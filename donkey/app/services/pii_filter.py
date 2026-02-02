import re


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
    # Name patterns are tricky - we'll use a heuristic for common patterns
    # like "환자 김OO" or "OOO 환자"
    "name_pattern1": (
        r"(?:환자|보호자)\s*[가-힣]{2,4}(?:씨|님)?",
        "[이름]",
    ),
    "name_pattern2": (
        r"[가-힣]{2,4}(?:씨|님)\s*(?:환자|보호자)",
        "[이름]",
    ),
}


def filter_pii(text: str) -> str:
    """
    Filter personally identifiable information from text.
    Replaces detected PII with placeholder tags.
    """
    result = text

    for pattern_name, (pattern, replacement) in PATTERNS.items():
        result = re.sub(pattern, replacement, result)

    return result


def filter_pii_from_lines(lines: list[str]) -> list[str]:
    """Filter PII from a list of text lines."""
    return [filter_pii(line) for line in lines]
