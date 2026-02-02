# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 프로젝트 개요

Donkey는 의료 오디오 처리 파이프라인으로, 화자 분리(diarization), 음성 전사, SOAP(Subjective/Objective/Assessment/Plan) 임상 요약을 한국어로 수행합니다.

## 명령어

```bash
# 가상환경 활성화
source donkey/diar/bin/activate

# 단일 오디오 파일 처리
python donkey/diarize_whisper.py audio_file.wav

# 녹음 번호로 여러 파일 처리 ("Recording N.m4a" 등 자동 검색)
python donkey/diarize_whisper.py --numbers 7 8 9 10

# 전체 옵션
python donkey/diarize_whisper.py audio.wav \
  --speakers 2 \
  --language ko \
  --stt_model gpt-4o-mini-transcribe \
  --chat_model gpt-4o-mini \
  --min_seg 0.6
```

## 아키텍처

`donkey/diarize_whisper.py` 단일 파일 애플리케이션으로 다음 파이프라인 구조:

1. **오디오 변환** (`ensure_wav_16k_mono`) - FFmpeg로 16kHz 모노 WAV 변환
2. **화자 분리** (`diarize_audio`) - pyannote/speaker-diarization-3.1로 화자별 구간 분리
3. **음성 전사** (`transcribe_segment_with_whisper`) - OpenAI STT로 각 구간 텍스트 변환
4. **SOAP 요약** (`soap_summarize`) - GPT-4o-mini로 임상 요약 생성

**출력 파일** (입력 파일당):
- `{filename}_diarized.txt` - 타임스탬프 화자 구간: `[Speaker_0] 00:12.3–00:28.5: 텍스트`
- `{filename}_SOAP.txt` - 임상 요약 및 면책 조항

## 환경 설정

`donkey/` 디렉토리에 `.env` 파일 필요:
```
OPENAI_API_KEY=sk-proj-...
HF_TOKEN=hf_...
```

**시스템 요구사항:**
- Python 3.10+
- FFmpeg (`brew install ffmpeg`)
- HuggingFace 토큰 (pyannote 모델 접근용)

## 주요 의존성

- `openai` - Whisper STT 및 GPT 채팅용 API 클라이언트
- `pyannote.audio` - 화자 분리 (v3.1)
- `pydub` - 오디오 세그먼트 조작
- `python-dotenv` - 환경 변수 관리
