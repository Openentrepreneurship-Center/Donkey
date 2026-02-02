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
        "Write in Korean. Use concise bullet points. "
        "Do not include any personal identifiers beyond what is present in the transcript."
    )

    user = f"""아래는 진료 대화 전사(화자/시간 포함)입니다.
SOAP(Subjective, Objective, Assessment, Plan) 형식으로 요약해줘.

요구사항:
- 한국어
- S/O/A/P 각 섹션 제목 포함
- 각 섹션은 불릿 포인트로 간결하게
- 전사에 없는 내용은 절대 추가하지 말 것(추측 금지)
- 모호하면 "불명확" 또는 "언급 없음"으로 표시
- 진료 핵심(증상/병력/검사/설명/진단 추정/계획)을 우선

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
    Parse SOAP text and diarized lines into ConsultationSummary structure.

    SOAP sections:
    - Subjective -> symptomRecord
    - Objective -> doctorNotes + testResults
    - Assessment -> (included in doctorNotes)
    - Plan -> prescriptionAndCare
    """
    # Parse SOAP sections
    sections = {"S": [], "O": [], "A": [], "P": []}
    current_section = None

    for line in soap_text.split("\n"):
        line = line.strip()
        if not line:
            continue

        # Detect section headers
        upper = line.upper()
        if upper.startswith("SUBJECTIVE") or upper.startswith("S:") or upper.startswith("S ") or upper == "S":
            current_section = "S"
            continue
        elif upper.startswith("OBJECTIVE") or upper.startswith("O:") or upper.startswith("O ") or upper == "O":
            current_section = "O"
            continue
        elif upper.startswith("ASSESSMENT") or upper.startswith("A:") or upper.startswith("A ") or upper == "A":
            current_section = "A"
            continue
        elif upper.startswith("PLAN") or upper.startswith("P:") or upper.startswith("P ") or upper == "P":
            current_section = "P"
            continue

        # Add content to current section
        if current_section and line.startswith(("-", "•", "*", "·")):
            content = line.lstrip("-•*· ").strip()
            if content:
                sections[current_section].append(content)

    # Separate testResults from Objective (lines mentioning 검사, 결과, etc.)
    test_keywords = ["검사", "결과", "수치", "혈액", "X-ray", "MRI", "CT", "초음파"]
    doctor_notes = []
    test_results = []

    for item in sections["O"]:
        if any(kw in item for kw in test_keywords):
            test_results.append(item)
        else:
            doctor_notes.append(item)

    # Add Assessment to doctor notes
    doctor_notes.extend(sections["A"])

    # Parse conversation content from diarized lines
    conversation_content = []
    for idx, line in enumerate(diarized_lines):
        # Parse format: [Speaker_0] 00:12.3–00:28.5: 텍스트
        match = re.match(r"\[([^\]]+)\]\s*[\d:.\-–]+:\s*(.+)", line)
        if match:
            speaker = match.group(1)
            content = match.group(2).strip()
            # Determine role based on speaker pattern
            role = "doctor" if "0" in speaker else "patient"
            conversation_content.append(ConversationItem(
                role=role,
                index=idx,
                content=content,
            ))

    return ConsultationSummary(
        doctorNotes=doctor_notes,
        testResults=test_results,
        symptomRecord=sections["S"],
        prescriptionAndCare=sections["P"],
        conversationContent=conversation_content,
    )
