"""
한국어 STT(Speech-to-Text) 성능 평가용 지표.

Reference(정답 전사)와 Hypothesis(인식 결과)를 비교하여
WER(Word Error Rate), CER(Character Error Rate)를 계산합니다.
긴 텍스트는 txt 파일 경로를 넘기는 *_from_files 를 사용하세요.
"""

import re
from pathlib import Path
from typing import Union


# 비교 시 제거: 특수문자(구두점·기호 등) 제거, 글자·숫자·공백만 유지
_SPECIAL_CHAR_RE = re.compile(r"[^\w\s]", re.UNICODE)

# 비교 시 제거할 추임새/짧은 응답 (단어 단위로만 제거, "네트워크" 등은 유지)
_FILLER_WORDS = frozenset({"음", "예", "네", "아", "어", "응", "네네", "예예", "으음"})


def _normalize_for_eval(text: str, strip_punctuation: bool = True) -> str:
    """한국어 STT 비교를 위한 전처리: 공백 정규화, (옵션) 특수문자·추임새 제거."""
    if not text:
        return ""
    text = text.strip()
    text = re.sub(r"\s+", " ", text)
    if strip_punctuation:
        # 특수문자 제거 후 연속 공백 하나로
        text = _SPECIAL_CHAR_RE.sub(" ", text)
        text = re.sub(r"\s+", " ", text).strip()
    # 추임새 제거 (단어 단위: "네"만 제거, "네트워크"는 유지)
    tokens = [t for t in text.split() if t not in _FILLER_WORDS]
    text = " ".join(tokens)
    return text


def _edit_distance(ref_seq: list[str], hyp_seq: list[str]) -> tuple[int, int, int, int]:
    """
    Levenshtein(편집 거리) 기반 최소 편집 횟수 계산.
    Returns: (total_edits, ref_len)
    """
    ref_len, hyp_len = len(ref_seq), len(hyp_seq)
    # dp[i][j] = ref[:i], hyp[:j] 까지의 최소 편집 비용
    dp = [[0] * (hyp_len + 1) for _ in range(ref_len + 1)]
    for i in range(ref_len + 1):
        dp[i][0] = i
    for j in range(hyp_len + 1):
        dp[0][j] = j
    for i in range(1, ref_len + 1):
        for j in range(1, hyp_len + 1):
            if ref_seq[i - 1] == hyp_seq[j - 1]:
                dp[i][j] = dp[i - 1][j - 1]
            else:
                dp[i][j] = 1 + min(
                    dp[i - 1][j - 1],  # substitution
                    dp[i - 1][j],      # deletion
                    dp[i][j - 1],      # insertion
                )
    # backtrace으로 S, D, I 개수 복원 (또는 단순히 total edits 사용)
    # 지표 정의: WER/CER = (S+D+I)/N 이고, total_edits = S+D+I 이므로
    total_edits = dp[ref_len][hyp_len]
    return total_edits, ref_len


def wer(
    reference: str,
    hypothesis: str,
    normalize: bool = True,
    strip_punctuation: bool = True,
) -> float:
    """
    Word Error Rate (단어 오류율).

    한국어 전사는 띄어쓰기로 단어를 구분한다고 가정합니다.
    Reference가 사람 전사(붙여쓰기), Hypothesis가 Whisper(띄어쓰기)면 WER이 높게 나올 수 있음.
    이 경우 Morpheme WER / CER을 보는 것을 권장합니다.
    Reference 길이가 0이면 0.0을 반환합니다.

    Returns:
        0.0 ~ 1.0 (1.0 = 100% 오류). 필요시 * 100 하여 % 사용.
    """
    if normalize:
        reference = _normalize_for_eval(reference, strip_punctuation=strip_punctuation)
        hypothesis = _normalize_for_eval(hypothesis, strip_punctuation=strip_punctuation)
    ref_words = reference.split() if reference else []
    hyp_words = hypothesis.split() if hypothesis else []
    if not ref_words:
        return 0.0
    edits, n = _edit_distance(ref_words, hyp_words)
    return edits / n


_kiwi = None  # kiwipiepy.Kiwi 인스턴스 (lazy 로딩)


def _tokenize_morphemes(text: str) -> list[str]:
    """한국어 형태소 분석으로 토큰 리스트 반환. kiwipiepy 사용."""
    global _kiwi
    try:
        from kiwipiepy import Kiwi
    except ImportError as e:
        raise ImportError(
            "Morpheme WER을 사용하려면 kiwipiepy가 필요합니다: pip install kiwipiepy"
        ) from e
    if not text or not text.strip():
        return []
    if _kiwi is None:
        _kiwi = Kiwi()
    tokens = _kiwi.tokenize(text.strip())
    return [t.form for t in tokens]


def morpheme_wer(
    reference: str,
    hypothesis: str,
    normalize: bool = True,
    strip_punctuation: bool = True,
) -> float:
    """
    Morpheme WER (형태소 단위 단어 오류율).

    한국어를 형태소 단위로 분리한 뒤, 형태소 시퀀스에 대해 WER을 계산합니다.
    띄어쓰기/어절 경계에 덜 민감하고 한국어 STT 평가에 자주 사용됩니다.
    Reference 형태소 수가 0이면 0.0을 반환합니다.

    Requires: kiwipiepy (pip install kiwipiepy)

    Returns:
        0.0 ~ 1.0. 필요시 * 100 하여 % 사용.
    """
    if normalize:
        reference = _normalize_for_eval(reference, strip_punctuation=strip_punctuation)
        hypothesis = _normalize_for_eval(hypothesis, strip_punctuation=strip_punctuation)
    ref_morphs = _tokenize_morphemes(reference)
    hyp_morphs = _tokenize_morphemes(hypothesis)
    if not ref_morphs:
        return 0.0
    edits, n = _edit_distance(ref_morphs, hyp_morphs)
    return edits / n


def cer(
    reference: str,
    hypothesis: str,
    normalize: bool = True,
    strip_punctuation: bool = True,
) -> float:
    """
    Character Error Rate (글자 오류율).

    한국어는 글자(음절) 단위로 비교합니다. (예: '한글' -> ['한', '글'])
    Reference 길이가 0이면 0.0을 반환합니다.

    Returns:
        0.0 ~ 1.0 (1.0 = 100% 오류). 필요시 * 100 하여 % 사용.
    """
    if normalize:
        reference = _normalize_for_eval(reference, strip_punctuation=strip_punctuation)
        hypothesis = _normalize_for_eval(hypothesis, strip_punctuation=strip_punctuation)
    ref_chars = list(reference) if reference else []
    hyp_chars = list(hypothesis) if hypothesis else []
    if not ref_chars:
        return 0.0
    edits, n = _edit_distance(ref_chars, hyp_chars)
    return edits / n


def soft_ser(
    reference: str,
    hypothesis: str,
    normalize: bool = True,
    strip_punctuation: bool = True,
) -> float:
    """
    Soft SER (Sentence Error Rate): 문장 단위 오류를 완화한 지표.

    줄 단위 1:1 비교해서, 각 줄마다 CER(글자 오류율)을 구한 뒤 그 평균을 반환.
    한 줄이 완전히 틀리면 1에 가깝고, 조금만 다르면 작은 값. ref 줄 수가 0이면 0.0 반환.
    """
    if normalize:
        ref_lines = [
            _normalize_for_eval(line.strip(), strip_punctuation=strip_punctuation)
            for line in reference.split("\n")
            if line.strip()
        ]
        hyp_lines = [
            _normalize_for_eval(line.strip(), strip_punctuation=strip_punctuation)
            for line in hypothesis.split("\n")
            if line.strip()
        ]
    else:
        ref_lines = [line.strip() for line in reference.split("\n") if line.strip()]
        hyp_lines = [line.strip() for line in hypothesis.split("\n") if line.strip()]
    if not ref_lines:
        return 0.0
    n_ref = len(ref_lines)
    n_pairs = min(n_ref, len(hyp_lines))
    total = 0.0
    for i in range(n_pairs):
        r, h = ref_lines[i], hyp_lines[i]
        ref_chars = list(r) if r else []
        hyp_chars = list(h) if h else []
        if not ref_chars:
            total += 0.0
        else:
            edits, n = _edit_distance(ref_chars, hyp_chars)
            total += edits / n
    # 짝 없는 ref 줄은 오류 1.0으로 침
    total += max(0, n_ref - len(hyp_lines)) * 1.0
    return total / n_ref


def _read_text(path: Union[str, Path], encoding: str = "utf-8") -> str:
    """txt 파일 내용을 읽어 반환."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"파일을 찾을 수 없습니다: {path}")
    return path.read_text(encoding=encoding)


def wer_from_files(
    reference_path: Union[str, Path],
    hypothesis_path: Union[str, Path],
    encoding: str = "utf-8",
    normalize: bool = True,
    strip_punctuation: bool = True,
) -> float:
    """
    Reference/Hypothesis를 txt 파일에서 읽어 WER 계산.

    Args:
        reference_path: 정답 전사가 담긴 txt 파일 경로.
        hypothesis_path: 인식 결과가 담긴 txt 파일 경로.
        encoding: 파일 인코딩. 기본 utf-8.
        normalize: 전처리(공백 정규화) 적용 여부.
        strip_punctuation: 구두점 제거 여부 (기본 True, 지표 완화).

    Returns:
        0.0 ~ 1.0 (1.0 = 100% 오류).
    """
    reference = _read_text(reference_path, encoding)
    hypothesis = _read_text(hypothesis_path, encoding)
    return wer(reference, hypothesis, normalize=normalize, strip_punctuation=strip_punctuation)


def morpheme_wer_from_files(
    reference_path: Union[str, Path],
    hypothesis_path: Union[str, Path],
    encoding: str = "utf-8",
    normalize: bool = True,
    strip_punctuation: bool = True,
) -> float:
    """
    Reference/Hypothesis를 txt 파일에서 읽어 Morpheme WER 계산.

    Args:
        reference_path: 정답 전사 txt 파일 경로.
        hypothesis_path: 인식 결과 txt 파일 경로.
        encoding: 파일 인코딩. 기본 utf-8.
        normalize: 전처리(공백 정규화) 적용 여부.
        strip_punctuation: 구두점 제거 여부 (기본 True).

    Returns:
        0.0 ~ 1.0 (형태소 단위 WER).
    """
    reference = _read_text(reference_path, encoding)
    hypothesis = _read_text(hypothesis_path, encoding)
    return morpheme_wer(
        reference, hypothesis, normalize=normalize, strip_punctuation=strip_punctuation
    )


def cer_from_files(
    reference_path: Union[str, Path],
    hypothesis_path: Union[str, Path],
    encoding: str = "utf-8",
    normalize: bool = True,
    strip_punctuation: bool = True,
) -> float:
    """
    Reference/Hypothesis를 txt 파일에서 읽어 CER 계산.

    Args:
        reference_path: 정답 전사가 담긴 txt 파일 경로.
        hypothesis_path: 인식 결과가 담긴 txt 파일 경로.
        encoding: 파일 인코딩. 기본 utf-8.
        normalize: 전처리(공백 정규화) 적용 여부.
        strip_punctuation: 구두점 제거 여부 (기본 True).

    Returns:
        0.0 ~ 1.0 (1.0 = 100% 오류).
    """
    reference = _read_text(reference_path, encoding)
    hypothesis = _read_text(hypothesis_path, encoding)
    return cer(
        reference, hypothesis, normalize=normalize, strip_punctuation=strip_punctuation
    )


def soft_ser_from_files(
    reference_path: Union[str, Path],
    hypothesis_path: Union[str, Path],
    encoding: str = "utf-8",
    normalize: bool = True,
    strip_punctuation: bool = True,
) -> float:
    """
    Reference/Hypothesis를 txt 파일에서 읽어 Soft SER 계산.

    줄 단위 1:1 비교, 문장별 CER의 평균.
    """
    reference = _read_text(reference_path, encoding)
    hypothesis = _read_text(hypothesis_path, encoding)
    return soft_ser(
        reference, hypothesis, normalize=normalize, strip_punctuation=strip_punctuation
    )
