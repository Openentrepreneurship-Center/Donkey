import os
import argparse
import tempfile
from typing import List, Tuple

from dotenv import load_dotenv
from openai import OpenAI
from pyannote.audio import Pipeline
from pydub import AudioSegment
import subprocess
from pathlib import Path


# -----------------------
# .env 로드 (스크립트 폴더 기준)
# -----------------------
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
HF_TOKEN = os.getenv("HF_TOKEN", "").strip()

if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY가 없습니다. .env 파일을 확인하세요.")
if not HF_TOKEN:
    raise RuntimeError("HF_TOKEN이 없습니다. .env 파일을 확인하세요.")

# OpenAI client (명시적으로 키 주입)
client = OpenAI(api_key=OPENAI_API_KEY)

print("⏳ Loading pyannote pipeline (3.1)...")
diarization_pipeline = Pipeline.from_pretrained(
    "pyannote/speaker-diarization-3.1",
    use_auth_token=HF_TOKEN,  
)
print("✅ Diarization pipeline loaded.")


def ensure_wav_16k_mono(input_path: str) -> str:
    """
    m4a 등 포맷을 pyannote/torchaudio가 못 여는 경우가 많아서 wav(16k mono)로 변환
    """
    p = Path(input_path)
    if p.suffix.lower() == ".wav":
        return input_path

    out_path = str(p.with_suffix(".wav"))
    cmd = ["ffmpeg", "-y", "-i", input_path, "-ac", "1", "-ar", "16000", out_path]

    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError:
        raise RuntimeError("ffmpeg가 없습니다. `brew install ffmpeg`로 설치해줘.")
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"ffmpeg 변환 실패:\n{e.stderr.decode(errors='ignore')}")
    return out_path


def seconds_to_time_str(sec: float) -> str:
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:04.1f}"
    return f"{m:02d}:{s:04.1f}"


def diarize_audio(file_path: str, num_speakers: int | None = None) -> List[Tuple[float, float, str]]:
    print(f"🎧 Running diarization on: {file_path}")

    if num_speakers is not None:
        diarization = diarization_pipeline(file_path, num_speakers=num_speakers)
    else:
        diarization = diarization_pipeline(file_path)

    segments: List[Tuple[float, float, str]] = []
    for turn, _, speaker in diarization.itertracks(yield_label=True):
        segments.append((float(turn.start), float(turn.end), str(speaker)))

    segments.sort(key=lambda x: x[0])
    print(f"🧩 Found {len(segments)} speaker segments.")
    return segments


def transcribe_segment_with_whisper(
    audio_segment: AudioSegment,
    language: str = "ko",
    model: str = "gpt-4o-mini-transcribe",
) -> str:
    """
    한 segment를 임시 wav로 저장해서 OpenAI STT 호출
    """
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp:
        audio_segment.export(tmp.name, format="wav")
        with open(tmp.name, "rb") as f:
            result = client.audio.transcriptions.create(
                model=model,
                file=f,
                language=language,
            )
    return (result.text or "").strip()


def diarize_and_transcribe(
    file_path: str,
    language: str = "ko",
    model: str = "gpt-4o-mini-transcribe",
    num_speakers: int | None = None,
    min_segment_duration: float = 0.6,
) -> str:
    """
    diarization 구간별로 오디오를 잘라 STT -> [speaker] start–end: text 라인 생성
    """
    segments = diarize_audio(file_path, num_speakers=num_speakers)
    if not segments:
        return ""

    audio = AudioSegment.from_file(file_path)

    lines: List[str] = []
    for idx, (start, end, speaker) in enumerate(segments, start=1):
        duration = end - start
        if duration < min_segment_duration:
            continue

        seg_audio = audio[int(start * 1000): int(end * 1000)]

        print(
            f"  ▶ Segment {idx:03d} | {speaker} "
            f"| {seconds_to_time_str(start)}–{seconds_to_time_str(end)} "
            f"({duration:.2f}s)"
        )

        try:
            text = transcribe_segment_with_whisper(seg_audio, language=language, model=model)
        except Exception as e:
            print(f"    ❌ Whisper STT error: {e}")
            text = ""

        if not text:
            continue

        lines.append(f"[{speaker}] {seconds_to_time_str(start)}–{seconds_to_time_str(end)}: {text}")

    return "\n".join(lines)


def soap_summarize(
    diarized_text: str,
    chat_model: str = "gpt-4o-mini",
) -> str:
    """
    diarized 전사 텍스트를 SOAP 프레임워크로 요약
    """
    system = (
        "You are a clinical documentation assistant. "
        "Summarize the provided Korean medical conversation into SOAP format. "
        "Be factual, do not invent details. If unclear, say '불명확/언급 없음'. "
        "Write in Korean. Use concise bullet points. "
        "Do not include any personal identifiers beyond what is present in the transcript."
    )

    user = f"""아래는 진료 대화 전사(화자/시간 포함)입니다.
SOAP(Subjective, Objective, Assessment, Plan) 형식으로 요약해줘.

요구사항:
- 한국어
- S/O/A/P 각 섹션 제목 포함
- 각 섹션은 불릿 포인트로 간결하게
- 전사에 없는 내용은 절대 추가하지 말 것(추측 금지)
- 모호하면 "불명확" 또는 "언급 없음"으로 표시
- 진료 핵심(증상/병력/검사/설명/진단 추정/계획)을 우선

[전사]
{diarized_text}
"""
    resp = client.chat.completions.create(
        model=chat_model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.2,
    )
    return resp.choices[0].message.content.strip()


def process_single_file(
    audio_path: str,
    language: str = "ko",
    stt_model: str = "gpt-4o-mini-transcribe",
    chat_model: str = "gpt-4o-mini",
    num_speakers: int | None = None,
    min_seg: float = 0.6,
):
    """
    단일 파일을 처리하여 diarized와 SOAP 파일을 생성
    """
    audio_path_processed = ensure_wav_16k_mono(audio_path)
    if not os.path.exists(audio_path_processed):
        raise FileNotFoundError(f"파일이 없습니다: {audio_path_processed}")

    base = os.path.splitext(audio_path_processed)[0]
    # 원본 파일명 기준으로 출력 파일명 생성 (확장자만 제거)
    original_base = os.path.splitext(audio_path)[0]
    diarized_path = original_base + "_diarized.txt"
    soap_path = original_base + "_SOAP.txt"

    # 1) diarized 전사 생성
    print(f"\n{'='*60}")
    print(f"📁 Processing: {audio_path}")
    print(f"{'='*60}")
    diarized_text = diarize_and_transcribe(
        file_path=audio_path_processed,
        language=language,
        model=stt_model,
        num_speakers=num_speakers,
        min_segment_duration=min_seg,
    )

    if not diarized_text:
        print(f"⚠️ {audio_path}: diarized 전사 결과가 비어 있습니다(무음/너무 짧은 발화일 수 있음).")
        return

    with open(diarized_path, "w", encoding="utf-8") as f:
        f.write(diarized_text)
    print(f"✅ Saved diarized transcript: {diarized_path}")

    # 2) SOAP 요약 생성
    print(f"🧾 Generating SOAP summary for {audio_path}...")
    soap_text = soap_summarize(diarized_text, chat_model=chat_model)

    soap_text_final = (
        soap_text
        + "\n\n---\n"
        + "※ 참고: 이 문서는 전사 텍스트 기반 자동 요약이며, 의료적 판단/진단을 대체하지 않습니다.\n"
    )

    with open(soap_path, "w", encoding="utf-8") as f:
        f.write(soap_text_final)
    print(f"✅ Saved SOAP summary: {soap_path}")


def find_recording_file(recording_num: int, base_dir: str = ".") -> str | None:
    """
    Recording 번호에 해당하는 파일을 찾음 (다양한 확장자 지원)
    """
    possible_names = [
        f"Recording {recording_num}",
        f"Recording{recording_num}",
        f"recording {recording_num}",
        f"recording{recording_num}",
    ]
    possible_extensions = [".m4a", ".wav", ".mp3", ".mp4", ".aac"]
    
    for name in possible_names:
        for ext in possible_extensions:
            full_path = os.path.join(base_dir, name + ext)
            if os.path.exists(full_path):
                return full_path
    
    return None


def main():
    parser = argparse.ArgumentParser(description="pyannote(3.1) + OpenAI STT + SOAP 요약")
    parser.add_argument("audio", type=str, nargs="*", help="입력 오디오 파일 경로 (여러 개 가능) 또는 --numbers 옵션 사용")
    parser.add_argument("--numbers", type=int, nargs="+", help="Recording 번호 리스트 (예: --numbers 7 8 9 10 11 14 15)")
    parser.add_argument("--speakers", type=int, default=None, help="화자 수(알면 지정, 예: 2)")
    parser.add_argument("--language", type=str, default="ko", help="언어 코드(기본 ko)")
    parser.add_argument(
        "--stt_model",
        type=str,
        default="gpt-4o-mini-transcribe",
        help='STT 모델 (예: "gpt-4o-mini-transcribe" 또는 "whisper-1")',
    )
    parser.add_argument(
        "--chat_model",
        type=str,
        default="gpt-4o-mini",
        help='SOAP 요약용 Chat 모델 (예: "gpt-4o-mini")',
    )
    parser.add_argument(
        "--min_seg",
        type=float,
        default=0.6,
        help="이 값(초)보다 짧은 화자 구간은 스킵(기본 0.6)",
    )
    args = parser.parse_args()

    # 파일 목록 준비
    audio_files = []
    
    # --numbers 옵션이 있으면 Recording 파일 찾기
    if args.numbers:
        base_dir = os.path.dirname(os.path.abspath(__file__)) if __file__ else "."
        for num in args.numbers:
            found = find_recording_file(num, base_dir)
            if found:
                audio_files.append(found)
                print(f"✅ Found: Recording {num} -> {found}")
            else:
                print(f"⚠️ Warning: Recording {num} 파일을 찾을 수 없습니다.")
    
    # 직접 지정된 파일 경로 추가
    if args.audio:
        audio_files.extend(args.audio)
    
    if not audio_files:
        parser.error("파일을 지정해주세요. (예: python diarize_whisper.py Recording.wav 또는 --numbers 7 8 9)")

    print(f"\n🎯 총 {len(audio_files)}개 파일 처리 예정:")
    for f in audio_files:
        print(f"   - {f}")
    print()

    # 각 파일 처리
    success_count = 0
    for idx, audio_file in enumerate(audio_files, start=1):
        try:
            print(f"\n[{idx}/{len(audio_files)}] 처리 중...")
            process_single_file(
                audio_path=audio_file,
                language=args.language,
                stt_model=args.stt_model,
                chat_model=args.chat_model,
                num_speakers=args.speakers,
                min_seg=args.min_seg,
            )
            success_count += 1
        except Exception as e:
            print(f"❌ {audio_file} 처리 실패: {e}")
            continue

    print(f"\n{'='*60}")
    print(f"🎉 완료! {success_count}/{len(audio_files)}개 파일 처리 완료.")
    print(f"   총 {success_count * 2}개 파일 생성됨 (diarized + SOAP 각 {success_count}개)")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()