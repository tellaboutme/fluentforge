"""Every evaluator prompt must name the fields its schema requires.

`CLAUDE.md` says each evaluator prompt has a schema. Both did -- and the
writing prompt never showed it to the model. It described the output in prose
("identify no more than three priority improvements", "distinguish meaning
errors, grammar errors, vocabulary issues"), and against a real model that
produced `priority_improvements`, then top-level `grammar`/`meaning`/`style`,
then `corrected_model`: three different shapes in three calls, every invented
key traceable to a line of the prompt.

The front matter pointed at `writing-evaluation.schema.json`, which is exact
and correct, and which a model has no way to read. A reference to a schema is
not a schema.

That defect was invisible to every existing test. The provider correctly
turns a schema violation into an abstention, the deterministic path correctly
carries on, and nothing anywhere is worse than "the AI said nothing today" --
so a prompt that could never work looked exactly like a prompt nobody had
configured.

These tests close the class rather than the instance. They do not check the
prompt is *good*; nothing here can. They check it is not silently impossible.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
PROMPT_DIR = REPO_ROOT / "prompts" / "evaluators"

_FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)


def _prompts() -> list[Path]:
    found = sorted(PROMPT_DIR.glob("*.md"))
    assert found, f"no evaluator prompts under {PROMPT_DIR}"
    return found


def _parse(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    match = _FRONT_MATTER.match(text)
    assert match, f"{path.name}: no front matter"
    return yaml.safe_load(match.group(1)) or {}, text[match.end() :]


@pytest.mark.parametrize("path", _prompts(), ids=lambda p: p.name)
def test_the_prompt_declares_a_schema_that_exists(path: Path) -> None:
    front, _ = _parse(path)

    declared = front.get("output_schema")
    assert declared, f"{path.name}: no output_schema"
    assert (REPO_ROOT / declared).is_file(), f"{path.name}: {declared} does not exist"


@pytest.mark.parametrize("path", _prompts(), ids=lambda p: p.name)
def test_the_prompt_names_every_required_field(path: Path) -> None:
    """The load-bearing one.

    A model cannot open the schema file. If the prompt does not say
    `priority_feedback`, the model will invent a name for that idea -- and it
    will be a reasonable name, and it will be rejected, and the whole
    evaluation will be discarded as an abstention that looks like the model
    being incapable.
    """
    front, body = _parse(path)
    schema = json.loads((REPO_ROOT / front["output_schema"]).read_text(encoding="utf-8"))

    missing = [field for field in schema.get("required", []) if field not in body]

    assert not missing, (
        f"{path.name} never names {missing}. A model has no way to read the "
        f"schema file, so it will invent a plausible key and have the whole "
        f"answer thrown away."
    )


@pytest.mark.parametrize("path", _prompts(), ids=lambda p: p.name)
def test_the_prompt_shows_the_shape_rather_than_describing_it(path: Path) -> None:
    """Naming the keys in prose is better than not, and still not enough.

    The failure was a model reading "priority improvements" in a sentence and
    deriving a key from the wording. A literal JSON example removes the
    inference entirely, which is the difference between a prompt that usually
    works and one that does.
    """
    _, body = _parse(path)

    assert "```json" in body, (
        f"{path.name} has no JSON example. Describing the output in prose is "
        f"what produced three different shapes in three calls."
    )


@pytest.mark.parametrize("path", _prompts(), ids=lambda p: p.name)
def test_the_prompt_says_extra_keys_are_rejected(path: Path) -> None:
    """The schema is `extra="forbid"`, and a model that does not know that
    will add a helpful field and lose everything with it."""
    _, body = _parse(path)
    lowered = body.lower()

    assert any(phrase in lowered for phrase in ("rejected", "any other key", "and nothing else")), (
        f"{path.name} never says that unexpected keys are refused."
    )


@pytest.mark.parametrize("path", _prompts(), ids=lambda p: p.name)
def test_the_prompt_is_versioned(path: Path) -> None:
    """Prompts are product logic. A change that alters what a learner is told
    has to be identifiable afterwards, which is why `evaluator_id` and
    `prompt_version` are stored on every judgement."""
    front, _ = _parse(path)

    version = str(front.get("version", ""))
    assert re.fullmatch(r"\d+\.\d+\.\d+", version), f"{path.name}: version {version!r}"


@pytest.mark.parametrize("path", _prompts(), ids=lambda p: p.name)
def test_the_prompt_tells_the_model_it_may_abstain(path: Path) -> None:
    """Abstention is a designed outcome, not a failure.

    A model that believes it must always produce a verdict will produce one
    for two sentences -- which `gpt-oss-120b` did, at confidence 0.85, before
    a word count stopped the request being made at all.
    """
    _, body = _parse(path)

    assert "abstain" in body.lower(), f"{path.name} never mentions abstaining."
