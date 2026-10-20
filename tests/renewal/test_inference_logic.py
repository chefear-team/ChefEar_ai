"""추론 서버의 순수 로직: STT 후처리, mp3 변환, 등록 음성 생성."""
import io
import sys
import types
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from inference.audio_encode import encode_mp3  # noqa: E402
from inference.recipe_audio import generate_for_recipe, recipe_texts  # noqa: E402
from inference.stt_runtime import clean_segments, transcribe_wav  # noqa: E402

from chefear_api import speech as sp  # noqa: E402


def seg(text, no_speech=0.01):
    return types.SimpleNamespace(text=text, no_speech_prob=no_speech)


class FakeModel:
    def __init__(self, segments):
        self.segments = segments
        self.calls = []

    def transcribe(self, audio, **kw):
        self.calls.append(kw)
        return iter(self.segments), types.SimpleNamespace()


def test_clean_segments_filters_noise_and_hallucination():
    assert clean_segments([seg(" 된장찌개 어떻게 만들어 ")]) == "된장찌개 어떻게 만들어"
    assert clean_segments([seg("된장찌개", no_speech=0.9)]) == ""
    assert clean_segments([seg("시청해주셔서 감사합니다")]) == ""
    assert clean_segments([seg("깨진�글자")]) == ""
    assert clean_segments([]) == ""


def test_transcribe_wav_uses_expected_decode_options():
    model = FakeModel([seg("다음")])
    text = transcribe_wav(model, b"x" * 100, decode=lambda wav: np.zeros(16000, dtype=np.float32))
    assert text == "다음"
    assert model.calls == [{"language": "ko", "vad_filter": False, "beam_size": 1}]
    assert transcribe_wav(model, b"", decode=lambda w: None) == ""  # 빈 오디오는 모델을 부르지 않는다
    assert len(model.calls) == 1


def test_default_decode_gives_16k_mono_float32_for_wav_and_mp3():
    from inference.stt_runtime import _default_decode

    def tone(sr, seconds=1.0):
        t = np.linspace(0, seconds, int(sr * seconds), endpoint=False)
        return (0.3 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)

    for sr in (16000, 24000, 44100):
        buf = io.BytesIO()
        sf.write(buf, tone(sr), sr, format="WAV", subtype="PCM_16")
        out = _default_decode(buf.getvalue())
        assert out.dtype == np.float32 and out.ndim == 1 and abs(len(out) - 16000) < 20, sr
        assert 0.15 < float(np.abs(out).max()) < 0.4  # 소리가 사라지거나 깨지지 않았다
    out = _default_decode(encode_mp3(tone(24000), 24000))
    assert out.dtype == np.float32 and 0.9 * 16000 < len(out) < 1.2 * 16000


def test_encode_mp3_is_small_decodable_mono():
    sr = 24000
    t = np.linspace(0, 1, sr, endpoint=False)
    data = encode_mp3((0.3 * np.sin(2 * np.pi * 440 * t)).astype(np.float32), sr)
    assert 1000 < len(data) < 60000
    out, out_sr = sf.read(io.BytesIO(data))
    assert out_sr == sr and out.ndim == 1 and 0.9 < len(out) / sr < 1.2
    stereo = np.stack([np.zeros(sr), np.zeros(sr)], axis=1).astype(np.float32)
    assert sf.read(io.BytesIO(encode_mp3(stereo, sr)))[0].ndim == 1


# ── 등록 음성 생성 ──────────────────────────────────────────────────
class _Q:
    def __init__(self, table, op, payload=None):
        self.t, self.op, self.payload, self.f, self.order_col = table, op, payload, [], None

    def select(self, *a, **k):
        return self

    def eq(self, c, v):
        self.f.append((c, v))
        return self

    def order(self, c):
        self.order_col = c
        return self

    def execute(self):
        match = lambda r: all(r.get(c) == v for c, v in self.f)  # noqa: E731
        if self.op == "upsert":
            pk = self.t.pk
            self.t.rows = [r for r in self.t.rows if r[pk] != self.payload[pk]] + [dict(self.payload)]
            return types.SimpleNamespace(data=[self.payload])
        if self.op == "delete":
            self.t.rows = [r for r in self.t.rows if not match(r)]
            return types.SimpleNamespace(data=[])
        rows = [dict(r) for r in self.t.rows if match(r)]
        if self.order_col:
            rows.sort(key=lambda r: r[self.order_col])
        return types.SimpleNamespace(data=rows)


class _T:
    def __init__(self, pk, rows=None):
        self.pk, self.rows = pk, rows or []

    def select(self, *a, **k):
        return _Q(self, "select")

    def upsert(self, payload):
        return _Q(self, "upsert", payload)

    def delete(self):
        return _Q(self, "delete")


class _Bucket:
    def __init__(self):
        self.files = {}

    def upload(self, path, data, opts):
        self.files[path] = data

    def remove(self, paths):
        for p in paths:
            self.files.pop(p, None)


class FakeDb:
    def __init__(self, recipe, steps):
        self.tables = {
            "recipes": _T("id", [recipe]),
            "recipe_steps": _T("step_number", steps),
            "tts_assets": _T("path"),
            "tts_jobs": _T("recipe_id"),
        }
        self.bucket = _Bucket()
        self.storage = types.SimpleNamespace(from_=lambda name: self.bucket)

    def table(self, name):
        return self.tables[name]


def _db(owner="u1"):
    recipe = {"id": "r1", "dish_name": "김밥", "owner_id": owner}
    steps = [{"recipe_id": "r1", "step_number": i, "step_text": f"{i}. 말아요 {i}."} for i in (1, 2)]
    return FakeDb(recipe, steps)


def test_generate_makes_private_files_and_marks_done():
    db = _db()
    made = []

    def synth(text):
        made.append(text)
        return b"mp3:" + text.encode()

    res = generate_for_recipe(db, "r1", "u1", synth)
    assert res == {"status": "done", "made": 3, "reused": 0, "removed": 0}
    assert made[0] == sp.confirm_text("김밥")
    assert len(db.bucket.files) == 3 and all(p.startswith("users/u1/") for p in db.bucket.files)
    assert db.tables["tts_jobs"].rows[0]["status"] == "done"
    assert len(db.tables["tts_assets"].rows) == 3

    # 다시 돌려도 새로 만들지 않는다
    made.clear()
    assert generate_for_recipe(db, "r1", "u1", synth)["made"] == 0 and made == []


def test_generate_replaces_stale_audio_after_edit():
    db = _db()
    generate_for_recipe(db, "r1", "u1", lambda t: b"x")
    db.tables["recipe_steps"].rows[1]["step_text"] = "2. 다르게 말아요."
    res = generate_for_recipe(db, "r1", "u1", lambda t: b"y")
    assert res["made"] == 1 and res["removed"] == 1 and len(db.bucket.files) == 3


def test_generate_refuses_other_owner_and_records_failure():
    db = _db(owner="u1")
    assert generate_for_recipe(db, "r1", "intruder", lambda t: b"x")["status"] == "skipped"
    assert db.bucket.files == {}

    def boom(text):
        raise RuntimeError("gpu down")

    with pytest.raises(RuntimeError):
        generate_for_recipe(db, "r1", "u1", boom)
    assert db.tables["tts_jobs"].rows[0]["status"] == "failed"


def test_recipe_texts_dedupes():
    assert recipe_texts("김밥", ["1. 말아요.", "2. 말아요."]) == [sp.confirm_text("김밥"), sp.step_speech_text("1. 말아요."),
                                                                    sp.step_speech_text("2. 말아요.")]
