"""
PII 필터: HIPAA Safe Harbor 식별자 기준 적용.
이름, 주소(시 이하), 날짜(연도 제외 제거), 전화/이메일, 주민/SSN, 병원기록번호,
건강보험번호, 계좌번호, 차량번호, 디바이스ID, IP, 병원명 등 마스킹.
"""
import re
from typing import TypedDict


class ScreeningData(TypedDict):
    names: list[str]
    phones: list[str]


# ---- 기존 + HIPAA Safe Harbor 공통 패턴 (filter_pii에서 모두 적용) ----
# 적용 순서: 전화/이메일/주민/카드 등 숫자형 → 날짜 → 주소 → 이름/병원명 등
PATTERNS = {
    # 전화번호 (한국 휴대/지역)
    "phone": (
        r"01[016789]-?\d{3,4}-?\d{4}",
        "[전화번호]",
    ),
    "phone_landline": (
        r"0(?:2|31|32|33|41|42|43|44|51|52|53|54|55|61|62|63|64)-?\d{3,4}-?\d{4}",
        "[전화번호]",
    ),
    # 이메일 (HIPAA)
    "email": (
        r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9][a-zA-Z0-9.-]*\.[a-zA-Z]{2,}",
        "[이메일]",
    ),
    # 주민번호 / SSN (HIPAA)
    "resident_id": (
        r"\d{6}-?[1-4]\d{6}",
        "[주민번호]",
    ),
    "ssn": (
        r"\d{3}-\d{2}-\d{4}",
        "[사회보장번호]",
    ),
    # 카드/계좌 (HIPAA)
    "card_number": (
        r"\d{4}-?\d{4}-?\d{4}-?\d{4}",
        "[카드번호]",
    ),
    "account_number": (
        r"(?:계좌(?:번호)?|acct\.?)\s*:?\s*[\d\-]+",
        "[계좌번호]",
    ),
    # IP 주소 (HIPAA)
    "ipv4": (
        r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d{1,2})\.){3}(?:25[0-5]|2[0-4]\d|1?\d{1,2})\b",
        "[IP주소]",
    ),
    "ipv6": (
        r"\b(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}\b",
        "[IP주소]",
    ),
    # 디바이스 ID / UUID / IMEI (HIPAA)
    "uuid": (
        r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b",
        "[디바이스ID]",
    ),
    "imei_like": (
        r"(?:IMEI|디바이스\s*ID?)\s*:?\s*\d{15}",
        "[디바이스ID]",
    ),
    # 병원 기록번호 / 건강보험번호 (HIPAA): 키워드 인접 시만
    "medical_record_num": (
        r"(?:차트(?:번호)?|환자(?:번호)?|MRN|의무기록(?:번호)?)\s*:?\s*[\d\-]+",
        "[병원기록번호]",
    ),
    "health_insurance_num": (
        r"(?:건강보험(?:번호)?|보험(?:증)?번호)\s*:?\s*\d{10,12}",
        "[건강보험번호]",
    ),
    # 날짜: 연도 제외 전부 제거 (HIPAA) → [날짜]로 통일
    "date_ymd_slash": (
        r"\d{4}/\d{1,2}/\d{1,2}",
        "[날짜]",
    ),
    "date_ymd_dash": (
        r"\d{4}-\d{1,2}-\d{1,2}",
        "[날짜]",
    ),
    "date_korean": (
        r"\d{4}\s*년\s*\d{1,2}\s*월\s*\d{1,2}\s*일",
        "[날짜]",
    ),
    "date_korean_short": (
        r"\d{1,2}\s*월\s*\d{1,2}\s*일(?=\s|$|[,.])",
        "[날짜]",
    ),
    "date_dot": (
        r"\d{4}\.\d{1,2}\.\d{1,2}",
        "[날짜]",
    ),
    # 주소: 시 이하 (HIPAA) — 시/구/군/동/로/길 + 번지 등
    "address_si": (
        r"[가-힣]+(?:시|특별시|광역시)\s+[가-힣]+(?:구|군)\s+[가-힣]*(?:동|로|길)\s*\d+\-?\d*",
        "[주소]",
    ),
    "address_do": (
        r"[가-힣]+도\s+[가-힣]+(?:시|군)\s+[가-힣]*(?:동|로|길|읍|면)\s*\d+\-?\d*",
        "[주소]",
    ),
    # 차량번호 (HIPAA): 12가3456, 서울 12가 3456 등
    "vehicle_plate": (
        r"(?:차량(?:번호)?|번호판)\s*:?\s*[\d가-힣\s]+|\d{2}[가-힣]\s*\d{4}",
        "[차량번호]",
    ),
    # 병원명 (HIPAA)
    "hospital_name": (
        r"[가-힣A-Za-z0-9&·\s]+(?:병원|의원|클리닉|요양병원|한방병원|치과의원)",
        "[병원명]",
    ),
    # 이름: 환자/보호자 호칭 (기존)
    "name_pattern1": (
        r"(?:환자|보호자)\s*[가-힣]{2,4}(?:씨|님)",
        "[이름]",
    ),
    "name_pattern2": (
        r"[가-힣]{2,4}(?:씨|님)\s*(?:환자|보호자)",
        "[이름]",
    ),
    # 의료진 이름: OOO 원장/선생님/교수 (HIPAA 이름 확장)
    "name_doctor": (
        r"[가-힣]{2,4}\s*(?:원장|선생님|교수|의사선생)",
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
