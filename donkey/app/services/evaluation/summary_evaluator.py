"""요약 7개 지표를 계산하고 hippo로 PATCH하는 오케스트레이터."""

from __future__ import annotations

import logging
from typing import Any

from app.services.evaluation.summary_metrics import (
    compute_hallucination_ratio,
    compute_icr,
    compute_mir,
    compute_ssa,
    compute_ssr,
    compute_summarization_velocity,
    compute_summary_mdr,
)

logger = logging.getLogger(__name__)

# ConsultationSummary 필드 → SOAP 키 매핑
SOAP_FIELD_MAP = {
    "symptomRecord": "S",
    "testResults": "O",
    "doctorNotes": "A",
    "prescriptionAndCare": "P",
}


def evaluate_summary_result(
    *,
    consultation_summary: dict,
    transcript_text: str,
    audio_duration_sec: float,
    summarization_time_ms: float,
) -> dict:
    """요약 결과를 받아 7개 지표를 계산하고 hippo PATCH용 payload를 반환.

    Returns:
        hippo PATCH 요청 바디 형태의 dict.
    """
    # SOAP 섹션 추출
    soap_sections: dict[str, list[str]] = {}
    all_text_parts: list[str] = []
    for field_name, soap_key in SOAP_FIELD_MAP.items():
        items = consultation_summary.get(field_name, [])
        sentences = [s for s in items if isinstance(s, str) and s.strip()]
        soap_sections[soap_key] = sentences
        all_text_parts.extend(sentences)

    summary_text = " ".join(all_text_parts)

    # 7개 지표 계산
    sv, sv_detail = compute_summarization_velocity(summarization_time_ms, audio_duration_sec)
    hr, hr_detail = compute_hallucination_ratio(transcript_text, summary_text)
    ssr_val, ssr_detail = compute_ssr(transcript_text, summary_text)
    icr_val, icr_detail = compute_icr(transcript_text, summary_text)
    smdr, smdr_detail = compute_summary_mdr(summary_text)
    mir_val, mir_detail = compute_mir(transcript_text, summary_text)
    ssa_val, ssa_detail = compute_ssa(soap_sections)

    # hippo PATCH payload
    return {
        "metrics": {
            "summary": {
                "summarization_velocity": sv,
                "hallucination_ratio": hr,
                "ssr": ssr_val,
                "icr": icr_val,
                "summary_mdr": smdr,
                "mir": mir_val,
                "ssa": ssa_val,
            },
        },
        "details": {
            "summary": {
                "summarization_velocity_detail": sv_detail,
                "hallucination_detail": hr_detail,
                "ssr_detail": ssr_detail,
                "icr_detail": icr_detail,
                "summary_mdr_detail": smdr_detail,
                "mir_detail": mir_detail,
                "ssa_detail": ssa_detail,
            },
        },
    }
