import json
import os
from pathlib import Path

import pytest

from app.services.summarization import (
    generate_simple_summary,
    generate_soap_summary,
    generate_title,
    parse_soap_to_consultation_summary,
)


def _load_sample_diarized_text() -> tuple[str, int]:
    fixture_path = Path(__file__).parent / "fixtures" / "summarization_live_sample.json"
    rows = json.loads(fixture_path.read_text(encoding="utf-8"))
    lines = [f"[{row['role']}] {row['content']}" for row in rows]
    return "\n".join(lines), len(lines)


@pytest.mark.skipif(
    not os.getenv("RUN_LIVE_OPENAI_TESTS"),
    reason="RUN_LIVE_OPENAI_TESTS=1 일 때만 실제 OpenAI 호출 테스트 실행",
)
def test_live_openai_summarization_smoke() -> None:
    if not os.getenv("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY가 없어 실제 호출 테스트를 건너뜁니다.")

    diarized_text, line_count = _load_sample_diarized_text()
    assert line_count > 0

    soap = generate_soap_summary(diarized_text)
    title = generate_title(diarized_text)
    simple = generate_simple_summary(diarized_text)
    parsed = parse_soap_to_consultation_summary(soap, diarized_text.splitlines())

    # 실호출 테스트는 모델 비결정성 때문에 최소 품질 조건만 검증합니다.
    assert isinstance(soap, str) and soap.strip() != ""
    assert isinstance(title, str) and title.strip() != ""
    assert isinstance(simple, str) and simple.strip() != ""

    soap_upper = soap.upper()
    assert any(section in soap_upper for section in ["SUBJECTIVE", "OBJECTIVE", "ASSESSMENT", "PLAN", "S", "O", "A", "P"])

    # 파싱 결과가 완전히 비어있지 않아야 함
    parsed_sections_count = (
        len(parsed.doctorNotes)
        + len(parsed.testResults)
        + len(parsed.symptomRecord)
        + len(parsed.prescriptionAndCare)
    )
    assert parsed_sections_count > 0
