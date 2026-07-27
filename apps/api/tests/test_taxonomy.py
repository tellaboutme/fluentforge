"""The linguistic feature taxonomy.

What is under test is mostly *discipline*: codes are stable machine codes, the
set is closed so a typo cannot invent a category, and every display helper
survives contact with a code it has never seen — including the legacy
`item.<skill>` codes written before the taxonomy existed.
"""

from __future__ import annotations

import pytest

from apps.api.app.learning import taxonomy


def test_codes_are_unique_and_sorted() -> None:
    codes = taxonomy.codes()
    assert len(set(codes)) == len(codes)
    assert list(codes) == sorted(codes)


def test_every_feature_is_addressable_by_its_own_code() -> None:
    for code, feature in taxonomy.FEATURES.items():
        assert feature.code == code


def test_every_code_has_three_segments() -> None:
    """`domain.area.feature`. The shape is what keeps the set browsable."""
    for code in taxonomy.codes():
        assert code.count(".") == 2, code


def test_every_feature_is_described_well_enough_to_choose() -> None:
    """A content author picks a code from its description; a stub is useless."""
    for feature in taxonomy.FEATURES.values():
        assert feature.label.strip()
        assert len(feature.description.strip()) > 20, feature.code


def test_the_set_is_closed() -> None:
    assert not taxonomy.is_known("grammar.invented.category")
    with pytest.raises(KeyError):
        taxonomy.require("grammar.invented.category")


def test_get_returns_none_rather_than_raising() -> None:
    assert taxonomy.get("nothing.at.all") is None


def test_a_known_code_renders_as_its_label() -> None:
    feature = taxonomy.require("grammar.tense.past_simple_form")
    assert taxonomy.label_for(feature.code) == feature.label
    assert taxonomy.describe(feature.code) == feature.description


def test_a_legacy_code_still_renders() -> None:
    """Rows written before the taxonomy must not break the error log."""
    assert taxonomy.label_for("item.grammar.past_future_basic") == "grammar · past_future_basic"
    assert taxonomy.is_legacy("item.grammar.past_future_basic")
    assert isinstance(taxonomy.describe("item.grammar.past_future_basic"), str)


def test_a_current_code_is_not_legacy() -> None:
    assert not taxonomy.is_legacy("grammar.tense.past_simple_form")


def test_an_unknown_code_renders_as_itself() -> None:
    assert taxonomy.label_for("who.knows.what") == "who.knows.what"


def test_meaning_blocking_defaults_are_set_deliberately() -> None:
    """Not every error costs the reader the message, and the split matters:
    `docs/LEARNING_SCIENCE.md` ranks meaning-blocking errors first."""
    assert taxonomy.blocks_meaning_default("grammar.word_order.question") is True
    assert taxonomy.blocks_meaning_default("mechanics.spelling.common") is False
    # Unknown codes must not be assumed urgent.
    assert taxonomy.blocks_meaning_default("who.knows.what") is False


def test_the_taxonomy_is_not_all_one_way() -> None:
    """A taxonomy where everything blocks meaning has no ranking in it."""
    blocking = [f for f in taxonomy.FEATURES.values() if f.typically_blocks_meaning]
    assert 0 < len(blocking) < len(taxonomy.FEATURES)


def test_several_domains_are_represented() -> None:
    domains = {feature.domain for feature in taxonomy.FEATURES.values()}
    assert len(domains) >= 4
