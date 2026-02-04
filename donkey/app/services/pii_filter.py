import re
from typing import TypedDict


class ScreeningData(TypedDict):
    names: list[str]
    phones: list[str]


# Regex patterns for Korean PII
PATTERNS = {
    "phone": (
        r"01[016789]-?\d{3,4}-?\d{4}",  # Korean mobile
        "[전화번호]"
    ),
    "resident_id": (
        r"\d{6}-?[1-4]\d{6}",  # Korean resident registration number
        "[주민번호]"
    ),
    "card_number": (
        r"\d{4}-?\d{4}-?\d{4}-?\d{4}",  # Credit card
        "[카드번호]"
    ),
    # 이름: "환자 OOO씨/님" 형태만 (씨/님 필수 → "환자 들이" 등 일반 단어 제외)
    "name_pattern1": (
        r"(?:환자|보호자)\s*[가-힣]{2,4}(?:씨|님)",
        "[이름]",
    ),
    "name_pattern2": (
        r"[가-힣]{2,4}(?:씨|님)\s*(?:환자|보호자)",
        "[이름]",
    ),
}

# Patterns that yield screening output (capture group or full match)
PHONE_PATTERN = re.compile(r"01[016789]-?\d{3,4}-?\d{4}")
# 씨/님 필수: "환자 들이" 같은 일반 단어 오탐 방지
NAME_PATTERN_1 = re.compile(r"(?:환자|보호자)\s*([가-힣]{2,4})(?:씨|님)")
NAME_PATTERN_2 = re.compile(r"([가-힣]{2,4})(?:씨|님)\s*(?:환자|보호자)")

# 이름으로 잘못 잡기 쉬운 일반 단어 (스크리닝 제외)
NAME_BLOCKLIST = frozenset({
    "들이", "가능", "경우", "상태", "정도", "때로", "다음", "그때", "당시",
    "이후", "이전", "최근", "매우", "많이", "조금", "너무", "아주",
})


def filter_pii(text: str) -> str:
    """
    Filter personally identifiable information from text.
    Replaces detected PII with placeholder tags.
    """
    result = text

    for pattern_name, (pattern, replacement) in PATTERNS.items():
        result = re.sub(pattern, replacement, result)

    return result


def filter_pii_with_screening(text: str) -> tuple[str, ScreeningData]:
    """
    Filter PII from text and return (filtered_text, screening_data).
    screening_data contains names and phones as "[value]" for API output.
    """
    result = text
    names: list[str] = []
    seen_names: set[str] = set()
    phones: list[str] = []
    seen_phones: set[str] = set()

    # Collect phones and replace
    for m in PHONE_PATTERN.finditer(text):
        raw = m.group(0)
        if raw not in seen_phones:
            seen_phones.add(raw)
            phones.append(f"[{raw}]")
    result = PHONE_PATTERN.sub("[전화번호]", result)

    # Collect names (pattern1: "환자 홍길동씨" -> 홍길동; 씨/님 필수로 "들이" 등 오탐 방지)
    for m in NAME_PATTERN_1.finditer(text):
        name = m.group(1)
        if name not in seen_names and name not in NAME_BLOCKLIST:
            seen_names.add(name)
            names.append(f"[{name}]")
    result = NAME_PATTERN_1.sub("[이름]", result)

    for m in NAME_PATTERN_2.finditer(result):
        name = m.group(1)
        if name not in seen_names and name not in NAME_BLOCKLIST:
            seen_names.add(name)
            names.append(f"[{name}]")
    result = NAME_PATTERN_2.sub("[이름]", result)

    # Apply remaining PII patterns (no screening output)
    for pattern_name, (pattern, replacement) in PATTERNS.items():
        if pattern_name not in ("phone", "name_pattern1", "name_pattern2"):
            result = re.sub(pattern, replacement, result)

    return result, ScreeningData(names=names, phones=phones)


def filter_pii_from_lines(lines: list[str]) -> list[str]:
    """Filter PII from a list of text lines."""
    return [filter_pii(line) for line in lines]
