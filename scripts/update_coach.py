"""Pull engine updates from canonical cse-coach into a derived practice repo.

    python scripts/update_coach.py --check     # is there anything new? (cheap, no clone)
    python scripts/update_coach.py --dry-run   # what would change?
    python scripts/update_coach.py             # apply it

A repo made with "Use this template" shares no history with cse-coach, so git
cannot merge them. This does the merge git can't - see `coach_sync.py` for the
three-way rule. The short version:

    you never touched it  -> updated for you
    you edited it         -> left alone; reported only if upstream also moved it
    your data             -> not even looked at

Maintainer note: run `--emit-manifest` in the canonical repo before tagging a
release, so the shipped manifest describes what that release actually contains.
"""

from __future__ import annotations

import argparse
import difflib
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from coach_sync import (  # noqa: E402
    CONFLICT_DIR,
    ENGINE_PATHS,
    MANIFEST_PATH,
    VERSION_PATH,
    Decision,
    FileVerdict,
    hash_file,
    is_newer,
    iter_tracked,
    parse_version,
    plan,
)

# Git runs hooks with a cp1252 console on Windows; the first non-ASCII character printed
# would otherwise kill the script mid-run while the commit still succeeds. See _console.
import _console

_console.force_utf8()

DEFAULT_UPSTREAM = "https://github.com/michael-yrao/cse-coach.git"
DEFAULT_REF = "main"
UNKNOWN_VERSION = "unknown"

REPO_ROOT = Path(__file__).resolve().parent.parent

#: How each decision is announced. Silence is deliberate for the boring ones -
#: a report that lists everything is a report nobody reads.
LABELS = {
    Decision.UPDATE: "updated",
    Decision.NEW: "NEW",
    Decision.CONFLICT: "NEEDS REVIEW",
    Decision.REMOVED_UPSTREAM: "dropped upstream",
    Decision.ADVISORY: "changed upstream",
}


class SyncError(RuntimeError):
    """Anything that should stop the sync with a readable message."""


# --- git helpers -------------------------------------------------------------


def _git(*args: str, cwd: Path | None = None) -> str:
    try:
        out = subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except FileNotFoundError as exc:  # pragma: no cover - environment dependent
        raise SyncError("git is not installed or not on PATH.") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise SyncError(f"git {' '.join(args)} failed:\n  {detail}") from exc
    return out.stdout


def remote_head(upstream: str, ref: str) -> str:
    """The upstream tip SHA, without cloning anything."""
    out = _git("ls-remote", upstream, ref).strip()
    if not out:
        raise SyncError(f"upstream has no ref {ref!r}: {upstream}")
    return out.split()[0]


def remote_tags(upstream: str) -> list[str]:
    """Upstream's tag names, without cloning. `^{}` deref entries are collapsed."""
    out = _git("ls-remote", "--tags", upstream)
    names = set()
    for line in out.splitlines():
        parts = line.split("refs/tags/")
        if len(parts) == 2:
            names.add(parts[1].strip().removesuffix("^{}"))
    return sorted(names)


def clone_upstream(upstream: str, ref: str, dest: Path) -> str:
    """Shallow-clone upstream into `dest`; return the cloned SHA."""
    _git("clone", "--depth", "1", "--branch", ref, "--quiet", upstream, str(dest))
    return _git("rev-parse", "HEAD", cwd=dest).strip()


# --- manifest ----------------------------------------------------------------


def read_manifest(root: Path) -> dict:
    path = root / MANIFEST_PATH
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SyncError(
            f"{MANIFEST_PATH} is not valid JSON ({exc}).\n"
            "  Delete it and re-run to rebuild a baseline from upstream."
        ) from exc


def build_manifest(root: Path, upstream: str, sha: str, version: str) -> dict:
    return {
        "upstream": upstream,
        "upstream_sha": sha,
        "version": version,
        "synced_at": date.today().isoformat(),
        "files": {rel: hash_file(root / rel) for rel in sorted(iter_tracked(root, ENGINE_PATHS))},
    }


def write_manifest(root: Path, manifest: dict) -> None:
    path = root / MANIFEST_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_version(root: Path) -> str:
    path = root / VERSION_PATH
    return path.read_text(encoding="utf-8").strip() if path.exists() else UNKNOWN_VERSION


def write_version(root: Path, version: str) -> None:
    """Record the synced engine version. VERSION sits outside ENGINE_PATHS (it is never
    classified or conflicted), so without this write `--check` keeps announcing the update."""
    if version == UNKNOWN_VERSION:
        return
    (root / VERSION_PATH).write_text(version, encoding="utf-8")


# --- applying ----------------------------------------------------------------


def write_conflict_patch(root: Path, rel: str, local: Path, upstream: Path) -> Path:
    """Save the upstream-vs-local diff so the learner can resolve it later."""
    out = root / CONFLICT_DIR / (rel.replace("/", "__") + ".patch")
    out.parent.mkdir(parents=True, exist_ok=True)
    diff = difflib.unified_diff(
        local.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True),
        upstream.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True),
        fromfile=f"yours/{rel}",
        tofile=f"upstream/{rel}",
    )
    out.write_text("".join(diff), encoding="utf-8")
    return out


def apply(root: Path, upstream_root: Path, verdicts: list[FileVerdict]) -> None:
    for v in verdicts:
        if not v.is_write:
            continue
        dest = root / v.path
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(upstream_root / v.path, dest)


# --- reporting ---------------------------------------------------------------


def report(verdicts: list[FileVerdict], *, dry_run: bool) -> None:
    shown = [v for v in verdicts if v.decision in LABELS]
    if not shown:
        print("  everything already in step - nothing to do.")
        return

    width = max(len(LABELS[v.decision]) for v in shown)
    order = [
        Decision.UPDATE,
        Decision.NEW,
        Decision.CONFLICT,
        Decision.ADVISORY,
        Decision.REMOVED_UPSTREAM,
    ]
    for decision in order:
        for v in (x for x in shown if x.decision == decision):
            verb = LABELS[decision]
            prefix = "would " if dry_run and v.is_write else ""
            print(f"  {prefix}{verb:<{width}}  {v.path}")


def summarize(verdicts: list[FileVerdict]) -> str:
    counts = {d: sum(1 for v in verdicts if v.decision is d) for d in Decision}
    parts = [
        f"{counts[Decision.UPDATE]} updated",
        f"{counts[Decision.NEW]} new",
        f"{counts[Decision.CONFLICT]} needing review",
    ]
    if counts[Decision.KEEP_LOCAL]:
        parts.append(f"{counts[Decision.KEEP_LOCAL]} of your edits kept")
    return ", ".join(parts)


# --- commands ----------------------------------------------------------------


def cmd_check(root: Path, upstream: str, ref: str) -> int:
    """Cheap 'is anything new?' - one ls-remote, no clone. Exit 1 if an update waits.

    Prefers **release tags** over commit SHAs. A SHA comparison cannot work here:
    `--emit-manifest` necessarily runs *before* the commit that carries the manifest,
    so the recorded SHA is always one commit stale and every fresh template copy
    would announce a phantom update on day one. Tags have no such problem - VERSION
    is bumped in the same commit that gets tagged.
    """
    local = read_version(root)
    tags = remote_tags(upstream)
    newer = sorted((t for t in tags if is_newer(t, local)), key=parse_version)

    if newer:
        print(
            f"Engine update available: v{local} -> v{newer[-1].lstrip('vV')}.\n"
            "Run `python scripts/update_coach.py --dry-run` to see what would change."
        )
        return 1
    if tags:
        print(f"cse-coach engine is up to date (v{local}).")
        return 0

    # Untagged upstream (e.g. a fork, or pre-release canonical): fall back to the
    # SHA, and phrase it as a maybe, because a stale-by-one SHA is expected here.
    known = manifest_sha = read_manifest(root).get("upstream_sha")
    head = remote_head(upstream, ref)
    if not known:
        print(
            "No sync baseline recorded yet - run `python scripts/update_coach.py` "
            "to establish one and pick up any engine updates."
        )
        return 1
    if manifest_sha == head:
        print(f"cse-coach engine is up to date (v{local}).")
        return 0
    print(
        f"Upstream has moved since your last sync ({known[:7]} -> {head[:7]}); "
        "it may or may not touch engine files.\n"
        "Run `python scripts/update_coach.py --dry-run` to see what would change."
    )
    return 1


def cmd_sync(root: Path, upstream: str, ref: str, *, dry_run: bool) -> int:
    manifest = read_manifest(root)
    baseline = manifest.get("files", {})
    if not baseline:
        print(
            "! No baseline in .coach-sync/manifest.json - this is the first sync.\n"
            "  Without it, a file you customized is indistinguishable from one that is\n"
            "  simply out of date, so anything that differs is reported rather than\n"
            "  overwritten. Nothing of yours will be lost.\n"
        )

    with tempfile.TemporaryDirectory(prefix="cse-coach-upstream-") as tmp:
        upstream_root = Path(tmp) / "repo"
        print(f"Fetching {upstream} @ {ref} ...")
        sha = clone_upstream(upstream, ref, upstream_root)
        upstream_version = read_version(upstream_root)
        print(f"  upstream v{upstream_version} ({sha[:7]}); you are on v{read_version(root)}\n")

        verdicts = plan(root, upstream_root, baseline)
        report(verdicts, dry_run=dry_run)

        conflicts = [v for v in verdicts if v.decision is Decision.CONFLICT]
        if dry_run:
            print(f"\nDry run - nothing written. Would be: {summarize(verdicts)}.")
            return 0

        apply(root, upstream_root, verdicts)
        for v in conflicts:
            write_conflict_patch(root, v.path, root / v.path, upstream_root / v.path)

        # The baseline is what upstream shipped, not what the learner now holds: hashing the
        # learner's tree would record a conflict-protected file's local hash, and the next
        # sync would read it as untouched and overwrite it.
        write_manifest(
            root,
            build_manifest(upstream_root, upstream, sha, upstream_version),
        )
        write_version(root, upstream_version)

    print(f"\nDone: {summarize(verdicts)}.")
    if conflicts:
        print(
            f"\n{len(conflicts)} file(s) need review - you and upstream both changed them,\n"
            f"so nothing was overwritten. Diffs are in {CONFLICT_DIR.as_posix()}/ (upstream vs yours).\n"
            "Ask your coach to walk you through them."
        )
    print("Your trackers, schedules, solutions and cse.config.yml were not touched.")
    return 0


def cmd_emit_manifest(root: Path, upstream: str) -> int:
    """Maintainer-side: record what THIS tree ships. Run before tagging a release."""
    try:
        sha = _git("rev-parse", "HEAD", cwd=root).strip()
    except SyncError:
        sha = ""
    manifest = build_manifest(root, upstream, sha, read_version(root))
    write_manifest(root, manifest)
    print(f"Wrote {MANIFEST_PATH} - {len(manifest['files'])} engine files at v{manifest['version']}.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Sync engine files from canonical cse-coach.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--upstream", default=DEFAULT_UPSTREAM, help="canonical repo URL")
    parser.add_argument("--ref", default=DEFAULT_REF, help="branch or tag to sync from")
    parser.add_argument("--root", type=Path, default=REPO_ROOT, help="repo to update")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="report whether an update exists")
    mode.add_argument("--dry-run", action="store_true", help="show changes without writing")
    mode.add_argument(
        "--emit-manifest",
        action="store_true",
        help="(maintainers) record this tree as the shipped baseline",
    )
    args = parser.parse_args(argv)

    root = args.root.resolve()
    try:
        if args.emit_manifest:
            return cmd_emit_manifest(root, args.upstream)
        if args.check:
            return cmd_check(root, args.upstream, args.ref)
        return cmd_sync(root, args.upstream, args.ref, dry_run=args.dry_run)
    except SyncError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
