import re
from functools import lru_cache

from openai import OpenAI

from app.config import get_settings
from app.schemas.response import ConsultationSummary, ConversationItem


@lru_cache(maxsize=1)
def get_openai_client() -> OpenAI:
    """Get OpenAI client (cached)."""
    settings = get_settings()
    return OpenAI(api_key=settings.openai_api_key)


def generate_soap_summary(diarized_text: str, chat_model: str = "gpt-4o-mini") -> str:
    """Generate SOAP summary from diarized transcript."""
    client = get_openai_client()

    system = (
        "You are a clinical documentation assistant. "
        "Summarize the provided Korean medical conversation into SOAP format. "
        "Be factual, do not invent details. If unclear, say '불명확/언급 없음'. "
        "Write in Korean. "
        "Use a consistent tone: write each bullet as a complete sentence in reported-speech or documentation style (e.g. '~했다고 했습니다', '~라고 했습니다', '~입니다'). "
        "Do not use telegraphic fragments (e.g. avoid '증상 개선 중' alone; write '환자는 증상이 개선되고 있다고 했습니다' or similar). "
        "For medical terms, use 한글(English) when appropriate (e.g. 혈당(Blood sugar), 비타민 D(Vitamin D)). "
        "Do not include any personal identifiers beyond what is present in the transcript."
    )

    user = f"""아래는 진료 대화 전사(화자/시간 포함)입니다.
SOAP(Subjective, Objective, Assessment, Plan) 형식으로 요약해줘.

요구사항:
- 한국어
- 반드시 섹션 제목을 한 줄에 쓴 뒤, 그 다음 줄부터 해당 섹션 내용을 적어줘.
  섹션 제목: Subjective (또는 S), Objective (또는 O), Assessment (또는 A), Plan (또는 P)
- 각 섹션 내용은 불릿(- 또는 •)으로 시작하는 문장으로 나열. 문장 톤: "~했다고 했습니다", "~라고 했습니다", "~입니다" 같은 전달형/기록형으로 한 문장씩 완결되게 쓸 것. (단순 단어 나열이나 생략형 금지)
- 전사에 없는 내용은 절대 추가하지 말 것(추측 금지)
- 모호하면 "불명확" 또는 "언급 없음"으로 표시
- 진료 핵심(증상/병력/검사/설명/진단 추정/계획)을 우선. 의학 용어는 필요 시 한글(English)로 표기
- 질문 문장 앞에 Q. 등 접두사 붙이지 말 것

[전사]
{diarized_text}
"""
    resp = client.chat.completions.create(
        model=chat_model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.2,
    )
    return resp.choices[0].message.content.strip()


def generate_title(diarized_text: str, chat_model: str = "gpt-4o-mini") -> str:
    """Generate a concise title for the consultation."""
    client = get_openai_client()

    resp = client.chat.completions.create(
        model=chat_model,
        messages=[
            {
                "role": "system",
                "content": "당신은 진료 기록 제목 생성기입니다. 간결하고 핵심적인 제목을 한국어로 작성합니다."
            },
            {
                "role": "user",
                "content": f"""아래 진료 대화 전사를 보고, 이 진료의 핵심을 담은 짧은 제목(10-20자)을 생성해주세요.
예시: "고관절 통증 및 괴사증 진료", "당뇨 정기 검진", "감기 증상 상담"

[전사]
{diarized_text}

제목만 출력하세요 (따옴표 없이):"""
            },
        ],
        temperature=0.3,
        max_tokens=50,
    )
    return resp.choices[0].message.content.strip().strip('"\'')


def generate_simple_summary(diarized_text: str, chat_model: str = "gpt-4o-mini") -> str:
    """Generate a 1-2 sentence simple summary."""
    client = get_openai_client()

    resp = client.chat.completions.create(
        model=chat_model,
        messages=[
            {
                "role": "system",
                "content": "당신은 진료 기록 요약 도우미입니다. 핵심만 담은 1-2문장 요약을 한국어로 작성합니다."
            },
            {
                "role": "user",
                "content": f"""아래 진료 대화를 1-2문장으로 간결하게 요약해주세요.
환자의 주요 증상과 의사의 핵심 소견/처방만 포함하세요.

[전사]
{diarized_text}

요약:"""
            },
        ],
        temperature=0.3,
        max_tokens=150,
    )
    return resp.choices[0].message.content.strip()


def parse_soap_to_consultation_summary(
    soap_text: str,
    diarized_lines: list[str],
) -> ConsultationSummary:
    """
    Parse SOAP text and diarized lines into ConsultationSummary.

    Mapping: S (Subjective) → symptomRecord, O (Objective) → testResults,
    A (Assessment) → doctorNotes, P (Plan) → prescriptionAndCare.
    """

    def _strip_question_prefix(text: str) -> str:
        """질문 접두사 Q. / Q. 제거."""
        return re.sub(r"^Q\.\s*", "", text.strip()).strip()

    # Parse SOAP sections
    sections = {"S": [], "O": [], "A": [], "P": []}
    current_section = None

    for line in soap_text.split("\n"):
        line = line.strip()
        if not line:
            continue

        # 마크다운 볼드 헤더: **S (Subjective)** , **O (Objective)** 등
        if "**" in line:
            upper = line.upper()
            if "(SUBJECTIVE)" in upper or upper.strip().startswith("**S "):
                current_section = "S"
                continue
            if "(OBJECTIVE)" in upper or upper.strip().startswith("**O "):
                current_section = "O"
                continue
            if "(ASSESSMENT)" in upper or upper.strip().startswith("**A "):
                current_section = "A"
                continue
            if "(PLAN)" in upper or upper.strip().startswith("**P "):
                current_section = "P"
                continue

        # Detect section headers (English, plain)
        upper = line.upper()
        if upper.startswith("SUBJECTIVE") or upper.startswith("S:") or upper.startswith("S ") or upper == "S" or (upper == "S."):
            current_section = "S"
            continue
        elif upper.startswith("OBJECTIVE") or upper.startswith("O:") or upper.startswith("O ") or upper == "O" or (upper == "O."):
            current_section = "O"
            continue
        elif upper.startswith("ASSESSMENT") or upper.startswith("A:") or upper.startswith("A ") or upper == "A" or (upper == "A."):
            current_section = "A"
            continue
        elif upper.startswith("PLAN") or upper.startswith("P:") or upper.startswith("P ") or upper == "P" or (upper == "P."):
            current_section = "P"
            continue

        # 한글 섹션 헤더 (주관적, 객관적, 평가, 계획)
        if line.startswith("주관적") or line.startswith("Subjective"):
            current_section = "S"
            continue
        if line.startswith("객관적") or line.startswith("Objective"):
            current_section = "O"
            continue
        if line.startswith("평가") or line.startswith("Assessment"):
            current_section = "A"
            continue
        if line.startswith("계획") or line.startswith("Plan"):
            current_section = "P"
            continue

        # Add content to current section
        if not current_section:
            continue
        # 불릿: -, •, *, ·
        if line.startswith(("-", "•", "*", "·")):
            content = _strip_question_prefix(line.lstrip("-•*· ").strip())
            if content:
                sections[current_section].append(content)
            continue
        # 번호 목록: 1. 2. 또는 1) 2)
        num_bullet = re.match(r"^\d+[.)]\s*(.+)", line)
        if num_bullet:
            content = _strip_question_prefix(num_bullet.group(1).strip())
            if content:
                sections[current_section].append(content)
            continue
        # 푸터/안내 문구 제외 (※ 참고: ...)
        if line.startswith("※"):
            continue
        # 현재 섹션인데 헤더가 아니면 한 줄 내용으로 처리 (일부 모델이 불릿 없이 출력하는 경우)
        if current_section and len(line) > 2 and not re.match(r"^[A-Za-z]\s*[.:)]", line):
            content = _strip_question_prefix(line)
            if content:
                sections[current_section].append(content)

    # SOAP → consultationSummary: S→symptomRecord, O→testResults, A→doctorNotes, P→prescriptionAndCare
    # Parse conversation content from diarized lines
    conversation_content = []
    for idx, line in enumerate(diarized_lines):
        # 1) [Speaker] 00:12.3–00:28.5: 텍스트
        # 2) [원장님] 텍스트  (신규 STT role 라벨 포맷)
        match_with_time = re.match(r"\[([^\]]+)\]\s*[\d:.\-–]+:\s*(.+)", line)
        match_no_time = re.match(r"\[([^\]]+)\]\s*(.+)", line)
        if not match_with_time and not match_no_time:
            continue

        match = match_with_time or match_no_time
        speaker = match.group(1).strip()
        content = _strip_question_prefix(match.group(2))
        if not content:
            continue

        # 기존 내부 화자코드(SPEAKER_00/01)와 신규 role 라벨(원장님/환자) 모두 지원
        if speaker == "SPEAKER_00":
            role = "원장님"
        elif speaker == "SPEAKER_01":
            role = "환자"
        else:
            role = speaker

        conversation_content.append(ConversationItem(
            role=role,
            index=idx,
            content=content,
        ))

    consultation = ConsultationSummary(
        doctorNotes=sections["A"],
        testResults=sections["O"],
        symptomRecord=sections["S"],
        prescriptionAndCare=sections["P"],
        conversationContent=conversation_content,
    )
    return consultation
