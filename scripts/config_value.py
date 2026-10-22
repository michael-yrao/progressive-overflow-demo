"""Print one value from cse.config.yml, for shell and workflow use.

    py scripts/config_value.py automation.weekly_build --default false
    py scripts/config_value.py timezone --default UTC --zone

Scalars print raw; booleans print `true` / `false`. Exit 2 (message on stderr) when the key
is missing and no --default is given, when the value is a mapping or a list, or when --zone
names a timezone zoneinfo rejects (glibc silently treats a bad TZ as UTC, so the check has
to happen here). A key whose value is null counts as missing. A config file that does not
exist counts as every key missing, so --default still answers.
"""
from __future__ import annotations

import argparse
import sys
import zoneinfo
from pathlib import Path

import yaml

from check_single_source import dig

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = REPO_ROOT / "cse.config.yml"
EXIT_REFUSED = 2


def render(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def load_config(path: Path) -> dict:
    if not path.is_file():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def read_value(config: dict, key: str, default: str | None) -> str:
    """The rendered value of `key`, or `default`. Raises ValueError when neither exists."""
    try:
        value = dig(config, key)
    except (IndexError, ValueError):  # a list index past the end, or a non-numeric one
        value = None
    if value is None:
        if default is None:
            raise ValueError(f"{key}: not set in the config and no --default given")
        return default
    if isinstance(value, (dict, list)):
        raise ValueError(f"{key}: a mapping or list, not a single value")
    return render(value)


def check_zone(name: str) -> None:
    try:
        zoneinfo.ZoneInfo(name)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"{name!r} is not a timezone zoneinfo knows ({exc})") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("key", help="dotted key, e.g. automation.weekly_build or solutions.roots.0")
    parser.add_argument("--default", default=None)
    parser.add_argument("--zone", action="store_true", help="the value must be an IANA timezone")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    args = parser.parse_args(argv)
    try:
        text = read_value(load_config(args.config), args.key, args.default)
        if args.zone:
            check_zone(text)
    except ValueError as exc:
        print(f"config_value: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
