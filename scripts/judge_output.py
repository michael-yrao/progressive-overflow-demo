"""Score a cse-coach turn against the output-quality standard with an LLM judge.

Measures the four standards in `.claude/skills/cse-coach/references/output-quality.md`:

    F1            precision (every sentence needed) x recall (every content-contract
                  item for this moment present), harmonic mean.
    Groundedness  every repo-state claim in the turn points at a tool result, or is
                  phrased as a plan.
    Narrative     one thread per turn, answer first, sent once — no running commentary,
                  no partial board or rating.
    Readability   short sentences, parallel lists, expanded acronyms, no em-dash chains.

Usage:
    python scripts/judge_output.py <transcript.jsonl> [--turns N] [--model ID] \\
        [--check] [--dry-run] [--json out.json]
    python scripts/judge_output.py <turn.md> --moment <name>

Transcript mode scores every real turn (split at real user messages, mirroring the
boundary rule in `.claude/hooks/problem_link_reminder.py`); `--turns N` scores only the
last N. Moment mode scores one turn already saved as a `.md` file, told which
content-contract row to grade it against.

Why stdlib `urllib` and not the Anthropic SDK: this engine has a zero-dependency
guarantee (see `scripts/effort_budget.py`, `scripts/check_single_source.py`) — every
script here must run on a bare Python install, with PyYAML as the only optional
extra. Pulling in the SDK for one script would break that for the whole repo.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

# Git runs hooks with a cp1252 console on Windows; the first emoji printed would
# otherwise kill the script mid-report while the commit still succeeds. See _console.
import _console

_console.force_utf8()

REPO = Path(__file__).resolve().parent.parent
# In an adopter/template checkout the live cse.config.yml does not exist yet (it is
# written at setup) — fall back to the shipped example, same rule as
# check_single_source.py.
CONFIG = REPO / "cse.config.yml"
if not CONFIG.is_file():
    CONFIG = REPO / "cse.config.example.yml"
RUBRIC = REPO / ".claude/skills/cse-coach/evals/rubric.md"

API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
REQUEST_TIMEOUT_SECONDS = 60
MAX_TOKENS = 1024
TOOL_RESULT_EXCERPT_CHARS = 200

#: Fallback only — used when a key is absent from cse.config.yml / the example. Must
#: mirror `output_quality:` there, or a machine that cannot read the config silently
#: judges against the wrong model or threshold. Checked by
#: scripts/check_single_source.py SCRIPT_DEFAULTS.
DEFAULT_CONFIG = {
    "judge_model": "claude-sonnet-5",
    "pass_threshold": 0.75,
    "max_sentence_words": 20,
}


def _announce_fallback(key: str) -> None:
    print(
        f"judge_output: output_quality.{key} missing from {CONFIG.name} (or unreadable) "
        f"— using DEFAULT_CONFIG[{key!r}] = {DEFAULT_CONFIG[key]!r}"
    )


def load_config() -> dict:
    """Read the `output_quality:` block, announcing any DEFAULT_CONFIG fallback.

    Lazy `import yaml` with a regex-scrape fallback — the house pattern in
    `scripts/effort_budget.py` / `scripts/update_review_dates.py`. Unlike those two,
    this script's fallback PRINTS when it fires: a silent default here would mean the
    judge and `--check` threshold could drift from the config with nothing to notice
    (CLAUDE.md single-source rule).
    """
    cfg = dict(DEFAULT_CONFIG)
    found = dict.fromkeys(DEFAULT_CONFIG, False)
    try:
        text = CONFIG.read_text(encoding="utf-8")
    except OSError:
        text = ""

    doc = None
    if text:
        try:
            import yaml  # noqa: PLC0415

            doc = yaml.safe_load(text) or {}
        except Exception:  # noqa: BLE001 — PyYAML missing, or the file is mid-edit
            doc = None

    if isinstance(doc, dict):
        block = doc.get("output_quality") or {}
        if isinstance(block.get("judge_model"), str):
            cfg["judge_model"] = block["judge_model"]
            found["judge_model"] = True
        if isinstance(block.get("pass_threshold"), (int, float)):
            cfg["pass_threshold"] = float(block["pass_threshold"])
            found["pass_threshold"] = True
        readability = block.get("readability") or {}
        if isinstance(readability, dict) and isinstance(readability.get("max_sentence_words"), int):
            cfg["max_sentence_words"] = readability["max_sentence_words"]
            found["max_sentence_words"] = True
    elif text:
        # ---- Fallback: no PyYAML (or the file failed to parse). Regex scrape. ----
        m = re.search(r"judge_model:\s*[\"']?([\w.\-]+)", text)
        if m:
            cfg["judge_model"] = m.group(1)
            found["judge_model"] = True
        m = re.search(r"pass_threshold:\s*([\d.]+)", text)
        if m:
            cfg["pass_threshold"] = float(m.group(1))
            found["pass_threshold"] = True
        m = re.search(r"max_sentence_words:\s*(\d+)", text)
        if m:
            cfg["max_sentence_words"] = int(m.group(1))
            found["max_sentence_words"] = True

    for key, was_found in found.items():
        if not was_found:
            _announce_fallback(key)
    return cfg


def load_rubric() -> str:
    return RUBRIC.read_text(encoding="utf-8")


def _is_real_user_message(entry: dict) -> bool:
    """True for a human turn, False for a `tool_result` carrier.

    Copied boundary rule from `.claude/hooks/problem_link_reminder.py`
    (`_is_real_user_message`): a tool result is recorded as a `type: "user"` entry
    INSIDE the assistant turn it answers, so it is not a turn boundary.
    """
    if entry.get("type") != "user":
        return False
    content = (entry.get("message") or {}).get("content")
    if isinstance(content, str):
        return True
    if not isinstance(content, list):
        return False
    return not any(
        isinstance(block, dict) and block.get("type") == "tool_result"
        for block in content
    )


def _tool_result_text(block: dict) -> str:
    content = block.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
        )
    return ""


def _new_turn() -> dict:
    return {"text": [], "tool_uses": [], "tool_results": []}


def _finalize_turn(turn: dict) -> dict:
    return {
        "text": "\n".join(turn["text"]),
        "tool_uses": list(turn["tool_uses"]),
        "tool_results": list(turn["tool_results"]),
    }


def load_transcript_turns(path: Path) -> list[dict]:
    """Split a transcript into assistant turns at real user-message boundaries.

    One turn is every assistant `text` and `tool_use` block emitted between two real
    user messages, plus a compact excerpt of each `tool_result` the turn triggered (for
    groundedness). Sidechain (subagent) entries are skipped — they are not the coach's
    own turn.
    """
    try:
        with path.open(encoding="utf-8") as fh:
            entries = [json.loads(ln) for ln in fh if ln.strip()]
    except (OSError, json.JSONDecodeError, ValueError):
        return []

    turns: list[dict] = []
    current = _new_turn()
    for entry in entries:
        if entry.get("isSidechain"):
            continue
        if _is_real_user_message(entry):
            if current["text"] or current["tool_uses"]:
                turns.append(_finalize_turn(current))
            current = _new_turn()
            continue
        if entry.get("type") == "user":
            content = (entry.get("message") or {}).get("content") or []
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        excerpt = _tool_result_text(block)[:TOOL_RESULT_EXCERPT_CHARS]
                        current["tool_results"].append(excerpt)
            continue
        if entry.get("type") != "assistant":
            continue
        content = (entry.get("message") or {}).get("content") or []
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                current["text"].append(block.get("text", ""))
            elif block.get("type") == "tool_use":
                current["tool_uses"].append(block.get("name", "?"))

    if current["text"] or current["tool_uses"]:
        turns.append(_finalize_turn(current))
    return turns


def _load_moment_turn(path: Path) -> dict:
    return {"text": path.read_text(encoding="utf-8"), "tool_uses": [], "tool_results": []}


def _evidence_block(turn: dict) -> str:
    tool_uses = turn.get("tool_uses") or []
    tool_results = turn.get("tool_results") or []
    if not tool_uses and not tool_results:
        return "(no tool calls this turn)"
    lines = [f"Tool calls: {', '.join(tool_uses) if tool_uses else '(none)'}"]
    for i, excerpt in enumerate(tool_results, 1):
        lines.append(f"  result {i}: {excerpt}")
    return "\n".join(lines)


def build_prompt(rubric_text: str, moment: str | None, turn: dict) -> str:
    moment_line = f"Moment: {moment}\n\n" if moment else ""
    return (
        f"{rubric_text}\n\n"
        "---\n"
        f"{moment_line}"
        "TURN TEXT:\n"
        f"{turn['text']}\n\n"
        "---\n"
        "TOOL EVIDENCE (for groundedness):\n"
        f"{_evidence_block(turn)}\n\n"
        "---\n"
        "Return JSON only."
    )


def _extract_first_json_object(text: str) -> dict | None:
    """Parse the first balanced `{...}` block in `text`, skipping any surrounding prose."""
    start = text.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(text)):
            ch = text[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start : i + 1]
                    try:
                        obj = json.loads(candidate)
                    except json.JSONDecodeError:
                        break
                    if isinstance(obj, dict):
                        return obj
                    break
        start = text.find("{", start + 1)
    return None


def _as_float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _zero_score(moment: str | None, notes: list[str]) -> dict:
    return {
        "moment": moment,
        "f1": {"precision": 0.0, "recall": 0.0, "f1": 0.0},
        "groundedness": 0.0,
        "narrative": 0.0,
        "readability": 0.0,
        "notes": notes,
    }


def _normalize_score(parsed: dict) -> dict:
    f1_block = parsed.get("f1") if isinstance(parsed.get("f1"), dict) else {}
    notes = parsed.get("notes")
    return {
        "moment": parsed.get("moment"),
        "f1": {
            "precision": _as_float(f1_block.get("precision")),
            "recall": _as_float(f1_block.get("recall")),
            "f1": _as_float(f1_block.get("f1")),
        },
        "groundedness": _as_float(parsed.get("groundedness")),
        "narrative": _as_float(parsed.get("narrative")),
        "readability": _as_float(parsed.get("readability")),
        "notes": [str(n) for n in notes] if isinstance(notes, list) else [],
    }


def _response_text(payload: dict) -> str:
    blocks = payload.get("content") or []
    if not isinstance(blocks, list):
        return ""
    return "\n".join(
        b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text"
    )


def call_judge(prompt: str, model: str, api_key: str, turn_index: int) -> dict:
    """POST one turn's prompt to the Messages API and parse its JSON verdict.

    Never raises on a network/HTTP failure — that failure becomes a one-line note on
    a zeroed score, so one bad turn does not abort the whole run.
    """
    body = json.dumps(
        {
            "model": model,
            "max_tokens": MAX_TOKENS,
            "messages": [{"role": "user", "content": prompt}],
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        API_URL,
        data=body,
        headers={
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return _zero_score(None, [f"turn {turn_index}: HTTP {exc.code} — {exc.reason}"])
    except urllib.error.URLError as exc:
        return _zero_score(None, [f"turn {turn_index}: request failed — {exc.reason}"])
    except (TimeoutError, OSError, json.JSONDecodeError) as exc:
        return _zero_score(None, [f"turn {turn_index}: request failed — {exc}"])

    parsed = _extract_first_json_object(_response_text(payload))
    if parsed is None:
        return _zero_score(None, ["unparseable"])
    return _normalize_score(parsed)


def _turn_aggregate(score: dict) -> float:
    """(F1 + groundedness/2 + narrative/2 + readability/2) / 4 — every term in 0..1."""
    f1 = score["f1"]["f1"]
    groundedness = score["groundedness"] / 2
    narrative = score["narrative"] / 2
    readability = score["readability"] / 2
    return (f1 + groundedness + narrative + readability) / 4


def aggregate_scores(scores: list[dict]) -> float:
    if not scores:
        return 0.0
    return sum(_turn_aggregate(s) for s in scores) / len(scores)


def print_table(scores: list[dict], aggregate: float) -> None:
    header = f"{'#':>3}  {'moment':<24} {'F1':>5} {'ground':>7} {'narr':>5} {'read':>5}  notes"
    print(header)
    print("-" * len(header))
    for i, score in enumerate(scores):
        moment = str(score.get("moment") or "-")[:24]
        notes = "; ".join(score["notes"])
        print(
            f"{i:>3}  {moment:<24} {score['f1']['f1']:5.2f} {score['groundedness']:7.1f} "
            f"{score['narrative']:5.1f} {score['readability']:5.1f}  {notes}"
        )
    print(f"\naggregate: {aggregate:.3f}")


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "path", help="a transcript .jsonl (scores every real turn) or a single-turn .md file"
    )
    ap.add_argument("--turns", type=int, default=None, help="score only the last N transcript turns")
    ap.add_argument("--model", default=None, help="override output_quality.judge_model")
    ap.add_argument(
        "--check", action="store_true",
        help="exit 1 when the aggregate is below output_quality.pass_threshold",
    )
    ap.add_argument(
        "--dry-run", action="store_true",
        help="print the first prompt and exit; sends no request",
    )
    ap.add_argument("--json", metavar="OUT", help="write per-turn scores + aggregate to this file")
    ap.add_argument(
        "--moment", metavar="NAME",
        help="score PATH as one turn (a .md file) against this content-contract moment",
    )
    args = ap.parse_args()

    cfg = load_config()
    model = args.model or cfg["judge_model"]
    rubric_text = load_rubric().replace("{max_sentence_words}", str(cfg["max_sentence_words"]))

    path = Path(args.path)
    if args.moment:
        turns = [_load_moment_turn(path)]
        moments: list[str | None] = [args.moment]
    else:
        turns = load_transcript_turns(path)
        if args.turns is not None:
            turns = turns[-args.turns :]
        moments = [None] * len(turns)

    if not turns:
        print(f"judge_output: no turns found in {path}")
        sys.exit(1 if args.check else 0)

    prompts = [build_prompt(rubric_text, moment, turn) for moment, turn in zip(moments, turns)]

    if args.dry_run:
        print(prompts[0])
        return

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("judge_output: set ANTHROPIC_API_KEY to run the judge")
        sys.exit(2)

    scores = [call_judge(prompt, model, api_key, i) for i, prompt in enumerate(prompts)]
    aggregate = aggregate_scores(scores)
    print_table(scores, aggregate)

    if args.json:
        Path(args.json).write_text(
            json.dumps({"turns": scores, "aggregate": aggregate}, indent=2), encoding="utf-8"
        )

    if args.check:
        sys.exit(0 if aggregate >= cfg["pass_threshold"] else 1)


if __name__ == "__main__":
    main()
