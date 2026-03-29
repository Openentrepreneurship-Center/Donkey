"""전사 유틸 (HTTP 없음)."""

from app.services.transcription import _segments_from_donkey_response, seconds_to_time_str


def test_seconds_to_time_str_under_one_hour():
    assert seconds_to_time_str(0) == "00:00.0"
    assert seconds_to_time_str(65.5) == "01:05.5"


def test_seconds_to_time_str_with_hours():
    assert seconds_to_time_str(3661.2) == "01:01:01.2"


def test_segments_from_list_format():
    body = [
        {"role": "의사", "index": 0, "content": "안녕하세요"},
        {"role": "환자", "index": 1, "content": "  "},  # skip empty
    ]
    segs = _segments_from_donkey_response(body)
    assert len(segs) == 1
    assert segs[0]["text"] == "안녕하세요"
    assert segs[0]["role"] == "의사"


def test_segments_from_dict_format():
    body = {
        "segments": [
            {"start": 0.0, "end": 1.5, "text": "hello", "speaker": "1"},
        ]
    }
    segs = _segments_from_donkey_response(body)
    assert len(segs) == 1
    assert segs[0]["start"] == 0.0
    assert segs[0]["end"] == 1.5
    assert segs[0]["speaker"] == "1"
