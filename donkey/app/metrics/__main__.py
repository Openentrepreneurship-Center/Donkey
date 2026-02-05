"""
한국어 STT 지표 CLI.

사용 예 (donkey 폴더에서):
  uv run python -m app.metrics -r reference.txt -H hypothesis.txt
  uv run python -m app.metrics -r ref.txt -H hyp.txt --encoding utf-8

설치 후:
  donkey-metrics -r ref.txt -H hyp.txt
"""

import argparse
import sys
from pathlib import Path

# donkey 폴더에서 eval_data/xxx 또는 xxx 만 넘겨도 app/metrics/eval_data/ 에서 찾기 위함
_EVAL_DATA_DIR = Path(__file__).resolve().parent / "eval_data"


def _resolve_path(path: Path) -> Path:
    if path.exists():
        return path
    fallback = _EVAL_DATA_DIR / path.name
    if fallback.exists():
        return fallback
    return path  # 없으면 원래 경로 반환 (아래에서 exists()로 에러 처리)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="한국어 STT 지표 계산 (Morpheme WER, CER)",
        epilog="예: uv run python -m app.metrics -r ref.txt -H hyp.txt  (donkey 폴더에서)",
    )
    parser.add_argument(
        "-r",
        "--ref",
        "--reference",
        dest="reference",
        required=True,
        type=Path,
        metavar="FILE",
        help="정답 전사 txt 파일 경로",
    )
    parser.add_argument(
        "-H",
        "--hyp",
        "--hypothesis",
        dest="hypothesis",
        required=True,
        type=Path,
        metavar="FILE",
        help="인식 결과 txt 파일 경로",
    )
    parser.add_argument(
        "--encoding",
        default="utf-8",
        help="파일 인코딩 (기본: utf-8)",
    )
    parser.add_argument(
        "--no-normalize",
        action="store_true",
        help="전처리(특수문자 제거·공백 정규화) 비활성화",
    )
    parser.add_argument(
        "--morpheme-wer",
        action="store_true",
        help="Morpheme WER만 출력",
    )
    parser.add_argument(
        "--cer",
        action="store_true",
        help="CER만 출력",
    )
    args = parser.parse_args()

    ref_path = _resolve_path(args.reference)
    hyp_path = _resolve_path(args.hypothesis)
    if not ref_path.exists():
        print(f"오류: reference 파일을 찾을 수 없습니다: {args.reference}", file=sys.stderr)
        return 1
    if not hyp_path.exists():
        print(f"오류: hypothesis 파일을 찾을 수 없습니다: {args.hypothesis}", file=sys.stderr)
        return 1

    # 아무 것도 지정 안 하면 Morpheme WER, CER 출력
    show_all = not (args.morpheme_wer or args.cer)
    normalize = not args.no_normalize

    from .transcription_metrics import cer_from_files, morpheme_wer_from_files

    kw = {
        "encoding": args.encoding,
        "normalize": normalize,
    }

    out_lines = []
    if show_all or args.morpheme_wer:
        try:
            m = morpheme_wer_from_files(ref_path, hyp_path, **kw)
            out_lines.append(f"Morpheme WER\t{m:.4f}\t({m*100:.2f}%)")
        except ImportError as e:
            out_lines.append(f"Morpheme WER\t(kiwipiepy 미설치: {e})")
    if show_all or args.cer:
        c = cer_from_files(ref_path, hyp_path, **kw)
        out_lines.append(f"CER\t{c:.4f}\t({c*100:.2f}%)")

    for line in out_lines:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
