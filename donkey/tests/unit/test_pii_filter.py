"""PII 마스킹 순수 로직."""

import pytest

from app.services.pii_filter import filter_pii, filter_pii_with_screening


@pytest.mark.parametrize(
    "text,expect_sub",
    [
        ("연락처 010-1234-5678", "[전화번호]"),
        ("test@example.com", "[이메일]"),
        ("900101-1234567", "[주민번호]"),
        ("접속 IP 192.168.0.1 확인", "[IP주소]"),
    ],
)
def test_filter_pii_masks_patterns(text, expect_sub):
    out = filter_pii(text)
    assert expect_sub in out


def test_filter_pii_with_screening_collects_phone():
    text = "환자분 010-9999-8888 로 연락"
    out, screening = filter_pii_with_screening(text)
    assert "[전화번호]" in out
    assert any("010" in p for p in screening["phones"])


def test_filter_pii_with_screening_patient_name():
    text = "환자 김철수씨 내원"
    out, screening = filter_pii_with_screening(text)
    assert "[이름]" in out
    assert any("김철수" in n for n in screening["names"])
