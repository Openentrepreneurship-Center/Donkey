"""
Speaker labeling (화자 라벨링).

=== 룰 구조 (불릿 정리) ===

■ 설정 분기
• use_llm_only_speaker_labeling=True (권장): 턴 기반 + LLM만 사용 (오디오/클러스터링/Resemblyzer 없음)
• use_llm_only_speaker_labeling=False: 오디오 특징(Resemblyzer 또는 MFCC) + 시간 연결 클러스터링 + LLM 역할 분류

■ 경로 A: use_llm_only_speaker_labeling=True (턴 기반)
• valid 세그먼트: (end - start) >= min_segment_duration(0.6초) 이고 텍스트 있는 것만
• build_turns (화자 경계 고려)
  - 이전 끝~다음 시작 간격 < 0.4초이고, 턴 길이 ≤ 25초일 때만 묶음
  - 다음 구간이 짧은 응답어(네/아니요/맞아요 등) 또는 3글자 이하면 무조건 새 턴 (화자 전환 가능성)
• _label_turns_by_llm(turns): 턴당 텍스트 합쳐서 LLM에 보냄
  - 5턴 단위로만 청크 (국소 판단; 35턴은 대화 요약 수준이라 제거)
  - 프롬프트 길이 제한 4000자
  - DOCTOR/PATIENT 정의: 의사=질문·질병/증상 설명·처방/지시, 환자=자기 증상 호소·답변·궁금한 것 질문
• 턴 라벨을 해당 턴 안의 모든 세그먼트에 전파 → (start, end, SPEAKER_00/01) 반환

■ 경로 B: use_llm_only_speaker_labeling=False (오디오 기반)
• 오디오 로드(16kHz mono) 후 구간별 특징 추출
  - use_resemblyzer_embedding=True: Resemblyzer 화자 임베딩(256차원)
  - False: MFCC(13) + delta-MFCC(13) + pitch + energy(28차원)
• cluster_speakers: 시간 연결 제약 AgglomerativeClustering(k=2), 인접 구간만 병합 가능
• 턴 단위 재클러스터링: 같은 클러스터 라벨이 연속된 구간을 턴으로 묶고, 턴별 특징으로 다시 클러스터링 후 세그먼트에 재할당
• 클러스터별 텍스트 모아서 classify_roles_with_llm → cluster_0/1 중 DOCTOR/PATIENT 결정
• assign_roles_to_segments: 클러스터 라벨 → SPEAKER_00(의사), SPEAKER_01(환자)
• 후처리
  - 짧은 구간(1초 미만): 이전 구간과 화자 다르면 이전 화자로 통일
  - 고립 전환: 앞·뒤 구간과 둘 다 다른 화자인 구간 → 이전 화자로 통일
"""
import json
import re
from pathlib import Path

import librosa
import numpy as np
from openai import OpenAI
from scipy.sparse import csr_matrix
from sklearn.cluster import AgglomerativeClustering

from app.config import get_settings
from app.services.transcription import seconds_to_time_str

try:
    from resemblyzer import VoiceEncoder as _VoiceEncoder
    _RESEMBLYZER_AVAILABLE = True
except ImportError:
    _VoiceEncoder = None
    _RESEMBLYZER_AVAILABLE = False

# 현재는 2명(의사/환자). 나중에 3명 이상 화자 확장 가능
N_SPEAKERS = 2

F0_MIN = 75.0
F0_MAX = 300.0
N_MFCC = 13
# MFCC(13) + delta-MFCC(13) + pitch + energy; pitch/energy weighted for voice character
PITCH_ENERGY_WEIGHT = 2.0
FEATURE_DIM = N_MFCC * 2 + 1 + 1


def extract_segment_features(y: np.ndarray, sr: int) -> np.ndarray:
    """
    One feature vector per segment: [MFCC_mean(13), delta_MFCC_mean(13), pitch_mean, energy_mean].
    Delta-MFCC helps separate speakers; pitch/energy scaled for balance.
    """
    if len(y) < 256:
        return np.zeros(FEATURE_DIM, dtype=np.float32)

    n_fft = min(2048, len(y) // 4)
    hop = min(512, max(64, len(y) // 8))
    mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=N_MFCC, n_fft=n_fft, hop_length=hop)
    mfcc_mean = np.mean(mfcc, axis=1).astype(np.float32)
    # Delta (first derivative) over time -> mean per coefficient
    if mfcc.shape[1] > 1:
        delta_mfcc = np.diff(mfcc, axis=1)
        delta_mean = np.mean(delta_mfcc, axis=1).astype(np.float32)
    else:
        delta_mean = np.zeros(N_MFCC, dtype=np.float32)

    frame_len = min(2048, max(256, len(y) // 4))
    hop_len = min(512, max(64, len(y) // 8))
    f0 = librosa.yin(y, fmin=F0_MIN, fmax=F0_MAX, sr=sr, frame_length=frame_len, hop_length=hop_len)
    f0_valid = f0[~(np.isnan(f0) | (f0 <= 0))]
    pitch_mean = float(np.mean(f0_valid)) if len(f0_valid) > 0 else 0.0
    rms = librosa.feature.rms(y=y)[0]
    energy_mean = float(np.mean(rms))

    pitch_energy = np.array([pitch_mean * PITCH_ENERGY_WEIGHT, energy_mean * PITCH_ENERGY_WEIGHT], dtype=np.float32)
    return np.concatenate([mfcc_mean, delta_mean, pitch_energy])


RESEMBLYZER_EMBED_DIM = 256
_MIN_SAMPLES_FOR_EMBED = 1600  # ~0.1s at 16kHz; Resemblyzer needs enough audio


def _embed_segment_resemblyzer(encoder, y_slice: np.ndarray, sr: int) -> np.ndarray:
    """Resemblyzer로 구간 하나 임베딩. 16kHz mono float 기대. 짧으면 zeros 반환."""
    if len(y_slice) < _MIN_SAMPLES_FOR_EMBED:
        return np.zeros(RESEMBLYZER_EMBED_DIM, dtype=np.float32)
    try:
        # Resemblyzer는 16kHz 기대
        if sr != 16000:
            y_slice = librosa.resample(y_slice.astype(np.float32), orig_sr=sr, target_sr=16000)
        emb = encoder.embed_utterance(y_slice.astype(np.float32))
        return emb.astype(np.float32)
    except Exception:
        return np.zeros(RESEMBLYZER_EMBED_DIM, dtype=np.float32)


def _extract_features_for_segments(
    valid: list[dict],
    y: np.ndarray,
    sr: int,
    use_resemblyzer: bool,
) -> list[np.ndarray]:
    """구간별 특징 벡터. use_resemblyzer=True면 Resemblyzer 임베딩(256차원), 아니면 MFCC+피치(28차원)."""
    if use_resemblyzer and _RESEMBLYZER_AVAILABLE and _VoiceEncoder is not None:
        encoder = _VoiceEncoder("cpu")
        features = []
        for s in valid:
            start_sample = int(s["start"] * sr)
            end_sample = int(s["end"] * sr)
            start_sample = min(max(0, start_sample), len(y) - 1)
            end_sample = min(max(start_sample + 1, end_sample), len(y))
            slice_y = y[start_sample:end_sample]
            features.append(_embed_segment_resemblyzer(encoder, slice_y, sr))
        return features
    features = []
    for s in valid:
        start_sample = int(s["start"] * sr)
        end_sample = int(s["end"] * sr)
        start_sample = min(max(0, start_sample), len(y) - 1)
        end_sample = min(max(start_sample + 1, end_sample), len(y))
        slice_y = y[start_sample:end_sample]
        features.append(extract_segment_features(slice_y, sr))
    return features


def _connectivity_chain(n: int):
    """Adjacent segments (0-1, 1-2, ..., n-2-n-1) can be merged. Same speaker tends to stay contiguous."""
    if n < 2:
        return None
    rows = list(range(n - 1)) + list(range(1, n))
    cols = list(range(1, n)) + list(range(n - 1))
    data = [1] * (2 * (n - 1))
    return csr_matrix((data, (rows, cols)), shape=(n, n))


def cluster_speakers(feature_vectors: list[np.ndarray], connectivity: bool = True) -> np.ndarray:
    """
    Time-constrained AgglomerativeClustering: only adjacent segments (in time order)
    can be merged. Produces temporally contiguous speaker blocks.
    """
    n = len(feature_vectors)
    X = np.stack(feature_vectors)
    X = (X - np.mean(X, axis=0)) / (np.std(X, axis=0) + 1e-8)
    conn = _connectivity_chain(n) if connectivity and n >= 2 else None
    if conn is not None:
        model = AgglomerativeClustering(
            n_clusters=N_SPEAKERS,
            connectivity=conn,
            linkage="average",
            metric="euclidean",
        )
        labels = model.fit_predict(X)
    else:
        labels = np.zeros(n, dtype=np.int32)
    return labels


def _turns_from_labels(labels: np.ndarray) -> list[tuple[int, int]]:
    """Consecutive segments with same label -> one turn. Returns list of (start_idx, end_idx)."""
    if len(labels) == 0:
        return []
    ranges = []
    start = 0
    for i in range(1, len(labels)):
        if labels[i] != labels[start]:
            ranges.append((start, i - 1))
            start = i
    ranges.append((start, len(labels) - 1))
    return ranges


def _get_openai_client() -> OpenAI:
    settings = get_settings()
    return OpenAI(api_key=settings.openai_api_key)


def classify_roles_with_llm(cluster_0_text: str, cluster_1_text: str) -> dict[str, str]:
    """
    Text-based role classification. LLM decides which cluster is DOCTOR vs PATIENT
    from diagnostic questions, treatment explanation, symptoms, conversation control.
    Returns {"cluster_0_role": "DOCTOR"|"PATIENT", "cluster_1_role": "DOCTOR"|"PATIENT"}.
    """
    settings = get_settings()
    client = _get_openai_client()

    system = (
        "You are a classifier for medical consultation transcripts. "
        "There are exactly two speakers: one DOCTOR, one PATIENT. "
        "Decide roles based on: who asks diagnostic questions, who explains treatment, "
        "who describes symptoms, and who controls the conversation. "
        "Respond with a single JSON object only, no other text."
    )
    user = f"""Two speakers' transcript parts are below. Assign each cluster to either DOCTOR or PATIENT.

Cluster 0 transcript:
{cluster_0_text[:8000]}

Cluster 1 transcript:
{cluster_1_text[:8000]}

Respond with exactly this JSON (use DOCTOR or PATIENT):
{{"cluster_0_role": "DOCTOR or PATIENT", "cluster_1_role": "DOCTOR or PATIENT"}}"""

    try:
        resp = client.chat.completions.create(
            model=settings.chat_model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.1,
            max_tokens=100,
        )
        text = (resp.choices[0].message.content or "").strip()
        # Allow markdown code block
        if "```" in text:
            text = re.sub(r"```(?:json)?\s*", "", text).strip()
        data = json.loads(text)
        c0 = (data.get("cluster_0_role") or "PATIENT").upper()
        c1 = (data.get("cluster_1_role") or "PATIENT").upper()
        if c0 not in ("DOCTOR", "PATIENT"):
            c0 = "PATIENT"
        if c1 not in ("DOCTOR", "PATIENT"):
            c1 = "PATIENT"
        return {"cluster_0_role": c0, "cluster_1_role": c1}
    except (json.JSONDecodeError, KeyError, Exception):
        return {"cluster_0_role": "DOCTOR", "cluster_1_role": "PATIENT"}


def assign_roles_to_segments(labels: np.ndarray, role_map: dict[str, str]) -> list[str]:
    """
    Map cluster labels to speaker labels. DOCTOR -> SPEAKER_00, PATIENT -> SPEAKER_01.
    """
    c0_role = role_map.get("cluster_0_role", "PATIENT")
    c1_role = role_map.get("cluster_1_role", "PATIENT")
    speaker_0 = "SPEAKER_00" if c0_role == "DOCTOR" else "SPEAKER_01"
    speaker_1 = "SPEAKER_00" if c1_role == "DOCTOR" else "SPEAKER_01"
    return [speaker_0 if lab == 0 else speaker_1 for lab in labels]


# 다음 구간이 이걸로 시작/동일하면 화자 전환 가능성 높음 → 턴 분리 (의사 질문 뒤 "네" 등)
SHORT_RESPONSE_SET = frozenset(
    s.strip()
    for s in (
        "네", "아니요", "맞아요", "응", "아니", "글쎄요", "몰라요", "네네", "아니에요", "그래요",
        "좋아요", "알겠어요", "그럴게요", "예", "아", "음", "네?", "아니요?", "맞아요?",
    )
)


# 이전이 질문(?)이고 다음이 이걸로 시작하면 같은 화자 부연 가능 → 묶음 유지
QUESTION_CONTINUATION_PREFIXES = ("제가", "그래서", "그런데", "저는", "그래요", "아", "음", "네 ", "아니 ")


def _is_likely_speaker_change(prev_text: str, next_text: str) -> bool:
    """
    화자 전환 가능성 높으면 True → 턴 병합하지 않고 새 턴 시작.
    - 다음이 짧은 응답어(네/아니요 등) 또는 3글자 이하
    - 또는 이전이 질문(?)으로 끝나고 다음이 긴 문장인데, 이어지는 말(제가/그래서 등)로 시작하지 않음
      → 질문 뒤 다른 화자 설명("현재 관절염의...")으로 넘어간 경우
    """
    next_ = (next_text or "").strip()
    prev_ = (prev_text or "").strip()
    if not next_:
        return False
    if len(next_) <= 3:
        return True
    if next_ in SHORT_RESPONSE_SET:
        return True
    # 이전이 ?로 끝나고, 다음이 길면(설명 가능성) 이어지는 말로 시작하는지 확인
    if prev_.endswith("?") and len(next_) >= 8:
        if any(next_.startswith(p) for p in QUESTION_CONTINUATION_PREFIXES):
            return False  # 같은 화자 부연 → 묶음
        return True  # 질문 뒤 긴 문장인데 이어지는 말 아님 → 화자 전환 가능
    return False


def build_turns(
    segments: list[dict],
    gap_threshold: float = 0.4,
    max_turn_duration_sec: float = 25.0,
) -> list[list[dict]]:
    """
    화자 경계를 고려한 발화 블록(턴) 생성.
    - 시간 간격 < gap_threshold 이고, 턴 길이 제한 내이고,
    - 다음 구간이 짧은 응답어(네/아니요 등)가 아니어야 묶음 (화자 전환 가능성 시 분리)
    - 턴 길이 > max_turn_duration_sec 면 강제 새 턴
    """
    if not segments:
        return []
    turns = []
    current = [segments[0]]
    for prev, seg in zip(segments, segments[1:]):
        gap = seg["start"] - prev["end"]
        turn_duration = current[-1]["end"] - current[0]["start"]
        prev_text = (current[-1].get("text") or "").strip()
        next_text = (seg.get("text") or "").strip()
        # 화자 전환 가능성: 다음이 응답어면 묶지 않음
        if _is_likely_speaker_change(prev_text, next_text):
            turns.append(current)
            current = [seg]
            continue
        if gap < gap_threshold and (turn_duration + (seg["end"] - seg["start"])) <= max_turn_duration_sec:
            current.append(seg)
        else:
            turns.append(current)
            current = [seg]
    turns.append(current)
    return turns


# LLM은 국소 판단에 강함. 35턴은 대화 요약 수준 → 5턴 단위로만 넘김
TURNS_PER_LLM_CALL = 5
TURN_PROMPT_MAX_CHARS = 4000


def _label_turns_by_llm(turns: list[list[dict]], max_chars: int = TURN_PROMPT_MAX_CHARS) -> list[str]:
    """
    턴(발화 블록) 단위로 LLM이 DOCTOR/PATIENT 판단. 턴이 많으면 여러 번 호출 후 합침.
    Returns list of "SPEAKER_00" or "SPEAKER_01" per turn.
    """
    settings = get_settings()
    client = _get_openai_client()
    all_labels = []

    for chunk_start in range(0, len(turns), TURNS_PER_LLM_CALL):
        chunk = turns[chunk_start : chunk_start + TURNS_PER_LLM_CALL]
        lines = []
        for i, turn in enumerate(chunk):
            text = " ".join((s.get("text") or "").strip() for s in turn).strip()
            if not text:
                text = "(무음)"
            line = f"Turn {i}: {text}"
            if lines and len("\n".join(lines)) + len(line) + 1 > max_chars:
                break
            lines.append(line)
        num_in_prompt = len(lines)
        if num_in_prompt == 0:
            all_labels.extend(["SPEAKER_00"] * len(chunk))
            continue

        transcript = "\n".join(lines)
        system = (
            "You are labeling a Korean medical consultation. "
            "Each line 'Turn N: ...' is one utterance from ONE speaker. "
            "Label each as DOCTOR or PATIENT. "
            "DOCTOR: 질문, 질병/증상 설명(예: '관절염의 증상이 있을 수 있고 통증이~'), 처방/지시. "
            "PATIENT: 자기 증상 호소(예: '저는 ~가 아파요'), 의사 질문에 대한 답변, 궁금한 것 질문(예: '~하는 게 좋아요?'). "
            "의사가 '증상이 있을 수 있고'처럼 질병을 설명하는 문맥이면 DOCTOR, 환자가 '저는 ~가 아프다'처럼 자기 상태를 말하면 PATIENT. "
            "Output JSON only, e.g. {\"turn_0\": \"DOCTOR\", \"turn_1\": \"PATIENT\"}."
        )
        user = f"Label each turn as DOCTOR or PATIENT.\n\n{transcript}\n\nJSON:"

        try:
            resp = client.chat.completions.create(
                model=settings.chat_model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                temperature=0.0,
                max_tokens=2048,
            )
            text = (resp.choices[0].message.content or "").strip()
            if "```" in text:
                text = re.sub(r"```(?:json)?\s*", "", text).strip()
            data = json.loads(text)
            last = "SPEAKER_00"
            for i in range(len(chunk)):
                if i < num_in_prompt:
                    role = (data.get(f"turn_{i}") or data.get(str(i)) or "").upper()
                    if role == "DOCTOR":
                        last = "SPEAKER_00"
                    elif role == "PATIENT":
                        last = "SPEAKER_01"
                all_labels.append(last)
        except (json.JSONDecodeError, KeyError, Exception):
            all_labels.extend(["SPEAKER_00"] * len(chunk))

    return all_labels


def map_external_speakers_to_roles(
    segments: list[dict],
) -> list[tuple[float, float, str]]:
    """
    외부 STT에서 나온 화자 라벨을 의사(1명) / 환자(1명 이상)로 매핑.
    LLM으로 역할 분류 후 SPEAKER_00=의사, SPEAKER_01/02/...=환자 순으로 부여.
    segments: [{"start", "end", "text", "speaker": "1"|"2"|...}, ...]
    Returns: [(start_sec, end_sec, "SPEAKER_00"|"SPEAKER_01"|...), ...] (입력과 동일 순서)
    """
    if not segments:
        return []
    if len(segments) == 1:
        return [(segments[0]["start"], segments[0]["end"], "SPEAKER_00")]

    # 화자별 텍스트 모음 (라벨 문자열 기준)
    by_speaker: dict[str, list[str]] = {}
    for s in segments:
        label = s.get("speaker")
        if label is None:
            label = "0"
        key = str(label)
        if key not in by_speaker:
            by_speaker[key] = []
        text = (s.get("text") or "").strip()
        if text:
            by_speaker[key].append(text)

    # 등장 순서 유지 (첫 등장 순)
    seen_order: list[str] = []
    for s in segments:
        key = str(s.get("speaker") or "0")
        if key not in seen_order:
            seen_order.append(key)

    # LLM: 의사 1명, 환자 0명 이상
    labels_sorted = sorted(by_speaker.keys(), key=lambda x: (seen_order.index(x) if x in seen_order else 999, x))
    transcript_parts = []
    for lab in labels_sorted:
        texts = by_speaker.get(lab, [])
        transcript_parts.append(f"Speaker {lab}:\n" + "\n".join(texts[:50]))  # 상위 50문장으로 제한
    transcript_blob = "\n\n".join(transcript_parts)[:12000]

    settings = get_settings()
    client = _get_openai_client()
    system = (
        "You are a classifier for Korean medical consultation transcripts. "
        "Each 'Speaker N' is one person. Exactly one speaker is the doctor (의사). "
        "The rest are patients (환자). There can be one or multiple patients. "
        "Respond with a single JSON object only: map each speaker label to 'doctor' or 'patient'. "
        "Example: {\"1\": \"doctor\", \"2\": \"patient\", \"3\": \"patient\"}"
    )
    user = f"""Classify each speaker as doctor or patient. One doctor, rest patients.

{transcript_blob}

Respond with JSON only, e.g. {{"1": "doctor", "2": "patient"}}:"""

    try:
        resp = client.chat.completions.create(
            model=settings.chat_model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.0,
            max_tokens=256,
        )
        text = (resp.choices[0].message.content or "").strip()
        if "```" in text:
            text = re.sub(r"```(?:json)?\s*", "", text).strip()
        role_by_label = json.loads(text)
    except (json.JSONDecodeError, KeyError, Exception):
        role_by_label = {}

    # raw speaker label -> SPEAKER_00 (의사 1명), SPEAKER_01, SPEAKER_02, ... (환자 순)
    doctor_label: str | None = None
    patient_labels: list[str] = []
    for lab in labels_sorted:
        role = (role_by_label.get(str(lab)) or "patient").lower()
        if role == "doctor":
            doctor_label = lab
        else:
            patient_labels.append(lab)
    if not doctor_label and labels_sorted:
        doctor_label = labels_sorted[0]
        patient_labels = [l for l in labels_sorted if l != doctor_label]
    label_to_speaker: dict[str, str] = {}
    if doctor_label is not None:
        label_to_speaker[doctor_label] = "SPEAKER_00"
    for i, lab in enumerate(patient_labels):
        label_to_speaker[lab] = f"SPEAKER_{i + 1:02d}"

    out: list[tuple[float, float, str]] = []
    for s in segments:
        key = str(s.get("speaker") or "0")
        sp = label_to_speaker.get(key, "SPEAKER_01")
        out.append((s["start"], s["end"], sp))
    return out




def diarize_from_whisper_segments(
    wav_path: str | Path,
    segments: list[dict],
    sample_rate: int = 16000,
    min_segment_duration: float = 0.3,
) -> list[tuple[float, float, str]]:
    """
    use_llm_only_speaker_labeling=True: 발화 블록(턴) 생성(gap<0.8초 묶음) → LLM이 턴 단위 DOCTOR/PATIENT → 세그먼트에 전파.
    False: Resemblyzer 또는 MFCC + 시간 연결 클러스터링 + LLM 역할 분류.
    Returns list of (start_sec, end_sec, speaker_label) with SPEAKER_00=doctor, SPEAKER_01=patient.
    """
    valid = [
        s
        for s in segments
        if (s["end"] - s["start"]) >= min_segment_duration and (s.get("text") or "").strip()
    ]
    if not valid:
        return []
    if len(valid) == 1:
        return [(valid[0]["start"], valid[0]["end"], "SPEAKER_00")]

    settings = get_settings()
    if settings.use_llm_only_speaker_labeling:
        # 턴(발화 블록): gap < 0.4초만 묶고, 턴 길이 25초 초과 시 강제 분리 → LLM 턴별 DOCTOR/PATIENT → 전파
        turns = build_turns(valid, gap_threshold=0.4, max_turn_duration_sec=25.0)
        turn_labels = _label_turns_by_llm(turns)
        segment_labels = []
        for turn, label in zip(turns, turn_labels):
            for _ in turn:
                segment_labels.append(label)
        return [(s["start"], s["end"], segment_labels[i]) for i, s in enumerate(valid)]

    path = Path(wav_path)
    y, sr = librosa.load(str(path), sr=sample_rate, mono=True)
    use_resemblyzer = settings.use_resemblyzer_embedding and _RESEMBLYZER_AVAILABLE

    # 1) Segment-level features (Resemblyzer 화자 임베딩 또는 MFCC+피치) and first clustering
    features = _extract_features_for_segments(valid, y, sr, use_resemblyzer)
    labels = cluster_speakers(features)

    # 1b) Turn-level re-clustering: group consecutive same-label segments into turns,
    #     extract one feature per turn (longer audio = stabler), re-cluster turns.
    turn_ranges = _turns_from_labels(labels)
    if len(turn_ranges) >= 2:
        turn_features = []
        if use_resemblyzer and _VoiceEncoder is not None:
            encoder = _VoiceEncoder("cpu")
            for start_idx, end_idx in turn_ranges:
                t_start = valid[start_idx]["start"]
                t_end = valid[end_idx]["end"]
                start_s = int(t_start * sr)
                end_s = int(t_end * sr)
                start_s = min(max(0, start_s), len(y) - 1)
                end_s = min(max(start_s + 1, end_s), len(y))
                turn_audio = y[start_s:end_s]
                turn_features.append(_embed_segment_resemblyzer(encoder, turn_audio, sr))
        else:
            for start_idx, end_idx in turn_ranges:
                t_start = valid[start_idx]["start"]
                t_end = valid[end_idx]["end"]
                start_s = int(t_start * sr)
                end_s = int(t_end * sr)
                start_s = min(max(0, start_s), len(y) - 1)
                end_s = min(max(start_s + 1, end_s), len(y))
                turn_audio = y[start_s:end_s]
                turn_features.append(extract_segment_features(turn_audio, sr))
        turn_labels = cluster_speakers(turn_features)
        # Map turn label back to each segment
        labels = np.zeros(len(valid), dtype=np.int32)
        for turn_id, (start_idx, end_idx) in enumerate(turn_ranges):
            labels[start_idx : end_idx + 1] = turn_labels[turn_id]

    # 2) Concatenate text per cluster and classify roles with LLM
    cluster_0_text = " ".join((s.get("text") or "").strip() for s, lab in zip(valid, labels) if lab == 0)
    cluster_1_text = " ".join((s.get("text") or "").strip() for s, lab in zip(valid, labels) if lab == 1)
    role_map = classify_roles_with_llm(cluster_0_text, cluster_1_text)

    # 3) Assign SPEAKER_00/01 to segments
    speaker_labels = assign_roles_to_segments(labels, role_map)

    # 4) Consistency: short segments follow previous speaker
    short_threshold = 1.0
    for i in range(1, len(valid)):
        dur = valid[i]["end"] - valid[i]["start"]
        if dur < short_threshold and speaker_labels[i] != speaker_labels[i - 1]:
            speaker_labels[i] = speaker_labels[i - 1]

    # 5) Isolated flips: segment different from both neighbors -> follow previous
    for i in range(1, len(valid) - 1):
        prev_sp, curr_sp, next_sp = speaker_labels[i - 1], speaker_labels[i], speaker_labels[i + 1]
        if curr_sp != prev_sp and curr_sp != next_sp:
            speaker_labels[i] = prev_sp

    return [
        (s["start"], s["end"], speaker_labels[i])
        for i, s in enumerate(valid)
    ]
