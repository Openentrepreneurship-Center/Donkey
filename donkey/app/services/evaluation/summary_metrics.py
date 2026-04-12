"""요약 품질 지표 7개 계산 함수.

sttbrief_turing/app/metrics/summary.py에서 이식.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from app.services.evaluation.medical import (
    extract_medical_terms,
    find_distorted_terms,
    normalize,
)


# ── 헬퍼 ──

def _split_sentences(text: str) -> list[str]:
    sents = re.split(r"[.?!。]\s*", text)
    return [s.strip() for s in sents if s.strip() and len(s.strip()) >= 3]


def _sentence_similarity(s1: str, s2: str) -> float:
    return SequenceMatcher(None, normalize(s1), normalize(s2)).ratio()


def _find_best_match(sentence: str, source_sentences: list[str]) -> float:
    if not source_sentences:
        return 0.0
    return max(_sentence_similarity(sentence, src) for src in source_sentences)


# ── 1. Summarization Velocity ──

def compute_summarization_velocity(
    summarization_time_ms: int | float,
    audio_duration_sec: float,
) -> tuple[float, dict]:
    if audio_duration_sec <= 0:
        return 0.0, {
            "summarization_time_ms": int(summarization_time_ms),
            "audio_duration_sec": 0.0,
            "velocity": 0.0,
        }
    velocity = (summarization_time_ms / 1000.0) / audio_duration_sec
    return round(velocity, 4), {
        "summarization_time_ms": int(summarization_time_ms),
        "audio_duration_sec": round(audio_duration_sec, 2),
        "velocity": round(velocity, 4),
    }


# ── 2. Hallucination Ratio ──

def compute_hallucination_ratio(
    transcript_text: str,
    summary_text: str,
    threshold: float = 0.3,
) -> tuple[float, dict]:
    summary_sents = _split_sentences(summary_text)
    transcript_sents = _split_sentences(transcript_text)

    if not summary_sents:
        return 0.0, {"total": 0, "hallucinated": 0, "examples": []}

    hallucinated = []
    for s in summary_sents:
        best_sim = _find_best_match(s, transcript_sents)
        if best_sim < threshold:
            hallucinated.append({"text": s[:60], "best_similarity": round(best_sim, 3)})

    ratio = len(hallucinated) / len(summary_sents)
    return round(ratio, 4), {
        "total": len(summary_sents),
        "hallucinated": len(hallucinated),
        "examples": hallucinated[:10],
    }


# ── 3. SSR (Semantic Similarity Ratio) ──

def compute_ssr(
    transcript_text: str,
    summary_text: str,
    threshold: float = 0.4,
) -> tuple[float, dict]:
    summary_sents = _split_sentences(summary_text)
    transcript_sents = _split_sentences(transcript_text)

    if not summary_sents:
        return 0.0, {"total": 0, "preserved": 0, "not_preserved": 0}

    preserved_count = 0
    for s in summary_sents:
        best_sim = _find_best_match(s, transcript_sents)
        if best_sim >= threshold:
            preserved_count += 1

    ratio = preserved_count / len(summary_sents)
    return round(ratio, 4), {
        "total": len(summary_sents),
        "preserved": preserved_count,
        "not_preserved": len(summary_sents) - preserved_count,
    }


# ── 4. ICR (Information Compression Ratio) ──

def compute_icr(transcript_text: str, summary_text: str) -> tuple[float, dict]:
    transcript_tokens = len(transcript_text.split())
    summary_tokens = len(summary_text.split())

    if transcript_tokens == 0:
        return 0.0, {"transcript_tokens": 0, "summary_tokens": 0}

    ratio = summary_tokens / transcript_tokens
    return round(ratio, 4), {
        "transcript_tokens": transcript_tokens,
        "summary_tokens": summary_tokens,
    }


# ── 5. Summary MDR (Medical Distortion Rate) ──

def compute_summary_mdr(summary_text: str) -> tuple[float, dict]:
    terms = extract_medical_terms(summary_text)
    distortions = find_distorted_terms(summary_text)

    total = len(terms) + len(distortions)
    if total == 0:
        return 0.0, {"medical_terms": 0, "distorted": 0, "distortions": []}

    ratio = len(distortions) / total
    return round(ratio, 4), {
        "medical_terms": len(terms),
        "distorted": len(distortions),
        "distortions": distortions[:10],
    }


# ── 6. MIR (Medical Information Recall) ──

def compute_mir(transcript_text: str, summary_text: str) -> tuple[float, dict]:
    transcript_terms = set(extract_medical_terms(transcript_text))
    summary_terms = set(extract_medical_terms(summary_text))

    if not transcript_terms:
        return 1.0, {
            "transcript_terms": 0,
            "summary_terms": len(summary_terms),
            "recalled": 0,
            "missed_terms": [],
        }

    recalled = transcript_terms & summary_terms
    missed = transcript_terms - summary_terms

    ratio = len(recalled) / len(transcript_terms)
    return round(ratio, 4), {
        "transcript_terms": len(transcript_terms),
        "summary_terms": len(summary_terms),
        "recalled": len(recalled),
        "missed_terms": sorted(missed),
    }


# ── 7. SSA (Structured Summary Accuracy) ──

_SOAP_KEYWORDS = {
    "S": ["호소", "불편", "통증", "증상", "느끼", "아프", "걱정", "힘들",
          "어지러", "두통", "기침", "가래", "숨", "열"],
    "O": ["검사", "수치", "혈압", "혈당", "X-ray", "CT", "MRI", "초음파",
          "결과", "소견", "진찰", "측정", "mg", "mmHg", "bpm", "%"],
    "A": ["진단", "의심", "추정", "판단", "소견", "가능성", "질환",
          "증후군", "염", "암"],
    "P": ["처방", "투약", "수술", "검사 예정", "의뢰", "재방문", "치료",
          "약", "주사", "물리치료", "경과 관찰", "입원", "퇴원", "예약", "추적"],
}


def _detect_soap_section(text: str) -> str | None:
    scores = {}
    text_lower = text.lower()
    for section, keywords in _SOAP_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in text_lower)
        scores[section] = score
    if max(scores.values()) == 0:
        return None
    return max(scores, key=scores.get)


def compute_ssa(summary_sections: dict[str, list[str]]) -> tuple[float, dict]:
    total = 0
    correct = 0
    details = []

    for section, sentences in summary_sections.items():
        if section not in ("S", "O", "A", "P"):
            continue
        for sent in sentences:
            total += 1
            detected = _detect_soap_section(sent)
            is_correct = detected == section
            if is_correct:
                correct += 1
            details.append({
                "section": section,
                "detected": detected,
                "correct": is_correct,
                "text": sent[:50],
            })

    accuracy = correct / total if total > 0 else 0.0
    return round(accuracy, 4), {
        "total": total,
        "correct": correct,
        "details": details[:20],
    }
