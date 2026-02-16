# Donkey

의료 오디오 전사·화자 분리·SOAP 요약 API. 화자 분리는 Whisper 구간 + 오디오 특징 클러스터링(규칙 기반)으로 동작합니다.

---

## 요구사항

- **Python** 3.10+
- **Redis** (작업 상태 저장용)
- **uv** (패키지 관리, 권장) 또는 pip

---

## 설치

```bash
# 저장소 클론 후 donkey 앱 디렉터리로 이동
cd donkey

# uv로 의존성 설치
uv sync
```

---

## 환경 변수

`donkey/.env` 파일을 만들고 아래 값을 설정합니다.

| 변수             | 필수   | 설명                                                                                                    |
| ---------------- | ------ | ------------------------------------------------------------------------------------------------------- |
| `OPENAI_API_KEY` | ✅     | OpenAI API 키 (전사·요약·화자 라벨링에 사용)                                                            |
| `API_KEY`        | (선택) | API 인증용 키. 없으면 `default-api-key` 사용. 요청 시 `X-Api-Key` 헤더에 넣습니다.                      |
| `REDIS_URL`      | (선택) | Redis URL. 기본값: `redis://localhost:6379/0`                                                           |
| `DATABASE_URL`   | (선택) | MySQL URL (진료/로그/요약 저장). 비우면 DB 저장 안 함. 예: `mysql+asyncmy://user:pass@host:3306/dbname` |

추가 옵션은 `donkey/.env.example` 참고.

---

## 실행 방법

### 1. Redis 실행

로컬에서 Redis가 설치되어 있다면:

```bash
redis-server
```

### 2. API 서버 실행

```bash
cd donkey
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

서버가 뜨면 **http://localhost:8000** 에서 접근할 수 있습니다.

- **헬스 체크**: `GET http://localhost:8000/health`
- **API 문서**: `http://localhost:8000/docs`

---

## API 사용법

모든 `/ai` 요청에는 **`X-Api-Key`** 헤더가 필요합니다. (`.env`의 `API_KEY` 또는 기본값 `default-api-key`)

### 작업 생성 (전사 + SOAP 요약)

오디오 파일 **URL**을 보내면, 백그라운드에서 전사·화자 분리·요약이 실행됩니다.

```bash
curl -X POST "http://localhost:8000/ai" \
  -H "X-Api-Key: default-api-key" \
  -H "Content-Type: application/json" \
  -d '{"file": "https://example.com/audio.mp3"}'
```

**응답 예시**

```json
{
  "status": "ok",
  "statusCode": 200,
  "body": { "id": "uuid-작업-ID" }
}
```

### 결과 조회

작업 ID로 상태와 결과를 조회합니다.

```bash
curl "http://localhost:8000/ai/{작업_ID}" \
  -H "X-Api-Key: default-api-key"
```

- **202**: 처리 중 (pending / processing)
- **200**: 완료 (전사·요약·SOAP 등 포함)
- **500**: 오류
- **404**: 해당 작업 없음

---

## Docker로 실행

```bash
cd donkey
docker build -t donkey .
docker run -p 8000:8000 --env-file .env donkey
```

Redis는 별도로 띄우거나, `docker run` 시 `--env REDIS_URL=redis://host.docker.internal:6379/0` 처럼 호스트 Redis를 지정하면 됩니다.

---

## 메트릭(전사 품질 평가)

Whisper 전사 품질 지표(WER 등)를 계산하려면:

```bash
cd donkey
uv run donkey-metrics --help
```

평가 데이터 형식은 `donkey/app/metrics/eval_data/README.md` 를 참고하면 됩니다.
