"""SOAP summarization module."""

from openai import OpenAI


SOAP_SYSTEM_PROMPT = (
    "You are a clinical documentation assistant. "
    "Summarize the provided Korean medical conversation into SOAP format. "
    "Be factual, do not invent details. If unclear, say '불명확/언급 없음'. "
    "Write in Korean. Use concise bullet points. "
    "Do not include any personal identifiers beyond what is present in the transcript."
)

SOAP_USER_TEMPLATE = """아래는 진료 대화 전사(화자/시간 포함)입니다.
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

SOAP_DISCLAIMER = "※ 참고: 이 문서는 전사 텍스트 기반 자동 요약이며, 의료적 판단/진단을 대체하지 않습니다."


def soap_summarize(
    diarized_text: str,
    client: OpenAI,
    chat_model: str = "gpt-4o-mini",
) -> str:
    """
    Summarize diarized transcript into SOAP format.

    Args:
        diarized_text: Transcribed text with speaker labels and timestamps
        client: OpenAI client instance
        chat_model: Chat model name for summarization

    Returns:
        SOAP-formatted summary in Korean
    """
    user_message = SOAP_USER_TEMPLATE.format(diarized_text=diarized_text)

    resp = client.chat.completions.create(
        model=chat_model,
        messages=[
            {"role": "system", "content": SOAP_SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        temperature=0.2,
    )
    return resp.choices[0].message.content.strip()


def soap_summarize_with_disclaimer(
    diarized_text: str,
    client: OpenAI,
    chat_model: str = "gpt-4o-mini",
) -> str:
    """
    Summarize diarized transcript into SOAP format with disclaimer.

    Args:
        diarized_text: Transcribed text with speaker labels and timestamps
        client: OpenAI client instance
        chat_model: Chat model name for summarization

    Returns:
        SOAP-formatted summary with disclaimer appended
    """
    soap_text = soap_summarize(diarized_text, client, chat_model)
    return f"{soap_text}\n\n---\n{SOAP_DISCLAIMER}\n"
