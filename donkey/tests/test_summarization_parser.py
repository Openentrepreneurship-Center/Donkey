from app.services.summarization import parse_soap_to_consultation_summary


def test_parse_soap_handles_markdown_bold_headers() -> None:
    soap_text = """**Subjective (S)**
- 환자는 오른쪽 다리 통증이 있다고 했습니다.

**Objective (O)**
- MRI에서 협착 소견이 있다고 했습니다.

**Assessment (A)**
- 척추관 협착증 가능성이 있다고 판단했습니다.

**Plan (P)**
- 소염진통제 복용과 경과 관찰을 권고했습니다.
"""

    diarized_lines = [
        "[환자] 오른쪽 다리가 아파요.",
        "[원장님] MRI상 협착 소견이 있습니다.",
    ]

    parsed = parse_soap_to_consultation_summary(soap_text, diarized_lines)

    assert parsed.symptomRecord == ["환자는 오른쪽 다리 통증이 있다고 했습니다."]
    assert parsed.testResults == ["MRI에서 협착 소견이 있다고 했습니다."]
    assert parsed.doctorNotes == ["척추관 협착증 가능성이 있다고 판단했습니다."]
    assert parsed.prescriptionAndCare == ["소염진통제 복용과 경과 관찰을 권고했습니다."]
