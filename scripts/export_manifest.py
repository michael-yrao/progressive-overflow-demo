"""Emit dashboard/manifest.json: a sha256 and byte size for every dashboard JSON file.

The site fetches the manifest first and re-fetches only the files whose hash changed. It
covers every `*.json` in dashboard/ and dashboard/showcase/ except manifest.json itself and
`*.schema.json`. Hashes are of the bytes LF-normalized to match what git commits
(core.autocrlf=input), not of the CRLF a Windows write leaves on disk. A generated file that
is absent (showcase.json, big-o.json, practice.json before the adopter creates one) is simply
not listed.

    python scripts/export_manifest.py            # write dashboard/manifest.json
    python scripts/export_manifest.py --check    # exit 1 if the manifest's files map drifted
    python scripts/export_manifest.py --stdout   # print it, write nothing
    python scripts/export_manifest.py --staged   # hash the git index's bytes, not the working tree's

`--check` and the write path compare only the `files` map, never `generatedAt`, so a day
passing is not drift and an unchanged map keeps its committed bytes.

Exit 1 is drift. Exit 2 is a schema violation (the manifest, or with `--check` the on-disk
indexes and one per-problem file): nothing is written.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import _console
import contract_schema
import dashboard_indexes

REPO = Path(__file__).resolve().parent.parent
DASHBOARD = REPO / "dashboard"
MANIFEST_NAME = "manifest.json"
SCHEMA_NAME = "manifest.schema.json"
SCHEMA_SUFFIX = ".schema.json"
SCHEMA_VERSION = 1
CRLF = b"\r\n"
LF = b"\n"


def _is_covered(path: Path) -> bool:
    return path.name != MANIFEST_NAME and not path.name.endswith(SCHEMA_SUFFIX)


def _covered_paths(dashboard: Path) -> list[Path]:
    candidates = [*dashboard.glob("*.json"), *(dashboard / "showcase").glob("*.json")]
    return [path for path in candidates if path.is_file() and _is_covered(path)]


ByteSource = Callable[[Path], bytes]


def _index_blob_shas(repo: Path, dashboard: Path) -> dict[Path, str]:
    """Blob sha of every covered file in the git index (one `git ls-files -s -z`)."""
    scope = dashboard.relative_to(repo).as_posix()
    out = subprocess.run(["git", "-C", str(repo), "ls-files", "-s", "-z", "--", scope],
                         capture_output=True, check=True).stdout
    shas = {}
    for record in filter(None, out.split(b"\0")):
        meta, _, name = record.partition(b"\t")
        path = repo / name.decode("utf-8")
        if path.suffix == ".json" and _is_covered(path):
            shas[path] = meta.split()[1].decode("ascii")
    return shas


def _read_blobs(repo: Path, shas: set[str]) -> dict[str, bytes]:
    """Contents of each blob (one `git cat-file --batch`): `<sha> blob <size>\\n<bytes>\\n`."""
    if not shas:
        return {}
    ordered = sorted(shas)
    out = subprocess.run(["git", "-C", str(repo), "cat-file", "--batch"],
                         input="".join(f"{sha}\n" for sha in ordered).encode("ascii"),
                         capture_output=True, check=True).stdout
    blobs, pos = {}, 0
    for sha in ordered:
        header_end = out.index(LF, pos)
        _, kind, size = out[pos:header_end].decode("ascii").split()
        start = header_end + 1
        blobs[sha] = out[start:start + int(size)]
        pos = start + int(size) + 1
    return blobs


def staged_byte_source(repo: Path, dashboard: Path) -> ByteSource:
    """Bytes of what the commit will contain: the index blob where the file is staged, the
    working-tree bytes where it is not. Two git processes however many files there are."""
    shas = _index_blob_shas(repo, dashboard)
    blobs = _read_blobs(repo, set(shas.values()))
    return lambda path: blobs[shas[path]] if path in shas else path.read_bytes()


def build_files_map(dashboard: Path, read_bytes: ByteSource = Path.read_bytes) -> dict[str, dict]:
    """`{relative/path: {sha256, bytes}}` for every covered file, keys sorted."""
    files = {}
    for path in _covered_paths(dashboard):
        data = read_bytes(path).replace(CRLF, LF)
        files[path.relative_to(dashboard).as_posix()] = {
            "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
    return dict(sorted(files.items()))


def build_manifest(dashboard: Path, today: dt.date,
                   read_bytes: ByteSource = Path.read_bytes) -> dict:
    return {"schemaVersion": SCHEMA_VERSION, "generatedAt": today.isoformat(),
            "files": build_files_map(dashboard, read_bytes)}


def schema_errors(manifest: dict) -> list[str]:
    return contract_schema.validate(manifest, DASHBOARD / SCHEMA_NAME)


def render(manifest: dict) -> str:
    return json.dumps(manifest, ensure_ascii=False, separators=(",", ":")) + "\n"


def read_existing(path: Path) -> dict | None:
    """The parsed manifest on disk, or None when it is missing or unreadable."""
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return existing if isinstance(existing, dict) else None


def drift_reasons(files: dict[str, dict], existing: dict | None) -> list[str]:
    """Every way the on-disk manifest's files map differs from `files`."""
    if existing is None:
        return ["manifest.json: missing or unreadable — regenerate"]
    old = existing.get("files")
    if not isinstance(old, dict):
        return ["manifest.json: 'files' must be an object — regenerate"]
    added = sorted(files.keys() - old.keys())
    removed = sorted(old.keys() - files.keys())
    changed = sorted(path for path in files.keys() & old.keys() if files[path] != old[path])
    reasons = []
    if added or removed:
        reasons.append(f"file set changed — added {added}, removed {removed}")
    reasons.extend(f"{path}: hash or size differs — regenerate" for path in changed)
    return reasons


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stdout", action="store_true", help="print the JSON, do not write")
    ap.add_argument("--check", action="store_true",
                     help="never write; exit 1 if the files map drifted")
    ap.add_argument("--date", metavar="YYYY-MM-DD",
                     help="override generatedAt (default: today)")
    ap.add_argument("--staged", action="store_true",
                     help="hash the git index's bytes for staged files (what the commit holds)")
    args = ap.parse_args()

    today = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
    target = DASHBOARD / MANIFEST_NAME
    read_bytes = staged_byte_source(REPO, DASHBOARD) if args.staged else Path.read_bytes
    manifest = build_manifest(DASHBOARD, today, read_bytes)
    existing = read_existing(target)
    reasons = drift_reasons(manifest["files"], existing)

    if args.check:
        contract_schema.exit_on_errors("dashboard/manifest.json violates its schema:",
                                       schema_errors(manifest))
        dashboard_indexes.exit_on_schema_errors(
            dashboard_indexes.load_validation_sample(DASHBOARD))
        if existing is None and not manifest["files"]:
            print("ok: no dashboard JSON to cover, no manifest needed", file=sys.stderr)
            return
        if reasons:
            print("ERROR: dashboard/manifest.json is stale:", file=sys.stderr)
            for reason in reasons:
                print(f"  - {reason}", file=sys.stderr)
            sys.exit(1)
        print(f"ok: {len(manifest['files'])} files in manifest", file=sys.stderr)
        return

    if args.stdout:
        print(render(manifest), end="")
        return

    if not reasons:
        print(f"unchanged {target.relative_to(REPO)} ({len(manifest['files'])} files)")
        return
    contract_schema.exit_on_errors("dashboard/manifest.json violates its schema:",
                                   schema_errors(manifest))
    target.write_text(render(manifest), encoding="utf-8")
    print(f"wrote {target.relative_to(REPO)} ({len(manifest['files'])} files)")


if __name__ == "__main__":
    main()
