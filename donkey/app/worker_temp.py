"""임시 STT 워커 (나중에 제거 예정)

기존 worker.py 대신 이 파일을 사용합니다.
- STT: http://api.donkey.ai.kr/transcribe (자체 오픈소스 Whisper API, URL 기반)
- 요약: SOAP 프레임워크 없이 자유 형식 요약
"""

import asyncio
import logging
import time
import traceback

from app.config import get_settings
from app.schemas.response import ConsultationSummary
from app.services.openai_client import get_openai_client
from app.services.job_logger import JobLogger
from app.services.pii_filter import filter_pii_with_screening
from app.services.rule_based_diarization import map_clova_speakers_to_roles
from app.services.slack import notify_slack
from app.services.transcription import seconds_to_time_str, transcribe_with_url
from app.store.redis import get_job_store

logger = logging.getLogger(__name__)

CLIENT_ERROR_MESSAGE = "처리 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."


def _generate_title(diarized_text: str, chat_model: str = "gpt-4o-mini") -> str:
    """대화 내용을 바탕으로 보편적인 제목을 생성합니다."""
    client = get_openai_client()

    resp = client.chat.completions.create(
        model=chat_model,
        messages=[
            {
                "role": "system",
                "content": "당신은 대화 내용을 보고 간결한 제목을 생성하는 어시스턴트입니다. 한국어로 작성합니다.",
            },
            {
                "role": "user",
                "content": f"""아래 대화 전사를 보고, 대화의 핵심을 담은 짧은 제목(10-20자)을 생성해주세요.

[전사]
{diarized_text}

제목만 출력하세요 (따옴표 없이):""",
            },
        ],
        temperature=0.3,
        max_tokens=50,
    )
    return resp.choices[0].message.content.strip().strip('"\'')


def _generate_free_summary(diarized_text: str, chat_model: str = "gpt-4o-mini") -> str:
    """temp용: 강의 내용을 구조화하여 요약합니다 (요청 프롬프트 적용)."""
    client = get_openai_client()

    system = "너는 강의 내용을 구조화하여 요약하는 AI이다."

    user = f"""[너의 역할/출력 지침]
너는 강의 내용을 구조화하여 요약하는 AI이다.

입력된 텍스트를 아래 형식으로 정리하라.

[출력 형식]

Notes (강의 요약)

1. 대주제
- (강의의 핵심 주제 1줄)

2. 소주제 구조
1) (주요 흐름1)
2) (주요 흐름2)
3) (주요 흐름3)

3. 주요내용 정리
- (분야명): (해당 내용을 한 문장으로 자연스럽게 정리, 설명형 문장으로 작성하며 '~함', '~했음' 형태로 끝낼 것)
- (분야명): (위와 동일한 형식으로 작성)
- (분야명): (위와 동일한 형식으로 작성)
- 핵심 개념: (전체를 관통하는 핵심 개념을 한 문장으로 정리)

4. 예시
- (기업/사례명): (무엇을 어떻게 AI로 활용하는지 한 문장으로 설명, '~함'으로 끝낼 것)
- (기업/사례명): (위와 동일)
- (기업/사례명): (위와 동일)

Cues (핵심)

키워드
- (핵심 키워드1)
- (핵심 키워드2)
- (핵심 키워드3)

교수 강조 포인트
- (강의에서 강조한 문장/개념)

질의응답
- Q: (질문)
  → (답변)

Actions (다음 할 것)

복습
- (복습 포인트1)
- (복습 포인트2)

과제
- (있으면 작성, 없으면 생략)

전달사항
- (있으면 작성, 없으면 생략)

[작성 규칙]

1. 모든 문장은 간결하고 자연스럽게 작성할 것 (너무 개조식 금지)
2. 주요내용 정리와 예시는 반드시 "한 줄 설명형 문장"으로 작성할 것
3. 예시, 질의응답, 과제, 전달사항은 내용이 있을 때만 작성할 것
4. 불필요한 서론, 결론, 감탄, 설명 문장 추가 금지
5. 한국어로 작성할 것

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


async def process_audio_job_temp(job_id: str, file_url: str) -> None:
    """임시 STT 파이프라인.

    파이프라인:
    1. Donkey STT API로 URL 기반 전사 (다운로드/변환 불필요)
    2. 화자 분리 (STT 응답 speaker 필드 활용)
    3. 진료 대화 유효성 검사
    4. 개인정보 필터링
    5. 자유 형식 요약 + 제목 생성
    6. Redis 결과 저장
    """
    store = await get_job_store()
    settings = get_settings()
    logger_inst = JobLogger(job_id=job_id, file_url=file_url)
    current_stage = ""

    try:
        await store.update_job(job_id, {"status": "processing"})

        # 1. STT via Donkey API
        current_stage = "transcription"
        logger_inst.start_stage()
        whisper_segments = await asyncio.to_thread(
            transcribe_with_url,
            file_url,
            settings.default_language,
        )
        logger_inst.end_stage("transcription_time_ms")

        # duration: 마지막 segment의 end 시간 사용
        duration = whisper_segments[-1].get("end", 0.0) if whisper_segments else 0.0

        if not whisper_segments:
            logger_inst.set_quality(
                is_abusing=True,
                abusing_reason="음성이 감지되지 않았습니다",
                speaker_count=0,
                segment_count=0,
            )
            await store.update_job(job_id, {
                "status": "completed",
                "isGenerated": True,
                "isAbusing": True,
                "abusingReason": "음성이 감지되지 않았습니다",
                "isScreening": False,
                "screeningReason": "해당되는 내용 없음.",
                "screening": {"names": [], "phones": []},
                "duration": duration,
                "title": "",
                "simpleSummary": "",
                "consultationSummary": ConsultationSummary().model_dump(),
            })
            logger_inst.complete("completed")
            await logger_inst.save_to_s3()
            return

        # 2. 화자 분리
        current_stage = "diarization"
        logger_inst.start_stage()
        valid_segments = [
            s for s in whisper_segments
            if (s["end"] - s["start"]) >= settings.min_segment_duration
            and (s.get("text") or "").strip()
        ]

        has_speaker_labels = valid_segments and valid_segments[0].get("speaker") is not None
        if has_speaker_labels:
            diarized_segments = map_clova_speakers_to_roles(valid_segments)
        else:
            diarized_segments = [(s["start"], s["end"], "SPEAKER_00") for s in valid_segments]
        logger_inst.end_stage("diarization_time_ms")

        unique_speakers = set(seg[2] for seg in diarized_segments)
        logger_inst.set_quality(speaker_count=len(unique_speakers))

        diarized_lines: list[str] = []
        for seg, (start, end, speaker) in zip(valid_segments, diarized_segments):
            text = (seg.get("text") or "").strip()
            if text:
                line = f"[{speaker}] {seconds_to_time_str(start)}–{seconds_to_time_str(end)}: {text}"
                diarized_lines.append(line)
        logger_inst.set_quality(segment_count=len(diarized_lines))

        if not diarized_lines:
            logger_inst.set_quality(
                is_abusing=True,
                abusing_reason="전사할 수 있는 음성이 없습니다",
            )
            await store.update_job(job_id, {
                "status": "completed",
                "isGenerated": True,
                "isAbusing": True,
                "abusingReason": "전사할 수 있는 음성이 없습니다",
                "isScreening": False,
                "screeningReason": "해당되는 내용 없음.",
                "screening": {"names": [], "phones": []},
                "duration": duration,
                "title": "",
                "simpleSummary": "",
                "consultationSummary": ConsultationSummary().model_dump(),
            })
            logger_inst.complete("completed")
            await logger_inst.save_to_s3()
            return

        diarized_text = "\n".join(diarized_lines)
        validation_abuse_reason: str | None = None

        current_stage = "validation"
        logger_inst.start_stage()
        is_valid, abuse_reason = await asyncio.to_thread(
            validate_medical_conversation,
            diarized_text,
            settings.chat_model,
        )
        logger_inst.end_stage("validation_time_ms")
        if not is_valid:
            validation_abuse_reason = abuse_reason or "진료 대화가 아님"
            logger_inst.set_quality(
                is_abusing=True,
                abusing_reason=validation_abuse_reason,
            )

        # 3. 개인정보 필터링
        current_stage = "pii_filter"
        logger_inst.start_stage()
        filtered_text, screening_data = filter_pii_with_screening(diarized_text)
        is_screening = bool(screening_data["names"] or screening_data["phones"])
        screening_reason = "해당되는 내용 발견." if is_screening else "해당되는 내용 없음."
        screening = {"names": screening_data["names"], "phones": screening_data["phones"]}
        logger_inst.end_stage("pii_filter_time_ms")

        # 5. 자유 형식 요약 + 제목 생성
        current_stage = "summarization"
        logger_inst.start_stage()
        free_summary = await asyncio.to_thread(_generate_free_summary, filtered_text, settings.chat_model)
        title = await asyncio.to_thread(_generate_title, filtered_text, settings.chat_model)
        logger_inst.end_stage("summarization_time_ms")

        is_abusing_final = validation_abuse_reason is not None
        abusing_reason_final = validation_abuse_reason or ""

        logger_inst.set_quality(
            is_abusing=is_abusing_final,
            abusing_reason=abusing_reason_final,
            speaker_count=len(unique_speakers),
            segment_count=len(diarized_lines),
        )

        # 6. Redis 결과 저장
        await store.update_job(job_id, {
            "status": "completed",
            "isGenerated": True,
            "isAbusing": is_abusing_final,
            "abusingReason": abusing_reason_final,
            "isScreening": is_screening,
            "screeningReason": screening_reason,
            "screening": screening,
            "duration": duration,
            "title": title,
            "simpleSummary": free_summary,
            "consultationSummary": None,
        })
        logger_inst.complete("completed")

    except Exception as e:
        traceback.print_exc()

        logger_inst.set_error(
            error_type=type(e).__name__,
            error_message=str(e),
            error_stage=current_stage,
        )
        logger_inst.complete("error")

        await store.update_job(job_id, {
            "status": "error",
            "error": CLIENT_ERROR_MESSAGE,
            "isGenerated": False,
            "isAbusing": False,
            "abusingReason": "",
            "isScreening": False,
            "screeningReason": "해당되는 내용 없음.",
            "screening": {"names": [], "phones": []},
        })
        notify_slack(
            get_settings().slack_webhook_url,
            f"🚨 [Donkey Temp STT] 처리 오류\njob_id: {job_id}\n원인: {type(e).__name__}: {e}\nstage: {current_stage}",
        )

    finally:
        await logger_inst.save_to_s3()
