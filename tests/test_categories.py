"""Tests for the category ontology and classifier."""

from __future__ import annotations

import pytest

from custom_components.buymeapie.categories import (
    CategoryClassifier, category_name, keyword_category, order_index, resolve_category,
)


@pytest.mark.parametrize(
    ("title", "group"),
    [
        ("TK Himbeeren", 1), ("Himbeeren", 6), ("Bio Bananen", 6), ("Fleischsalat", 3),
        ("Kokosmilch", 4), ("Hafermilch", 7), ("Apfelsaft", 4), ("Gewürzgurken", 4),
        ("Gurke", 6), ("Klopapier", 0), ("Brötchen", 2), ("Hamburgerbrötchen", 4),
        ("Rinderhackfleisch", 5), ("Eier", 7), ("Reis", 4), ("Eis", 1),
        ("Stückige Tomaten", 4), ("Kartoffelsalat", 7), ("Kamillentee", 4),
    ],
)
def test_keywords(title: str, group: int) -> None:
    result = keyword_category(title)
    assert result is not None and result[0] == group, result


def test_unknown_keyword() -> None:
    assert keyword_category("Quinoa") is None
    assert keyword_category("") is None


def test_classifier_order() -> None:
    clf = CategoryClassifier(
        [("Hafermilch", 4, 9), ("Quinoa bunt", 4, 3), ("Zwiebeln", 0, 7)]
    )
    # 1. the user's own choice wins
    assert clf.suggest("Hafermilch").source == "history"
    assert clf.suggest("hafermilch").group_id == 4
    # 2. keyword ontology
    s = clf.suggest("Bio Hafermilch")
    assert (s.group_id, s.source) == (7, "keyword")
    # 3. similar title from the history
    s = clf.suggest("Quinoa")
    assert (s.group_id, s.source, s.reason) == (4, "similar", "Quinoa bunt")
    # colour 0 in the history is treated as "not categorised" for learning
    assert clf.suggest("Zwiebeln").group_id == 0
    assert clf.suggest("Rote Zwiebeln").group_id == 6
    # 4. fallback
    assert clf.suggest("Geschenk für Oma").source == "default"


def test_names_and_order() -> None:
    assert category_name(6).endswith("Obst & Gemüse")
    assert category_name(6, {6: "Gemüse"}) == "Gemüse"
    assert category_name(12) == "Farbe 12"
    assert order_index(7) < order_index(6) < order_index(1) < order_index(12) < order_index(0)


@pytest.mark.parametrize(
    ("value", "expected"),
    [("4", 4), (6, 6), ("obst", 6), ("Tiefkühl", 1), ("🧊 Tiefkühl", 1), ("99", None), ("xyz", None)],
)
def test_resolve(value, expected) -> None:
    assert resolve_category(value) == expected
