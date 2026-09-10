# -*- coding: utf-8 -*-
"""배포용 STT 모델(faster-whisper, CTranslate2 int8)을 Fixed100 검증셋으로 재평가한다.

저장소에 커밋된 검증셋(`data/evaluation_scripts/stt/ChefEar_test_fixed_100.csv` + mp3 100개)을
그대로 읽어 WER/CER을 계산하므로, `.env`(HF_TOKEN, HF_STT_CT2_REPO)만 있으면 누구나 같은
수치를 다시 얻을 수 있다.

실행:
    python src/stt/evaluate_fixed100.py            # 100문장 전체
    python src/stt/evaluate_fixed100.py --limit 5  # 빠른 확인
결과:
    results/stt/fixed100_ct2_int8.csv   문장별 정답/인식결과/WER/CER
    results/stt/fixed100_summary.md     전체 평균 요약
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

CSV_PATH = PROJECT_ROOT / "data" / "evaluation_scripts" / "stt" / "ChefEar_test_fixed_100.csv"
AUDIO_DIR = PROJECT_ROOT / "data" / "evaluation_scripts" / "stt" / "test_audio_100"
OUT_DIR = PROJECT_ROOT / "results" / "stt"

_PUNCT_RE = re.compile(r"[.,!?~…·\"'()\[\]{}:;]")
_UNIT_MAP = {"kg": "킬로그램", "ml": "밀리리터", "g": "그램", "l": "리터", "L": "리터"}


def normalize(text: str) -> str:
    """정답/인식결과 공통 정규화 — 문장부호 제거, 단위 기호 한글화, 공백 정리.

    정답 CSV는 "150 g"처럼 기호 단위를 쓰고 배포 STT는 "150그램"으로 후처리하므로,
    같은 뜻을 다른 표기로 적은 것이 오류로 잡히지 않게 양쪽을 같은 표기로 맞춘다.
    """
    text = _PUNCT_RE.sub(" ", text)
    for unit, word in _UNIT_MAP.items():
        text = re.sub(rf"(\d)\s*{unit}\b", rf"\1{word}", text)
    text = re.sub(r"(\d)\s+(그램|킬로그램|밀리리터|리터|컵|큰술|작은술|개|분|초|스푼)", r"\1\2", text)
    return " ".join(text.split())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="앞에서 N개만 평가(0=전체)")
    args = parser.parse_args()

    import jiwer
    from orchestration.db import load_env
    from stt.infer import stt_transcribe

    load_env()

    with CSV_PATH.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if args.limit:
        rows = rows[: args.limit]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_rows = []
    t0 = time.perf_counter()
    for i, row in enumerate(rows, 1):
        audio = AUDIO_DIR / f"{row['test_id']}.mp3"
        started = time.perf_counter()
        hyp = stt_transcribe(str(audio))
        elapsed = time.perf_counter() - started
        ref_n, hyp_n = normalize(row["text"]), normalize(hyp)
        wer = jiwer.wer(ref_n, hyp_n) if ref_n else 0.0
        cer = jiwer.cer(ref_n.replace(" ", ""), hyp_n.replace(" ", "")) if ref_n else 0.0
        out_rows.append(
            {
                "test_id": row["test_id"],
                "recipe_name": row["recipe_name"],
                "reference": row["text"],
                "hypothesis": hyp,
                "wer": f"{wer:.4f}",
                "cer": f"{cer:.4f}",
                "seconds": f"{elapsed:.2f}",
            }
        )
        print(f"[{i:3d}/{len(rows)}] WER={wer:.3f} CER={cer:.3f} | {row['text']} -> {hyp}")

    refs = [normalize(r["reference"]) for r in out_rows]
    hyps = [normalize(r["hypothesis"]) for r in out_rows]
    corpus_wer = jiwer.wer(refs, hyps)
    corpus_cer = jiwer.cer([r.replace(" ", "") for r in refs], [h.replace(" ", "") for h in hyps])
    exact = sum(1 for r, h in zip(refs, hyps) if r == h)
    avg_sec = sum(float(r["seconds"]) for r in out_rows) / len(out_rows)

    csv_path = OUT_DIR / "fixed100_ct2_int8.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
        writer.writeheader()
        writer.writerows(out_rows)

    summary = "\n".join(
        [
            "# Fixed100 재평가 — 배포용 STT(faster-whisper, CTranslate2 int8)",
            "",
            f"- 평가 문장 수: {len(out_rows)}",
            f"- Corpus WER: {corpus_wer * 100:.2f}%",
            f"- Corpus CER: {corpus_cer * 100:.2f}%",
            f"- 완전 일치 문장: {exact}/{len(out_rows)}",
            f"- 문장당 평균 추론 시간: {avg_sec:.2f}초 (모델 로딩 제외, 첫 문장은 워밍업 포함)",
            f"- 총 소요: {time.perf_counter() - t0:.1f}초",
            "",
            f"실행 스크립트: `src/stt/evaluate_fixed100.py`, 문장별 결과: `{csv_path.relative_to(PROJECT_ROOT).as_posix()}`",
            "",
        ]
    )
    (OUT_DIR / "fixed100_summary.md").write_text(summary, encoding="utf-8")
    print(summary)


if __name__ == "__main__":
    main()
