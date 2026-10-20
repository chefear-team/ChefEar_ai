"""미리 만들 음성 목록(CSV)을 내보낸다. DB 없이 500개 레시피 CSV만으로 만든다.

    python scripts/export_tts_manifest.py [출력경로]

열: file_name, kind, dish_name, step_number, text, tts_text
- file_name: 음성 파일 이름. 이 이름 그대로 data/tts_audio/standard/에 넣는다.
- text: tts_synthesize()에 넣을 문장.
- tts_text: 참고용. tts_synthesize() 안에서 발음 보정을 거친 실제 낭독 문장.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "server"))

from chefear_api.speech import FIXED_PHRASES, audio_key, confirm_text, step_speech_text  # noqa: E402
from orchestration.load_500_recipes import CSV_PATH, split_steps  # noqa: E402
from tts.pronunciation import apply_pronunciation_fixes  # noqa: E402

DEFAULT_OUT = ROOT / "data" / "tts_manifest.csv"


def build_rows() -> list[dict]:
    rows: list[dict] = []
    seen: set[str] = set()

    def add(kind: str, dish: str, step: int | str, text: str) -> None:
        key = audio_key(text)
        if key in seen:  # 같은 문장은 파일 하나로 충분하다
            return
        seen.add(key)
        rows.append(
            {
                "file_name": f"{key}.mp3",
                "kind": kind,
                "dish_name": dish,
                "step_number": step,
                "text": text,
                "tts_text": apply_pronunciation_fixes(text).strip(),
            }
        )

    for phrase in FIXED_PHRASES:
        add("fixed", "", "", phrase)

    with CSV_PATH.open(encoding="utf-8-sig", newline="") as f:
        recipes = list(csv.DictReader(f))
    for recipe in recipes:
        dish = recipe["CKG_NM"].strip()
        add("confirm", dish, "", confirm_text(dish))
        for i, step_text in enumerate(split_steps(recipe["COOKING_STEPS"]), start=1):
            add("step", dish, i, step_speech_text(step_text))
    return rows


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT
    rows = build_rows()
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    kinds = {k: sum(1 for r in rows if r["kind"] == k) for k in ("fixed", "confirm", "step")}
    print(f"{out} — {len(rows)}개 (고정 {kinds['fixed']}, 확인 {kinds['confirm']}, 단계 {kinds['step']})")


if __name__ == "__main__":
    main()
