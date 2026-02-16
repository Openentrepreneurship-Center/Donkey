# MySQL 예시 로우 (테이블별 1건)

진료 1건 기준으로 `consultation`, `consultation_log`, `consultation_summary` 각 1행 예시.

---

## 1. consultation

| id  | job_id                               | file_url                                                                      | status    | created_at                 | updated_at                 |
| --- | ------------------------------------ | ----------------------------------------------------------------------------- | --------- | -------------------------- | -------------------------- |
| 1   | a1b2c3d4-e5f6-7890-abcd-ef1234567890 | https://bucket.s3.ap-northeast-2.amazonaws.com/recordings/2025/02/rec_001.wav | completed | 2025-02-16 09:00:00.000000 | 2025-02-16 09:02:31.000000 |

---

## 2. consultation_log

| id  | consultation_id | request_timestamp          | completed_at               | processing_time_ms | audio_duration_sec | stages    | quality   | model_usage | error |
| --- | --------------- | -------------------------- | -------------------------- | ------------------ | ------------------ | --------- | --------- | ----------- | ----- |
| 1   | 1               | 2025-02-16 09:00:00.000000 | 2025-02-16 09:02:31.000000 | 151200             | 312.5              | 아래 JSON | 아래 JSON | 아래 JSON   | NULL  |

**stages** (JSON):

```json
{
  "download_time_ms": 1200,
  "conversion_time_ms": 3400,
  "diarization_time_ms": 42000,
  "transcription_time_ms": 58000,
  "validation_time_ms": 8500,
  "pii_filter_time_ms": 2100,
  "summarization_time_ms": 28600
}
```

**quality** (JSON):

```json
{
  "is_abusing": false,
  "abusing_reason": "",
  "speaker_count": 2,
  "segment_count": 48
}
```

**model_usage** (JSON):

```json
{
  "stt_model": "gpt-4o-mini-transcribe",
  "chat_model": "gpt-4o-mini",
  "total_tokens": 12400
}
```

---

## 3. consultation_summary

| id  | consultation_id | title                               | simple_summary                                     | doctor_notes | test_results | symptom_record | prescription_and_care | conversation_content |
| --- | --------------- | ----------------------------------- | -------------------------------------------------- | ------------ | ------------ | -------------- | --------------------- | -------------------- |
| 1   | 1               | 두통·현훈으로 내원한 50대 남성 진료 | 환자 두통, 현훈 호소. 혈압 측정 및 약물 조절 권고. | 아래 JSON    | 아래 JSON    | 아래 JSON      | 아래 JSON             | 아래 JSON            |

**doctor_notes** (JSON):

```json
[
  "현훈과 두통이 동반되어 있으나 급성 뇌질환 소견 없음.",
  "혈압 조절 목표 130/80 이하 권고."
]
```

**test_results** (JSON):

```json
["혈압 142/88 mmHg", "이비인후과 검진 상 특이소견 없음."]
```

**symptom_record** (JSON):

```json
["일주일 전부터 두통, 며칠 전부터 현훈", "아침에 더 심함"]
```

**prescription_and_care** (JSON):

```json
[
  "현재 복용 중인 고혈압약 유지",
  "2주 후 재측정 후 외래 방문",
  "두통 악화 시 응급실 내원 권고"
]
```

**conversation_content** (JSON):

```json
[
  { "role": "DOCTOR", "index": 0, "content": "어디가 불편하세요?" },
  {
    "role": "PATIENT",
    "index": 1,
    "content": "일주일 전부터 머리가 아프고 어지러워요."
  },
  { "role": "DOCTOR", "index": 2, "content": "아침에 더 심해지나요?" },
  {
    "role": "PATIENT",
    "index": 3,
    "content": "네, 아침에 일어나면 특히 그래요."
  },
  {
    "role": "DOCTOR",
    "index": 4,
    "content": "혈압 한번 재볼게요. 평소 약 잘 드시고 계시죠?"
  }
]
```

---

## 에러 케이스 예시 (consultation_log만)

status가 `error`인 진료의 로그에서 **error** 컬럼만 채워진 경우:

| error (JSON)                                                                                                                   |
| ------------------------------------------------------------------------------------------------------------------------------ |
| `{"type": "ProcessingTimeout", "message": "처리 시간이 제한을 초과했습니다. (오디오 길이 기준 임계시간)", "stage": "timeout"}` |

---

이렇게 한 진료(consultation id=1)에 대해 log 1행, summary 1행이 1:1로 연결되는 느낌입니다.
