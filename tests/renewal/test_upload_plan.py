import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from upload_tts_audio import compare, plan  # noqa: E402


def test_compare_reports_missing_extra_and_empty():
    names = {"a.mp3", "b.mp3", "c.mp3"}
    files = {"a.mp3": 10, "b.mp3": 0, "z.mp3": 5}
    assert compare(names, files) == {"missing": ["c.mp3"], "extra": ["z.mp3"], "empty": ["b.mp3"]}


def test_plan_skips_already_uploaded_empty_and_extra():
    names = {"a.mp3", "b.mp3", "c.mp3", "d.mp3"}
    files = {"a.mp3": 10, "b.mp3": 0, "c.mp3": 7, "z.mp3": 5}
    assert plan(names, files, {"standard/a.mp3"}) == ["c.mp3"]
