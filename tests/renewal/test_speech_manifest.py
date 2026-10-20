"""미리 만든 음성 목록(data/tts_manifest.csv)이 서비스가 실제로 요청할 문장을 전부 덮는지."""
import csv
from pathlib import Path

from chefear_api import speech as sp
from orchestration.load_500_recipes import CSV_PATH, split_steps

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "data" / "tts_manifest.csv"


def _manifest_names() -> set[str]:
    with MANIFEST.open(encoding="utf-8-sig", newline="") as f:
        return {row["file_name"] for row in csv.DictReader(f)}


def test_manifest_covers_every_standard_sentence():
    names = _manifest_names()
    with CSV_PATH.open(encoding="utf-8-sig", newline="") as f:
        recipes = list(csv.DictReader(f))
    assert len(recipes) == 500
    missing = []
    for r in recipes:
        dish = r["CKG_NM"].strip()
        wanted = [sp.confirm_text(dish)] + [sp.step_speech_text(s) for s in split_steps(r["COOKING_STEPS"])]
        missing += [t for t in wanted if f"{sp.audio_key(t)}.mp3" not in names]
    assert missing == []
    assert all(f"{sp.audio_key(p)}.mp3" in names for p in sp.FIXED_PHRASES)


def test_manifest_has_expected_count_and_unique_names():
    with MANIFEST.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 2724
    assert len({r["file_name"] for r in rows}) == 2724


def test_audio_key_changes_with_voice_version(monkeypatch):
    before = sp.audio_key("안녕")
    monkeypatch.setattr(sp, "VOICE_VERSION", "other")
    assert sp.audio_key("안녕") != before
