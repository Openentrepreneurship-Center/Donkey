import asyncio

import pytest

from app.schemas.response import ConsultationSummary
from app import worker


class FakeStore:
    def __init__(self) -> None:
        self.update_calls: list[dict] = []

    async def update_job(self, _job_id: str, payload: dict) -> None:
        self.update_calls.append(payload)

    async def get_job(self, _job_id: str):
        return {}


def _run_worker_with_validation_result(
    monkeypatch: pytest.MonkeyPatch,
    *,
    is_valid: bool,
    abuse_reason: str,
) -> dict:
    fake_store = FakeStore()

    class FakeSettings:
        processing_timeout_override_seconds = 0
        default_language = "ko"
        whisper_segment_model = "whisper-1"
        save_whisper_to_eval_data = False
        min_segment_duration = 0.1
        stt_backend = "donkey"
        chat_model = "gpt-4o-mini"
        slack_webhook_url = ""

    async def fake_get_job_store():
        return fake_store

    async def fake_download_audio(_url, _path) -> None:
        return None

    async def fake_save_to_s3(self) -> None:
        return None

    monkeypatch.setattr(worker, "get_settings", lambda: FakeSettings())
    monkeypatch.setattr(worker, "get_job_store", fake_get_job_store)
    monkeypatch.setattr(worker, "download_audio", fake_download_audio)
    monkeypatch.setattr(worker, "ensure_wav_16k_mono", lambda path: path)
    monkeypatch.setattr(worker, "get_audio_duration", lambda _path: 30.0)
    monkeypatch.setattr(worker, "upload_audio_to_s3", lambda _path, _job_id: None)
    monkeypatch.setattr(
        worker,
        "transcribe_with_segments",
        lambda *_args, **_kwargs: [
            {"role": "환자", "index": 0, "text": "열이 나고 기침이 있어요."},
            {"role": "원장님", "index": 1, "text": "감기 소견이며 해열제를 복용하세요."},
        ],
    )
    monkeypatch.setattr(worker, "validate_medical_conversation", lambda *_args, **_kwargs: (is_valid, abuse_reason))
    monkeypatch.setattr(worker, "filter_pii_with_screening", lambda text: (text, {"names": [], "phones": []}))
    monkeypatch.setattr(worker, "filter_pii", lambda text: text)
    monkeypatch.setattr(
        worker,
        "generate_soap_summary",
        lambda *_args, **_kwargs: "S\n- 환자는 열과 기침을 호소했습니다.\nO\n- 의사는 감기 소견을 말했습니다.\nA\n- 상기도 감염 가능성입니다.\nP\n- 해열제 복용을 권고했습니다.",
    )
    monkeypatch.setattr(worker, "generate_title", lambda *_args, **_kwargs: "감기 증상 상담")
    monkeypatch.setattr(worker, "generate_simple_summary", lambda *_args, **_kwargs: "감기 증상에 대해 상담하고 해열제 복용을 안내했습니다.")
    monkeypatch.setattr(
        worker,
        "parse_soap_to_consultation_summary",
        lambda *_args, **_kwargs: ConsultationSummary(
            doctorNotes=["상기도 감염 가능성입니다."],
            testResults=["의사는 감기 소견을 말했습니다."],
            symptomRecord=["환자는 열과 기침을 호소했습니다."],
            prescriptionAndCare=["해열제 복용을 권고했습니다."],
            conversationContent=[],
        ),
    )
    monkeypatch.setattr(worker, "notify_slack", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(worker.JobLogger, "save_to_s3", fake_save_to_s3)

    asyncio.run(worker.process_audio_job("job-test-1", "https://example.com/audio.mp3"))

    completed_updates = [u for u in fake_store.update_calls if u.get("status") == "completed"]
    assert completed_updates, "completed 상태로 저장된 결과가 있어야 합니다."
    return completed_updates[-1]


def test_abusing_case_still_generates_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    result = _run_worker_with_validation_result(
        monkeypatch,
        is_valid=False,
        abuse_reason="진료 대화가 아님 테스트",
    )

    assert result["isGenerated"] is True
    assert result["isAbusing"] is True
    assert result["abusingReason"] == "진료 대화가 아님 테스트"
    assert result["simpleSummary"] != ""
    assert result["consultationSummary"] is not None


def test_normal_case_generates_summary_with_non_abusing(monkeypatch: pytest.MonkeyPatch) -> None:
    result = _run_worker_with_validation_result(
        monkeypatch,
        is_valid=True,
        abuse_reason="",
    )

    assert result["isGenerated"] is True
    assert result["isAbusing"] is False
    assert result["abusingReason"] == ""
    assert result["simpleSummary"] != ""
    assert result["consultationSummary"] is not None
