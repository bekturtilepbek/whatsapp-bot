"""Сверка Pydantic-моделей с JSON Schema контракта на общих фикстурах.

Схема (docs/contracts/events.schema.json) — источник истины; модели в
core.events написаны вручную. Если они разъехались, один из тестов падает.
"""

import json
from pathlib import Path

import jsonschema
import pytest

from core.events import Event

REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_PATH = REPO_ROOT / "docs" / "contracts" / "events.schema.json"
EXAMPLES_DIR = REPO_ROOT / "docs" / "contracts" / "examples"

SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
EXAMPLE_FILES = sorted(EXAMPLES_DIR.glob("*.json"))


@pytest.mark.parametrize("example_path", EXAMPLE_FILES, ids=lambda p: p.stem)
def test_example_matches_json_schema(example_path: Path) -> None:
    example = json.loads(example_path.read_text(encoding="utf-8"))
    jsonschema.validate(instance=example, schema=SCHEMA)


@pytest.mark.parametrize("example_path", EXAMPLE_FILES, ids=lambda p: p.stem)
def test_example_matches_pydantic_model(example_path: Path) -> None:
    example = json.loads(example_path.read_text(encoding="utf-8"))
    from pydantic import TypeAdapter

    event = TypeAdapter(Event).validate_python(example)
    assert event.type == example["type"]


def test_examples_cover_all_schema_variants() -> None:
    types_in_examples = {json.loads(p.read_text(encoding="utf-8"))["type"] for p in EXAMPLE_FILES}
    types_in_schema = {
        definition["properties"]["type"]["const"] for definition in SCHEMA["definitions"].values()
    }
    assert types_in_examples == types_in_schema
