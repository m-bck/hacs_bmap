"""Unit tests for recipe parsing and matching."""

from __future__ import annotations

from fractions import Fraction

import pytest

from custom_components.buymeapie.recipes import (
    Recipe, find_recipe, matches_exclusion, parse_ingredient, parse_ingredients, split_exclusions,
)


@pytest.mark.parametrize(
    ("line", "title", "amount", "scaled"),
    [
        ("500 g Hackfleisch", "Hackfleisch", "500 g", "750 g"),
        ("500g Hack", "Hack", "500 g", "750 g"),
        ("2 Dosen stückige Tomaten", "stückige Tomaten", "2 Dosen", "3 Dosen"),
        ("1/2 Bund Petersilie", "Petersilie", "½ Bund", "1 Bund"),
        ("½ TL Salz", "Salz", "½ TL", "¾ TL"),
        ("1½ EL Öl", "Öl", "1½ EL", "2¼ EL"),
        ("1,5 l Milch", "Milch", "1½ l", "2¼ l"),
        ("3-4 Tomaten", "Tomaten", "3–4", "5–6"),
        ("3 Eier", "Eier", "3", "5"),  # counted items are rounded up
        ("2 Lauchzwiebeln", "Lauchzwiebeln", "2", "3"),  # "l" is not a unit here
        ("Lasagneplatten", "Lasagneplatten", "", ""),
        ("Parmesan | 100 g", "Parmesan", "100 g", "150 g"),
        ("Basilikum | etwas", "Basilikum", "etwas", "etwas"),
        ("- 1 Kopf Salat", "Salat", "1 Kopf", "2 Kopf"),
    ],
)
def test_parse_and_scale(line, title, amount, scaled) -> None:
    ingredient = parse_ingredient(line)
    assert ingredient is not None
    assert ingredient.title == title
    assert ingredient.amount() == amount
    assert ingredient.amount(Fraction(6, 4)) == scaled


def test_comments_and_blank_lines() -> None:
    assert parse_ingredients("# Teig\n\n200 g Mehl\n  \n# Belag\nKäse") == [
        parse_ingredient("200 g Mehl"), parse_ingredient("Käse"),
    ]


def test_exclusions() -> None:
    assert matches_exclusion("stückige Tomaten", "Tomaten")
    assert matches_exclusion("Tomaten", "tomate")
    assert not matches_exclusion("Tomatenmark", "Tomaten")
    assert matches_exclusion("Hackfleisch", "Fleisch")
    assert not matches_exclusion("Parmesan", "Bio")
    kept, excluded, unknown = split_exclusions(
        parse_ingredients("500 g Hack\n2 Dosen Tomaten\nTomatenmark"), ["Tomaten", "Zimt"]
    )
    assert [i.title for i in kept] == ["Hack", "Tomatenmark"]
    assert [i.title for i in excluded] == ["Tomaten"]
    assert unknown == ["Zimt"]


def test_find_recipe() -> None:
    lasagne = Recipe.from_data("1", {"name": "Lasagne", "aliases": "Lasagna, Nudelauflauf",
                                     "portions": 4, "ingredients": "Hack"})
    chili = Recipe.from_data("2", {"name": "Chili con Carne", "portions": 2, "ingredients": "Bohnen"})
    assert find_recipe([lasagne, chili], "lasagne") is lasagne
    assert find_recipe([lasagne, chili], "Nudelauflauf") is lasagne
    assert find_recipe([lasagne, chili], "chili") is chili
    assert find_recipe([lasagne, chili], "Pizza") is None
    assert lasagne.factor(6) == Fraction(3, 2)
    assert lasagne.factor(None) == 1
