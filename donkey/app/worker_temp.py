"""임시 STT 워커 (나중에 제거 예정)

기존 worker.py 대신 이 파일을 사용합니다.
- STT: http://api.donkey.ai.kr/transcribe (자체 오픈소스 Whisper API, URL 기반)
- 요약: SOAP 프레임워크 없이 자유 형식 요약
"""

import asyncio
import logging
import time
import traceback

import httpx
from openai import OpenAI

from app.config import get_settings
from app.services.job_logger import JobLogger
from app.services.pii_filter import filter_pii_with_screening
from app.services.rule_based_diarization import map_clova_speakers_to_roles
from app.services.slack import notify_slack
from app.services.transcription import seconds_to_time_str
from app.services.validation import validate_medical_conversation
from app.store.redis import get_job_store

logger = logging.getLogger(__name__)

CLIENT_ERROR_MESSAGE = "처리 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."
DONKEY_STT_API_URL = "http://api.donkey.ai.kr/transcribe"


def _transcribe_via_donkey_api(file_url: str, language: str = "ko") -> list[dict]:
    """http://api.donkey.ai.kr/transcribe 를 통해 STT 전사 (URL 기반).

    응답 형식:
        {
            "segments": [{"start": float, "end": float, "text": str, "speaker": str}, ...],
            "full_text": str
        }
    """
    with httpx.Client(timeout=600.0) as client:
        resp = client.post(
            DONKEY_STT_API_URL,
            json={"url": file_url, "language": language},
        )
        resp.raise_for_status()
        body = resp.json()

    segments_raw = body.get("segments") or []
    out: list[dict] = []
    for seg in segments_raw:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        item: dict = {
            "start": float(seg.get("start") or 0),
            "end": float(seg.get("end") or 0),
            "text": text,
        }
        speaker = seg.get("speaker")
        if speaker:
            item["speaker"] = str(speaker)
        out.append(item)
    return out


def _generate_title(diarized_text: str, chat_model: str = "gpt-4o-mini") -> str:
    """대화 내용을 바탕으로 보편적인 제목을 생성합니다."""
    settings = get_settings()
    client = OpenAI(api_key=settings.openai_api_key)

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
    """특정 프레임워크 없이 대화 내용을 보편적으로 요약합니다."""
    settings = get_settings()
    client = OpenAI(api_key=settings.openai_api_key)

    system = (
        "당신은 대화 내용을 요약하는 어시스턴트입니다. "
        "한국어로 핵심 내용을 명확하고 자연스럽게 요약합니다. "
        "전사에 있는 내용만 사실 그대로 요약하고, 없는 내용은 절대 추가하지 않습니다."
    )

    user = f"""아래는 대화 전사(화자/시간 포함)입니다.
대화의 핵심 내용을 자연스러운 한국어로 요약해주세요.

요구사항:
- 대화에서 논의된 주요 내용을 중심으로 요약할 것
- 특정 형식(섹션, 항목 구분 등) 없이 자연스러운 서술형으로 작성할 것
- 전사에 없는 내용은 절대 추가하지 말 것
- 모호하거나 언급 없는 내용은 생략할 것

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
            _transcribe_via_donkey_api,
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
                "consultationSummary": None,
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
                "consultationSummary": None,
            })
            logger_inst.complete("completed")
            await logger_inst.save_to_s3()
            return

        diarized_text = "\n".join(diarized_lines)

        # 3. 진료 대화 유효성 검사
        current_stage = "validation"
        logger_inst.start_stage()
        is_valid, abuse_reason = await asyncio.to_thread(
            validate_medical_conversation,
            diarized_text,
            settings.chat_model,
        )
        logger_inst.end_stage("validation_time_ms")

        if not is_valid:
            logger_inst.set_quality(
                is_abusing=True,
                abusing_reason=abuse_reason or "진료 대화가 아님",
            )
            await store.update_job(job_id, {
                "status": "completed",
                "isGenerated": True,
                "isAbusing": True,
                "abusingReason": abuse_reason or "진료 대화가 아님",
                "isScreening": False,
                "screeningReason": "해당되는 내용 없음.",
                "screening": {"names": [], "phones": []},
                "duration": duration,
                "title": "",
                "simpleSummary": "",
                "consultationSummary": None,
            })
            logger_inst.complete("completed")
            await logger_inst.save_to_s3()
            return

        # 4. 개인정보 필터링
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

        logger_inst.set_quality(
            is_abusing=False,
            abusing_reason="",
            speaker_count=len(unique_speakers),
            segment_count=len(diarized_lines),
        )

        # 6. Redis 결과 저장
        await store.update_job(job_id, {
            "status": "completed",
            "isGenerated": True,
            "isAbusing": False,
            "abusingReason": "",
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
