"""의료 용어 공통 유틸리티.

stt-api/app/services/evaluation/medical.py와 동일 로직.
Donkey-백엔드 경로에 맞게 medical_dict.json 위치만 조정.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

logger = logging.getLogger(__name__)

_medical_terms: list[str] = []
_term_set: set[str] = set()

_DICT_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "medical_dict.json"


def _load_dict() -> None:
    global _medical_terms, _term_set
    if _term_set:
        return

    if not _DICT_PATH.exists():
        logger.warning("의료 사전 파일 없음: %s", _DICT_PATH)
        return

    try:
        data = json.loads(_DICT_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("의료 사전 로드 실패: %s", exc)
        return

    terms: set[str] = set()
    for t in data.get("prompt_terms", []):
        if isinstance(t, str) and len(t) >= 2:
            terms.add(t.strip())
    for entry in data.get("entries", []):
        if not isinstance(entry, dict):
            continue
        correct = entry.get("correct", "") or entry.get("corrected", "")
        if correct and len(correct) >= 2:
            terms.add(correct.strip())
        wrong = entry.get("wrong", "") or entry.get("original", "")
        if wrong and len(wrong) >= 2:
            terms.add(wrong.strip())

    _medical_terms = sorted(terms)
    _term_set = terms
    logger.info("의료 사전 로드 완료: %d개 용어", len(_medical_terms))


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def extract_medical_terms(text: str) -> list[str]:
    _load_dict()
    if not text:
        return []
    text_norm = normalize(text)
    return [term for term in _medical_terms if term in text_norm]


def find_distorted_terms(
    text: str,
    similarity_threshold: float = 0.7,
    min_len: int = 2,
) -> list[dict]:
    _load_dict()
    if not text or not _medical_terms:
        return []

    text_norm = normalize(text)
    words = text_norm.replace(",", " ").replace(".", " ").split()
    candidates: list[str] = []
    for w in words:
        if len(w) >= min_len:
            candidates.append(w)
    for i in range(len(words) - 1):
        bigram = words[i] + words[i + 1]
        if min_len <= len(bigram) <= 10:
            candidates.append(bigram)

    distortions: list[dict] = []
    exact_terms = set(extract_medical_terms(text))

    for candidate in candidates:
        if candidate in _term_set:
            continue
        for term in _medical_terms:
            if term in exact_terms:
                continue
            if abs(len(candidate) - len(term)) > 2:
                continue
            sim = SequenceMatcher(None, candidate, term).ratio()
            if similarity_threshold <= sim < 1.0:
                distortions.append({
                    "found": candidate,
                    "expected": term,
                    "similarity": round(sim, 3),
                })
                break

    return distortions
