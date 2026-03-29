import re

from app.config import get_settings
from app.schemas.response import ConsultationSummary, ConversationItem
from app.services.openai_client import get_openai_client


def generate_soap_summary(diarized_text: str, chat_model: str = "gpt-4o-mini") -> str:
    """Generate SOAP summary from diarized transcript."""
    client = get_openai_client()

    system = (
        "You are a clinical documentation assistant. "
        "Convert the provided Korean medical conversation into a structured SOAP note. "
        "Be factual, do not invent details. If unclear, say '불명확/언급 없음'. "
        "Write in Korean. "
        "Use a consistent tone: write each bullet as a complete sentence in reported-speech or documentation style (e.g. '~했다고 했습니다', '~라고 했습니다', '~입니다'). "
        "Do not use telegraphic fragments (e.g. avoid '증상 개선 중' alone; write '환자는 증상이 개선되고 있다고 했습니다' or similar). "
        "For medical terms, use 한글(English) when appropriate (e.g. 혈당(Blood sugar), 비타민 D(Vitamin D)). "
        "Do not include any personal identifiers beyond what is present in the transcript. "
        "Strictly separate sections: O is findings-only, A is clinical interpretation/risk, P is action/instruction. "
        "Your first priority is information recall, not brevity. Missing medical information is a serious error. "
        "If medically relevant context makes the output longer, keep it."
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
- 의료적으로 관련된 대화는 길어지더라도 보존할 것. 핵심만 남기기 위해 맥락을 버리지 말 것. 의학 용어는 필요 시 한글(English)로 표기
- 질문 문장 앞에 Q. 등 접두사 붙이지 말 것

섹션 배치 엄수 규칙(반드시 준수):
- Subjective(S): 환자 주관 증상/경과/복약 언급/환자 질문만 작성
- Objective(O): 검사/영상/진찰에서 확인된 객관 소견만 작성 (수치/병변/관찰 결과)
- Assessment(A): 의사의 임상 판단, 원인 해석, 위험도 설명, 합병증/재발 가능성 설명만 작성
- Plan(P): 처방, 시술/수술 계획, 수술 후 지시, 외래/추적 계획, 퇴원 계획만 작성
- 특히 '치료/처방/수술 계획/운동 지시/호흡 지시/퇴원 계획'은 반드시 Plan(P)에만 작성
- Objective에 치료/처방/지시/계획 문장을 넣지 말 것
- Assessment에는 실행 지시(복용/시행/방문) 문장을 넣지 말 것
- 중복 작성 금지: 한 정보는 가장 적절한 섹션 하나에만 배치

압축 금지 규칙(매우 중요):
- 정보를 합쳐서 한 줄로 축약하지 말고, 임상적으로 다른 사실은 반드시 별도 불릿으로 분리할 것
- 의사 발화에 포함된 '합병증/위험/예외/조건/수치/일정/주의사항'은 각각 따로 분리해서 기록할 것
- 한 불릿에 2개 이상의 독립 사건(예: 위험 + 지시 + 일정)을 섞지 말 것
- 가능하면 전사의 정보 단위를 최대한 보존해 상세히 기록하고, 일반화된 표현(예: '회복 지시함', '추적 필요함')으로 뭉뚱그리지 말 것
- 문장 정리보다 정보 보존을 우선할 것 (약간 장문이 되더라도 의미 단위를 유지)

세부 작성 가이드:
- Subjective: 환자 질문/걱정/증상 변화는 각각 분리
- Objective: 확인된 병변, 수술 소요시간, 객관적 상태는 각각 분리
- Assessment: 의사의 위험 설명(무기폐/폐렴/혈전/재발률/추가수술 가능성 등)은 각각 분리
- Plan: 심호흡, 보행, 도뇨관 관리, 외래 추적, 퇴원 일정은 각각 분리

의료 맥락 대화 보존 규칙:
- 중간 대화라고 생략하지 말고, 의료 판단/치료 선택/동의 과정에 영향을 주는 문장은 포함할 것
- 환자의 우려, 질문, 이해 확인, 보호자와의 질의응답 중 의료적으로 의미 있는 부분은 반드시 반영할 것
- 의사의 설명 중 배경 맥락(왜 그렇게 하는지, 어떤 상황에서 달라지는지)은 축약하지 말고 핵심 문장으로 유지할 것
- 행정적 안내만 있고 의료적 의미가 없는 문장(순수 서명 위치 안내 등)만 제외 가능
- 애매하면 제외하지 말고 해당 섹션에 보수적으로 포함할 것
- 환자가 진료 후 기억해야 하거나 동의해야 하는 설명은 모두 핵심 의료 정보로 간주할 것
- 따라서 위험 고지, 예외 상황, 담당 변경 가능성, 추적 필요성, 일반적 경과 설명은 누락 없이 포함할 것

핵심 발화 주변 맥락 규칙:
- 핵심 의료 발화를 요약할 때, 직전/직후 인접 발화에서 의료적으로 연결되는 질문·확인·조건 설명을 함께 반영할 것
- 설명-질문-답변이 연속되는 경우, 맥락이 끊기지 않도록 가능한 한 함께 보존할 것
- 관련성 기준: 원인-결과, 위험-대응, 설명-질문, 지시-확인 관계

의사 설명 포괄성 규칙(범용, 필수):
- 의사 발화에서 아래 범주는 누락 없이 각각 불릿으로 반영할 것:
  1) 시술/수술 이유와 근거
  2) 합병증/부작용/위험(출혈, 감염, 폐합병증, 혈전 등)
  3) 예외/조건부 분기(예: 종양이 큰 경우, 손상 시, 악화 시)
  4) 추가 처치 가능성(수혈, 스텐트, 추가 수술, 대체 집도의 등)
  5) 재발/예후/추적 필요성(재발률, 외래 추적, 정기검사)
  6) 일반적 경과/예상 반응/회복 과정(예: 일정 기간 발열 가능, 일시적 장애 후 회복 가능)
- 위 범주가 전사에 존재하면 절대 생략하지 말고, 항목별로 분리해 기록할 것
- 한 불릿에 여러 위험요소를 묶지 말고 위험요소별로 분리할 것
- '가능성/될 수 있음/경우에는/불가피 시/보통 ~일' 같은 조건형 문장은 반드시 보존할 것
- 조건형 문장, 예외 조항, 대체 담당 가능성, 일반적인 수술 후 경과는 "부가 설명"이 아니라 독립 의료 정보로 취급할 것
- 따라서 짧더라도, 핵심 사건에 종속된 부속 문장처럼 보여도, 별도 불릿으로 남길 것

문장 분해 규칙:
- 한 불릿에는 하나의 행동/사실만 작성할 것
- 하나의 원문 문장에 둘 이상의 행동이 있으면 반드시 불릿을 분리할 것
  예) "소변줄 끼고 보통 다음 날쯤 뺍니다" →
      1) "의사는 소변줄을 삽입한다고 설명했습니다."
      2) "의사는 소변줄을 보통 다음 날 제거한다고 설명했습니다."
- "~고", "~며", "~하면서", "~후" 등으로 연결된 복합문은 가능한 한 독립 문장으로 분해할 것

출력 전 자기검증(내부적으로 수행):
- 작성 후, 의사 발화의 핵심 항목이 누락되지 않았는지 점검하고 누락된 항목을 보완한 뒤 최종 출력할 것
- 특히 '가능성/될 수 있음/경우에는/불가피 시' 같은 조건형 문장을 빠뜨리지 말 것

누락 방지 절차(내부적으로 반드시 수행, 출력에는 노출하지 말 것):
1) 전사에서 의료 정보 단위를 먼저 모두 추출한다.
2) 추출한 각 정보 단위를 S/O/A/P 중 정확히 하나에 배치한다.
3) 최종 출력 전에 정보 단위 누락 여부를 역으로 점검한다.
4) 누락된 정보 단위가 있으면 해당 섹션에 추가한 뒤 출력한다.
5) 문장을 다듬더라도 의미 단위는 삭제하지 않는다.

정보 추출 우선 규칙:
- 먼저 전사에서 의료 정보 단위를 가능한 한 잘게 쪼개 추출한 뒤 SOAP로 재배치할 것
- 하나의 긴 발화 안에 여러 의료 사실이 있으면 각 사실을 별도 항목으로 모두 보존할 것
- 특히 아래와 같은 문장은 길거나 부수적이어 보여도 절대 버리지 말 것:
  - 위험/합병증 설명
  - 조건부 가능성 설명("~할 수 있음", "~경우에는")
  - 시술/수술 중 또는 이후 발생 가능한 예외 상황
  - 추적 관찰, 재발, 외래 방문 필요성
  - 환자의 질문에 대한 구체적 답변
  - 위험 상황에서 뒤따르는 추가 처치 가능성(예: 수혈, 스텐트, 추가 수술)
- 어떤 의료 정보가 다른 더 큰 문장 안에 포함돼 있더라도, 그 정보는 독립적으로 살아남아야 한다.
- 요약이 길어져도 괜찮으니, 의료적으로 의미 있는 정보는 누락하지 말 것.
- 문장이 불완전하거나 끝이 잘린 경우라도, 그 안에 의료적으로 의미 있는 정보가 있으면 버리지 말 것
- 불완전한 절(clause) 안에 의료용어, 시술명, 검사명, 약물명, 합병증, 위험, 조건, 시점 정보가 있으면 독립적인 정보 단위로 간주할 것
- 불완전 문장은 의미를 추가로 추론하지 말고, 원문 의미를 유지하는 최소한의 문장 정리만 해서 보존할 것
- 즉, 문장 완성도보다 의료 정보 보존을 우선할 것
- 의료와 관련된 문장은 완전한 문장이 아니어도 추출 대상에서 제외하지 말 것
- ASR 오류, 말줄임, 끊긴 문장, 조사 누락이 있어도 의료 의미가 있으면 반드시 포함할 것
- 특히 위험, 합병증, 가능성, 일정, 처치, 예외 상황, 추적 계획을 담은 절은 불완전해도 무조건 보존할 것
- 시간 범위(예: 며칠, 다음 날, 모레, 일정 기간), 조건절(예: ~하면, ~경우), 예외 담당자/대체 절차 언급은 빠뜨리지 말 것
- 숫자, 기간, 횟수, 빈도, 확률, 비율, 날짜, 시점 정보가 나오면 가능한 한 원문 그대로 보존할 것
- 예: 2~3일, 50% 이상, 다음 날, 모레, 1시간 정도 같은 표현은 일반화하거나 삭제하지 말 것
- 위험 설명 안에 포함된 추가 처치 가능성도 별도 의료 정보로 취급할 것
- 예를 들어 출혈 뒤의 수혈 가능성처럼, 앞 문장에 종속된 것처럼 보여도 독립 항목으로 남길 것

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

        # 마크다운/헤더 문자 제거 후 섹션 헤더 감지
        normalized = re.sub(r"[*_`#>~\-]+", " ", line).strip()
        normalized = re.sub(r"\s+", " ", normalized)

        # 마크다운 볼드 헤더: **Subjective (S)** , **Objective (O)** 등
        if "**" in line:
            upper = normalized.upper()
            if "SUBJECTIVE" in upper or upper.startswith("S ") or upper.startswith("S:") or "(S)" in upper:
                current_section = "S"
                continue
            if "OBJECTIVE" in upper or upper.startswith("O ") or upper.startswith("O:") or "(O)" in upper:
                current_section = "O"
                continue
            if "ASSESSMENT" in upper or upper.startswith("A ") or upper.startswith("A:") or "(A)" in upper:
                current_section = "A"
                continue
            if "PLAN" in upper or upper.startswith("P ") or upper.startswith("P:") or "(P)" in upper:
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
