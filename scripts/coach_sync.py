"""Three-way sync state for engine files. Shared by update_coach.py and its tests.

Why this module exists at all
-----------------------------
A repo created with GitHub's "Use this template" has **no shared history** with
cse-coach, so `git merge upstream/main` can never run against it. This module does
the part git would have done: for each *engine-owned* file it decides between
"take upstream", "keep yours", and "needs review", by comparing three hashes -

    local     what the file is now, in the learner's repo
    upstream  what canonical ships today
    baseline  what canonical shipped at the learner's LAST sync
              (recorded in .coach-sync/manifest.json, which travels with the template)

The baseline is the whole trick. Without it you cannot tell "the learner customized
this" from "the learner is simply behind", and every sync degenerates into either
clobbering their edits or refusing to touch anything.

**Learner data is not modeled here and never can be.** Trackers, schedules,
solutions and cse.config.yml are absent from the manifest, so this module has no
opinion about them and no code path that writes to them.
"""

from __future__ import annotations

import fnmatch
import hashlib
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

# Git runs hooks with a cp1252 console on Windows; the first non-ASCII character printed
# would otherwise kill the script mid-run while the commit still succeeds. See _console.
import _console

_console.force_utf8()

# --- What upstream owns ------------------------------------------------------
# Paths the learner is not expected to edit. Anything matching these is offered
# for sync; anything else is learner data and is never read, written, or reported.
#
# Being generous here is safe: a file the learner DID edit is protected by the
# three-way rule below, not by its absence from this list. The list decides what
# we look at; the hashes decide what we touch.
ENGINE_PATHS = (
    "scripts/*.py",
    "tests/*.py",
    ".claude/skills/**/*.md",
    ".claude/memory/feedback_*.md",
    # A FEW project files are genericized model templates the skill's references cite, so they must
    # travel with it — named EXPLICITLY, never a `project_*` glob. project_ is otherwise learner state
    # (standing personal context) and must stay out, or every adopter's own project note would be
    # offered for sync. The glob boundary is guarded by test_coach_sync (`project_whatever.md` -> not
    # engine); these three exact paths are the deliberate exception, not a hole in that rule.
    ".claude/memory/project_ai_pillar.md",
    ".claude/memory/project_recognition_probes.md",
    ".claude/memory/project_sd_mock_model.md",
    # Agent hooks are engine, not learner data. Their *wiring* lives in
    # `.claude/settings.json`, which is gitignored and per-machine (see docs/HOOKS.md) —
    # but the scripts themselves ship, and were invisible to both directions of sync
    # until this pattern existed.
    ".claude/hooks/*.py",
    ".githooks/*",
    "curriculum/**/*.yml",
    "cse.config.example.yml",
    # The dated decision log that rule files reconcile against. Engine, not learner data:
    # it records when the MODEL changed (a retired concept, a moved boundary), which every
    # adopter needs, while `cse.config.yml` — the learner's own values — stays out by design.
    #
    # ⚠️ It was invisible to BOTH sync directions until Aug 17, 2026 because nothing here
    # matched a bare root-level .yml. A new engine artifact does not automatically become
    # syncable; the pattern list is not self-extending, and neither direction complains
    # about a file it was never told to look at.
    "decisions.yml",
    "docs/PHILOSOPHY.md",
    # The 4-tier context-memory architecture doc. Engine, not learner data — and, like decisions.yml
    # once was, invisible to sync until named here. Added when the reference/spine split landed.
    "docs/ARCHITECTURE.md",
    "docs/STYLE_GUIDE.md",
    "docs/foundations/*/templates/*",
    "docs/foundations/dsa/patterns/**/*.md",
    # `**` not `*`: fundamentals were reorganized into complexity/ and graph_theory/ subdirs, which a
    # single-segment glob silently misses — exactly the "not self-extending" trap flagged above.
    "docs/foundations/dsa/fundamentals/**/*.md",
    "AGENTS.md",
    # The honest-progress data contract gamify.py emits against — engine, not learner data,
    # like the curriculum YAMLs above. Named explicitly rather than a `dashboard/*` glob: the
    # generated progress.json/progress-summary.json under the same directory ARE learner data
    # and must never be offered for sync.
    "dashboard/progress.schema.json",
    # The other dashboard data contracts the export_*.py / dashboard_indexes.py scripts validate
    # against (scripts/contract_schema.py loads every dashboard/*.schema.json by `$id`). Named
    # one by one, for the reason above: NOT a `dashboard/*.schema.json` glob, which would also
    # offer cheat-sheets.schema.json (a runtime copy of the fixture below). The curated
    # manifests dashboard/showcase.yml and dashboard/bigo.yml are the learner's own picks and
    # must never match here; requirements.txt carries the validators' pip dependencies.
    "dashboard/showcase.schema.json",
    "dashboard/big-o.schema.json",
    "dashboard/practice.schema.json",
    "dashboard/practice-index.schema.json",
    "dashboard/showcase-index.schema.json",
    "dashboard/showcase-problem.schema.json",
    "dashboard/manifest.schema.json",
    "dashboard/pattern-sense.schema.json",
    "requirements.txt",
    # build_cheatsheets.py copies fixtures/cheat-sheets.schema.json into dashboard/ at runtime
    # and its golden test reads fixtures/cheat-sheets.seed.json, so both must travel with the
    # engine — and, like decisions.yml once was, scripts/fixtures/ was invisible to sync until
    # named here.
    "scripts/fixtures/*.json",
    # The skill-creator eval suite (evals.json, the rubric, its fixture files) and this repo's
    # own hook tests. Invisible to sync until named here, same trap as scripts/fixtures/ above:
    # `.claude/hooks/*.py` already reaches a top-level hook script, but not one nested under
    # hooks/tests/, so that directory needs its own explicit pattern.
    ".claude/skills/**/*.json",
    ".claude/skills/**/evals/files/*",
    ".claude/hooks/tests/*.py",
    # The fold, weekly-build and onboard Actions are engine: their workflows and the composite
    # actions they share must reach a learner's repo through sync.
    ".github/workflows/*.yml",
    ".github/actions/**/action.yml",
)

# Reported when upstream changes them, never written. These are the files every
# adopter is *expected* to rewrite - auto-updating them would overwrite the
# learner's own house rules, and flagging them as conflicts every single sync
# would train the learner to ignore the report.
ADVISORY_PATHS = (
    "CLAUDE.md",
    "README.md",
)

MANIFEST_PATH = Path(".coach-sync/manifest.json")
CONFLICT_DIR = Path(".coach-sync/conflicts")
VERSION_PATH = Path("VERSION")


class Decision(Enum):
    """What to do with one engine file."""

    UNCHANGED = "unchanged"  # upstream matches what you already have
    UPDATE = "update"  # you never touched it, upstream moved -> take upstream
    NEW = "new"  # upstream added a file you don't have
    KEEP_LOCAL = "keep-local"  # you edited it, upstream didn't -> yours wins, silently
    CONFLICT = "conflict"  # you edited it AND upstream moved -> report, touch nothing
    REMOVED_UPSTREAM = "removed-upstream"  # upstream dropped it; we never delete
    ADVISORY = "advisory"  # upstream moved; report only, by policy


#: Decisions that cause a write. Everything else is read-only.
WRITING = frozenset({Decision.UPDATE, Decision.NEW})

#: Decisions worth putting in front of a human.
NEEDS_ATTENTION = frozenset({Decision.CONFLICT, Decision.REMOVED_UPSTREAM, Decision.ADVISORY})


@dataclass(frozen=True)
class FileVerdict:
    path: str
    decision: Decision
    local: str | None
    upstream: str | None
    baseline: str | None

    @property
    def is_write(self) -> bool:
        return self.decision in WRITING

    @property
    def needs_attention(self) -> bool:
        return self.decision in NEEDS_ATTENTION


def parse_version(text: str) -> tuple[int, ...] | None:
    """`v1.2.3` / `1.2.3` -> (1, 2, 3). Anything unparseable -> None.

    Used to compare the local VERSION against upstream's release tags. Versions,
    unlike commit SHAs, can be compared *remotely* (`git ls-remote --tags`) and have
    no chicken-and-egg problem: VERSION is bumped in the very commit that gets
    tagged, so a shipped manifest always describes itself correctly.
    """
    cleaned = text.strip().lstrip("vV").split("-")[0].split("+")[0]
    if not cleaned:
        return None
    parts = cleaned.split(".")
    if not all(p.isdigit() for p in parts):
        return None
    return tuple(int(p) for p in parts)


def is_newer(candidate: str, current: str) -> bool:
    """True if `candidate` is a strictly newer version than `current`.

    Unparseable input on either side returns False - an unreadable version is not
    evidence of an update, and a spurious "update available" that never goes away
    is exactly how a notice gets trained into background noise.
    """
    a, b = parse_version(candidate), parse_version(current)
    if a is None or b is None:
        return False
    return a > b


def hash_bytes(data: bytes) -> str:
    """sha256 of `data`, with text line endings normalized to LF first.

    Line-ending normalization is load-bearing, not cosmetic. Git rewrites CRLF<->LF
    on checkout (`core.autocrlf`, the Windows default), so the learner's working
    tree and the freshly-cloned upstream tree can hold byte-different copies of a
    file that is *identical in content*. Hashing raw bytes would then mark every
    text file in a Windows repo as locally modified, turning the entire sync into
    one enormous phantom conflict. Found the first time this ran end-to-end.

    Files containing a NUL are treated as binary and hashed verbatim.
    """
    if b"\x00" not in data:
        data = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(data).hexdigest()


def hash_file(path: Path) -> str | None:
    """sha256 of a file, or None if it isn't there."""
    if not path.is_file():
        return None
    return hash_bytes(path.read_bytes())


def matches(rel: str, patterns: tuple[str, ...]) -> bool:
    """True if `rel` (a POSIX-style relative path) matches any glob in `patterns`.

    `**` is handled by also testing the pattern with `**/` collapsed, because
    fnmatch has no concept of path segments - `a/**/*.md` alone would not match
    `a/b.md`, which is virtually always what the author of the pattern intended.

    A `..` segment never matches anything, whatever the patterns say. fnmatch's `*`
    happily spans both `/` and `..`, so `.claude/skills/**/evals/files/*` also reaches
    `.claude/skills/cse-coach/evals/files/../../../cse.config.yml` - a fixture path
    climbing straight out of its own directory and back into the learner's config. No
    pattern list can close that by being more specific; the segment itself has to be
    refused before any pattern gets a look at the path.
    """
    if any(part == ".." for part in rel.split("/")):
        return False
    for pat in patterns:
        if fnmatch.fnmatch(rel, pat):
            return True
        if "**/" in pat and fnmatch.fnmatch(rel, pat.replace("**/", "")):
            return True
    return False


def iter_tracked(root: Path, patterns: tuple[str, ...]) -> set[str]:
    """Every file under `root` matching `patterns`, as relative POSIX paths."""
    found: set[str] = set()
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if _is_noise(rel):
            continue
        if matches(rel, patterns):
            found.add(rel)
    return found


def _is_noise(rel: str) -> bool:
    """Paths that are never content, whatever the patterns say."""
    parts = rel.split("/")
    return any(
        part in {".git", "__pycache__", ".pytest_cache", ".coach-sync", "worktrees"}
        for part in parts
    )


def classify_one(
    rel: str,
    local: str | None,
    upstream: str | None,
    baseline: str | None,
    advisory: bool = False,
) -> FileVerdict:
    """Decide the fate of a single path from its three hashes.

    The table, in the order the branches fire:

        upstream missing   -> REMOVED_UPSTREAM (we never delete for you)
        local missing      -> NEW
        local == upstream  -> UNCHANGED (already in step; baseline is irrelevant)
        advisory path      -> ADVISORY (report only, by policy)
        local == baseline  -> UPDATE     (untouched by you; safe to overwrite)
        upstream==baseline -> KEEP_LOCAL (only you moved; nothing to bring down)
        otherwise          -> CONFLICT   (both moved; a human decides)

    Note `local == upstream` is checked BEFORE the baseline branches: if the two
    already agree, the file is in step no matter what the baseline says, and a
    stale-but-harmless manifest entry must not manufacture a phantom conflict.
    """
    if upstream is None:
        return FileVerdict(rel, Decision.REMOVED_UPSTREAM, local, upstream, baseline)
    if local is None:
        return FileVerdict(rel, Decision.NEW, local, upstream, baseline)
    if local == upstream:
        return FileVerdict(rel, Decision.UNCHANGED, local, upstream, baseline)
    if advisory:
        return FileVerdict(rel, Decision.ADVISORY, local, upstream, baseline)
    if local == baseline:
        return FileVerdict(rel, Decision.UPDATE, local, upstream, baseline)
    if upstream == baseline:
        return FileVerdict(rel, Decision.KEEP_LOCAL, local, upstream, baseline)
    return FileVerdict(rel, Decision.CONFLICT, local, upstream, baseline)


def plan(local_root: Path, upstream_root: Path, baseline: dict[str, str]) -> list[FileVerdict]:
    """Classify every engine + advisory path across both trees.

    A path is considered if it exists in EITHER tree (or in the baseline), so that
    upstream additions and upstream deletions are both visible.
    """
    verdicts: list[FileVerdict] = []

    for patterns, advisory in ((ENGINE_PATHS, False), (ADVISORY_PATHS, True)):
        paths = iter_tracked(local_root, patterns) | iter_tracked(upstream_root, patterns)
        paths |= {rel for rel in baseline if matches(rel, patterns)}
        for rel in sorted(paths):
            verdicts.append(
                classify_one(
                    rel,
                    hash_file(local_root / rel),
                    hash_file(upstream_root / rel),
                    baseline.get(rel),
                    advisory=advisory,
                )
            )
    return verdicts
