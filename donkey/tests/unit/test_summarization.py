"""SOAP → ConsultationSummary 파싱 (LLM 없음)."""

from app.schemas.response import ConsultationSummary
from app.services.summarization import parse_soap_to_consultation_summary


def test_parse_soap_sections_and_conversation():
    soap = """
Subjective (S)
- 두통이 심합니다
- 며칠 전부터

Objective (O)
- 혈압 정상

Assessment (A)
- 긴장성 두통 의심

Plan (P)
- 진통제 처방
"""
    lines = [
        "[SPEAKER_00] 00:01.0–00:05.0: 어디가 아프세요?",
        "[원장님] 다음에 오세요",
        "[SPEAKER_01] 00:06.0–00:10.0: 머리가 아파요",
    ]
    cs = parse_soap_to_consultation_summary(soap, lines)
    assert isinstance(cs, ConsultationSummary)
    assert any("두통" in s for s in cs.symptomRecord)
    assert any("혈압" in s for s in cs.testResults)
    assert any("긴장" in s for s in cs.doctorNotes)
    assert any("진통" in s for s in cs.prescriptionAndCare)
    roles = {c.role for c in cs.conversationContent}
    assert "원장님" in roles
    assert "환자" in roles
