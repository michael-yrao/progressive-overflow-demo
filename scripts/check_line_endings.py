"""Report-only pre-commit check: did a staged edit flip a file's line endings?

A text-mode rewrite (Python `open(..., "w")` on Windows, an editor's "normalize EOL") turns a
CRLF file into LF and stages a whole-file diff for a one-line change. This compares each
modified staged file's HEAD blob with its STAGED blob — like with like, never the working
tree, because git normalizes some files on `git add` — and prints one ERROR line per file
whose style changed (crlf <-> lf <-> mixed). Binary blobs (a NUL byte) and files new at HEAD
are skipped. Always exits 0: the hook calls it with `|| true`.
"""
from __future__ import annotations

import subprocess
import sys

STYLE_CRLF = "crlf"
STYLE_LF = "lf"
STYLE_MIXED = "mixed"
STYLE_NONE = "none"  # no newline at all


def classify(blob: bytes) -> str:
    """The line-ending style of `blob`: crlf, lf, mixed, or none (no newline)."""
    crlf = blob.count(b"\r\n")
    lf = blob.count(b"\n") - crlf
    if crlf and lf:
        return STYLE_MIXED
    if crlf:
        return STYLE_CRLF
    if lf:
        return STYLE_LF
    return STYLE_NONE


def is_binary(blob: bytes) -> bool:
    return b"\0" in blob


def flipped_endings(head_blob: bytes | None, staged_blob: bytes) -> tuple[str, str] | None:
    """(old, new) styles when both have a style and they differ; else None. A new file
    (no HEAD blob) and a binary blob are never reported."""
    if head_blob is None or is_binary(head_blob) or is_binary(staged_blob):
        return None
    old, new = classify(head_blob), classify(staged_blob)
    if STYLE_NONE in (old, new) or old == new:
        return None
    return old, new


def _git_lines(*args: str) -> list[str]:
    result = subprocess.run(["git", *args], capture_output=True, text=True, check=True,
                            encoding="utf-8")
    return [line for line in result.stdout.splitlines() if line]


def read_blobs(specs: list[str]) -> list[bytes | None]:
    """The bytes for each object spec (`HEAD:path`, `:path`), None when missing — all
    through ONE `git cat-file --batch` process."""
    request = "".join(f"{spec}\n" for spec in specs).encode("utf-8")
    out = subprocess.run(["git", "cat-file", "--batch"], input=request,
                         capture_output=True, check=True).stdout
    blobs: list[bytes | None] = []
    pos = 0
    for _ in specs:
        end = out.index(b"\n", pos)
        header = out[pos:end].decode("utf-8").split()
        pos = end + 1
        if len(header) != 3 or header[1] != "blob":
            blobs.append(None)
            continue
        size = int(header[2])
        blobs.append(out[pos:pos + size])
        pos += size + 1  # the LF git prints after each object
    return blobs


def main() -> int:
    paths = _git_lines("diff", "--cached", "--name-only", "--diff-filter=M")
    if not paths:
        return 0
    blobs = read_blobs([f"HEAD:{p}" for p in paths] + [f":{p}" for p in paths])
    heads, staged = blobs[:len(paths)], blobs[len(paths):]
    for path, head_blob, staged_blob in zip(paths, heads, staged):
        if staged_blob is None:
            continue
        flip = flipped_endings(head_blob, staged_blob)
        if flip:
            old, new = flip
            print(f"ERROR: {path}: line endings changed {old.upper()} -> {new.upper()} "
                  f"(HEAD vs staged)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
