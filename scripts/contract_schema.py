"""Validate a dashboard contract payload against its hand-maintained JSON schema."""

import functools
import json
import sys
from pathlib import Path

SCHEMA_EXIT_CODE = 2
MAX_SCHEMA_ERRORS_SHOWN = 20
INSTALL_HINT = "jsonschema not installed: py -m pip install -r requirements.txt"
ROOT_PATH = "$"
DASHBOARD = Path(__file__).resolve().parent.parent / "dashboard"
SCHEMA_GLOB = "*.schema.json"
ID_KEY = "$id"


def _format_path(error) -> str:
    parts = [str(part) for part in error.absolute_path]
    return ".".join([ROOT_PATH, *parts]) if parts else ROOT_PATH


@functools.cache
def _registry():
    """Every dashboard/*.schema.json keyed by its `$id`, so a `$ref` to another contract
    resolves from disk. Built once per process; `referencing` never fetches over the network."""
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT7

    resources = []
    for path in sorted(DASHBOARD.glob(SCHEMA_GLOB)):
        contents = json.loads(path.read_text(encoding="utf-8"))
        if ID_KEY in contents:
            resources.append((contents[ID_KEY],
                              Resource.from_contents(contents, default_specification=DRAFT7)))
    return Registry().with_resources(resources)


def validate(payload: dict, schema_path: Path) -> list[str]:
    """Return "<json path>: <message>" for every schema violation; [] when valid.

    Raises ValueError when the schema `$ref`s something no dashboard schema defines."""
    try:
        from jsonschema.validators import validator_for
        from referencing.exceptions import Unresolvable
    except ImportError:
        raise SystemExit(INSTALL_HINT) from None
    schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
    validator = validator_for(schema)(schema, registry=_registry())
    try:
        errors = sorted(validator.iter_errors(payload),
                        key=lambda e: list(map(str, e.absolute_path)))
    except Unresolvable as exc:
        raise ValueError(f"{Path(schema_path).name}: unresolvable $ref: {exc}") from exc
    return [f"{_format_path(e)}: {e.message}" for e in errors]


def exit_on_errors(heading: str, errors: list[str]) -> None:
    """Print `heading` and the first MAX_SCHEMA_ERRORS_SHOWN errors to stderr and exit
    SCHEMA_EXIT_CODE, so the caller writes nothing; return when there are no errors."""
    if not errors:
        return
    print(f"ERROR: {heading}", file=sys.stderr)
    for error in errors[:MAX_SCHEMA_ERRORS_SHOWN]:
        print(f"  - {error}", file=sys.stderr)
    sys.exit(SCHEMA_EXIT_CODE)


def check(payload: dict, schema_path: Path) -> None:
    """Validate `payload` against `schema_path`; exit SCHEMA_EXIT_CODE on any violation."""
    errors = validate(payload, schema_path)
    exit_on_errors(f"payload violates {Path(schema_path).name} ({len(errors)} errors):", errors)
