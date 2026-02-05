# 평가 데이터 (Reference / Hypothesis)

한국어 STT 지표(**Morpheme WER**, **CER**) 계산용 txt 파일을 이 폴더에 넣어두세요.

- **Morpheme WER**: 형태소 단위 오류율
- **CER**: 글자 단위 오류율

## 파일

| 파일명      | 설명                                                                                                        |
| ----------- | ----------------------------------------------------------------------------------------------------------- |
| `*_ref.txt` | 정답 전사(ground truth)                                                                                     |
| `*_hyp.txt` | 인식 결과(STT 출력). 파이프라인에서 `SAVE_WHISPER_TO_EVAL_DATA=true` 이면 `{job_id}_hyp.txt` 로 자동 저장됨 |

## 전처리 (기본 적용)

비교 전에 자동으로 적용됩니다.

- **특수문자 제거**: 글자·숫자·공백만 남김 (구두점, 기호 제거)
- **추임새 제거**: `음`, `예`, `네`, `아`, `어`, `응` 등 단어 단위 제거 (`네트워크` 등은 유지)
- 비활성화: CLI에서 `--no-normalize` 사용

## CLI (donkey 폴더에서)

```bash
# ref / hyp 파일명만 넣어도 이 폴더에서 찾음
uv run python -m app.metrics -r recording14_ref.txt -H recording14_hyp.txt

# Morpheme WER만
uv run python -m app.metrics -r recording14_ref.txt -H recording14_hyp.txt --morpheme-wer

# CER만
uv run python -m app.metrics -r recording14_ref.txt -H recording14_hyp.txt --cer
```

설치 후: `donkey-metrics -r recording14_ref.txt -H recording14_hyp.txt`

## Python

```python
from pathlib import Path
from app.metrics import morpheme_wer_from_files, cer_from_files

eval_dir = Path(__file__).resolve().parent  # eval_data 폴더 경로

mwer = morpheme_wer_from_files(eval_dir / "recording14_ref.txt", eval_dir / "recording14_hyp.txt")
cer = cer_from_files(eval_dir / "recording14_ref.txt", eval_dir / "recording14_hyp.txt")
```
