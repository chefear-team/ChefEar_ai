"""미리 만든 음성(data/tts_audio/standard/*.mp3)을 Supabase Storage(공개 버킷 tts)에 올리고 tts_assets에 기록한다.

    python scripts/upload_tts_audio.py --dry-run      # 올리지 않고 대조 결과만 본다
    python scripts/upload_tts_audio.py                 # 올린다(이미 올라간 것은 건너뜀, 이어하기 가능)
    python scripts/upload_tts_audio.py --dir 고친폴더 --allow-missing --overwrite   # 고친 파일만 교체

환경변수: SUPABASE_URL, SUPABASE_KEY(service_role) — .env 또는 셸에서. 값은 출력하지 않는다.
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

BUCKET = "tts"


def compare(manifest_names: set[str], files: dict[str, int]) -> dict:
    """목록과 폴더를 대조한다. files: 파일이름 -> 크기."""
    return {
        "missing": sorted(manifest_names - set(files)),
        "extra": sorted(set(files) - manifest_names),
        "empty": sorted(n for n, size in files.items() if n in manifest_names and size == 0),
    }


def plan(manifest_names: set[str], files: dict[str, int], already: set[str]) -> list[str]:
    """올릴 파일 목록(목록에 있고, 크기가 0이 아니고, 아직 안 올라간 것)."""
    report = compare(manifest_names, files)
    ok = manifest_names - set(report["missing"]) - set(report["empty"])
    return sorted(n for n in ok if f"standard/{n}" not in already)


def read_manifest(path: Path) -> set[str]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return {row["file_name"] for row in csv.DictReader(f)}


def existing_paths(client) -> set[str]:
    paths: set[str] = set()
    start = 0
    while True:
        rows = client.table("tts_assets").select("path").eq("scope", "standard").range(start, start + 999).execute().data or []
        paths.update(r["path"] for r in rows)
        if len(rows) < 1000:
            return paths
        start += 1000


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=str(ROOT / "data" / "tts_audio" / "standard"))
    ap.add_argument("--manifest", default=str(ROOT / "data" / "tts_manifest.csv"))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--allow-missing", action="store_true", help="목록에 없는 파일이 빠져 있어도 있는 것만 올린다")
    ap.add_argument("--overwrite", action="store_true", help="이미 올라간 이름도 다시 올린다(고친 파일 교체용)")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    names = read_manifest(Path(args.manifest))
    folder = Path(args.dir)
    files = {p.name: p.stat().st_size for p in folder.glob("*.mp3")} if folder.exists() else {}
    report = compare(names, files)
    print(f"목록 {len(names)}개 / 폴더 mp3 {len(files)}개 / 빠진 것 {len(report['missing'])} / 목록에 없는 것 {len(report['extra'])} / 크기 0 {len(report['empty'])}")
    for label in ("missing", "extra", "empty"):
        for n in report[label][:10]:
            print(f"  {label}: {n}")
        if len(report[label]) > 10:
            print(f"  {label}: ... 외 {len(report[label]) - 10}개")

    if (report["missing"] or report["empty"]) and not args.allow_missing:
        print("목록과 폴더가 맞지 않아 멈춥니다(있는 것만 올리려면 --allow-missing).")
        return 1
    if args.dry_run:
        print("--dry-run: 올리지 않았습니다.")
        return 0

    from orchestration.db import get_client

    client = get_client(allow_mock=False)
    todo = plan(names, files, set() if args.overwrite else existing_paths(client))
    print(f"올릴 파일 {len(todo)}개" + (" (덮어쓰기)" if args.overwrite else " (이미 올라간 것은 건너뜀)"))
    done = 0
    failed: list[str] = []

    def upload(name: str) -> None:
        path = f"standard/{name}"
        data = (folder / name).read_bytes()
        for attempt in range(3):
            try:
                client.storage.from_(BUCKET).upload(path, data, {"content-type": "audio/mpeg", "upsert": "true"})
                client.table("tts_assets").upsert({"path": path, "scope": "standard"}).execute()
                return
            except Exception as exc:  # noqa: BLE001 — 재시도 후에도 실패하면 목록에 남긴다
                if attempt == 2:
                    raise
                time.sleep(2 * (attempt + 1))
                print(f"  재시도 {name}: {exc!r}", flush=True)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(upload, n): n for n in todo}
        for fut in futures:
            n = futures[fut]
            try:
                fut.result()
                done += 1
            except Exception as exc:  # noqa: BLE001
                failed.append(n)
                print(f"  실패 {n}: {exc!r}", flush=True)
            if (done + len(failed)) % 100 == 0:
                print(f"  진행 {done + len(failed)}/{len(todo)}", flush=True)
    print(f"완료 {done}개, 실패 {len(failed)}개")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
