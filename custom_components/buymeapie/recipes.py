"""Recipes: parsing ingredient lines, scaling portions, matching exclusions.

A recipe is stored as a config subentry with a name, optional aliases, the
number of portions and one ingredient per line, written like on a recipe
card::

    500 g Hackfleisch
    2 Dosen stückige Tomaten
    1/2 Bund Petersilie
    Lasagneplatten
    Parmesan | 100 g          (alternative: name | amount)
    # comments are ignored

The quantity in front is scaled to the requested portions; everything else is
the item name that ends up on the shopping list.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from fractions import Fraction
import re
from typing import Any, Final

from .categories import normalize, stem, tokenize

CONF_RECIPE_NAME: Final = "name"
CONF_RECIPE_ALIASES: Final = "aliases"
CONF_RECIPE_PORTIONS: Final = "portions"
CONF_RECIPE_INGREDIENTS: Final = "ingredients"
SUBENTRY_TYPE_RECIPE: Final = "recipe"
DEFAULT_PORTIONS: Final = 4

_UNITS: Final = (
    "kg", "g", "mg", "l", "ml", "cl", "dl", "el", "tl", "msp", "prise", "prisen",
    "pck", "pck.", "päckchen", "packung", "packungen", "pkg", "dose", "dosen",
    "glas", "gläser", "becher", "bund", "stück", "stk", "stk.", "zehe", "zehen",
    "scheibe", "scheiben", "tasse", "tassen", "flasche", "flaschen", "beutel",
    "kopf", "köpfe", "stange", "stangen", "zweig", "zweige", "handvoll", "tafel",
    "tafeln", "würfel", "netz", "schale", "schalen", "liter",
)
_UNIT_RE: Final = "|".join(sorted((re.escape(u) for u in _UNITS), key=len, reverse=True))
_VULGAR: Final = {"½": "1/2", "¼": "1/4", "¾": "3/4", "⅓": "1/3", "⅔": "2/3", "⅛": "1/8"}
_NUMBER: Final = r"\d+\s+\d+/\d+|\d+/\d+|\d+(?:[.,]\d+)?"
_LINE_RE: Final = re.compile(
    rf"^(?P<qty>(?:{_NUMBER})(?:\s*[-–]\s*(?:{_NUMBER}))?)\s*"
    rf"(?:(?P<unit>{_UNIT_RE})(?=\s|$)\.?\s*)?(?P<title>.*)$",
    re.IGNORECASE,
)
# Units where fractional results are rounded to whole numbers.
_WHOLE_UNITS: Final = {"g", "mg", "ml", "cl", "dl"}
# Measures that may stay fractional when scaled; everything else (no unit,
# "Dose", "Kopf", "Stück", ...) is counted and rounded up when scaled.
_MEASURE_UNITS: Final = {
    "kg", "l", "liter", "el", "tl", "msp", "prise", "prisen", "tasse", "tassen", "handvoll",
}


# Units that change between one and several ("1 Dose", "2 Dosen"). Units not
# listed here (g, EL, Bund, Becher, Stück, ...) are the same in both forms.
_PLURALS: Final = {
    "dose": "dosen", "zehe": "zehen", "packung": "packungen", "scheibe": "scheiben",
    "tasse": "tassen", "flasche": "flaschen", "stange": "stangen", "zweig": "zweige",
    "tafel": "tafeln", "schale": "schalen", "glas": "gläser", "kopf": "köpfe",
    "prise": "prisen",
}
_SINGULARS: Final = {plural: singular for singular, plural in _PLURALS.items()}
_AT_MOST_ONE: Final = {"1", "¼", "½", "¾"}


def _inflect(unit: str, number: str) -> str:
    """Unit in singular or plural to match the number text, keeping the case."""
    folded = unit.casefold()
    target = (_SINGULARS if number in _AT_MOST_ONE else _PLURALS).get(folded)
    if target is None:
        return unit
    return target[:1].upper() + target[1:] if unit[:1].isupper() else target


def _to_fraction(text: str) -> Fraction:
    text = text.strip().replace(",", ".")
    if " " in text:  # "1 1/2"
        whole, frac = text.split(None, 1)
        return Fraction(whole) + Fraction(frac)
    return Fraction(text)


def _format_number(value: Fraction, unit: str | None, scaled: bool = False) -> str:
    folded = unit.casefold() if unit else None
    if scaled and folded not in _MEASURE_UNITS and folded not in _WHOLE_UNITS:
        # 4.5 eggs or 1.5 tins make no sense on a shopping list.
        return str(max(-(-value.numerator // value.denominator), 1))
    if folded in _WHOLE_UNITS:
        number = round(value)
        if number >= 100:
            number = int(round(number / 5) * 5)
        return str(max(number, 1))
    # Halves and quarters are common on recipe cards.
    rounded = Fraction(round(value * 4), 4)
    if rounded == 0:
        rounded = Fraction(1, 4)
    whole, rest = divmod(rounded, 1)
    symbols = {Fraction(1, 4): "¼", Fraction(1, 2): "½", Fraction(3, 4): "¾"}
    if rest == 0:
        return str(int(whole))
    return (str(int(whole)) if whole else "") + symbols[rest]


@dataclass(frozen=True, slots=True)
class Ingredient:
    """One ingredient line."""

    title: str
    quantity: Fraction | None = None
    quantity_max: Fraction | None = None
    unit: str | None = None
    note: str | None = None  # free-text amount that cannot be scaled

    def amount(self, factor: Fraction = Fraction(1)) -> str:
        """Amount text for the shopping list, scaled by factor."""
        if self.quantity is None:
            return self.note or ""
        scaled = factor != 1
        text = _format_number(self.quantity * factor, self.unit, scaled)
        if self.quantity_max is not None:
            upper = _format_number(self.quantity_max * factor, self.unit, scaled)
            if upper != text:
                text += "–" + upper
        if not self.unit:
            return text
        return f"{text} {_inflect(self.unit, text)}"

    def as_dict(self, factor: Fraction = Fraction(1)) -> dict[str, Any]:
        """Serialisable representation."""
        return {"item": self.title, "amount": self.amount(factor)}


def parse_ingredient(line: str) -> Ingredient | None:
    """Parse one line of a recipe; None for empty lines and comments."""
    text = line.strip().lstrip("-•*·").strip()
    if not text or text.startswith("#"):
        return None
    for symbol, replacement in _VULGAR.items():
        text = re.sub(rf"(\d)\s*{symbol}", rf"\1 {replacement}", text)
        text = text.replace(symbol, replacement)
    if "|" in text:
        title, _, amount = text.partition("|")
        title = title.strip()
        parsed = parse_ingredient(f"{amount.strip()} {title}") if amount.strip() else None
        if parsed is not None and parsed.quantity is not None and parsed.title == title:
            return parsed
        return Ingredient(title=title, note=amount.strip() or None) if title else None
    match = _LINE_RE.match(text)
    if match and match.group("title").strip():
        parts = re.split(r"\s*[-–]\s*", match.group("qty"), maxsplit=1)
        low = parts[0]
        high = parts[1] if len(parts) > 1 else ""
        try:
            quantity = _to_fraction(low)
            quantity_max = _to_fraction(high) if high else None
        except (ValueError, ZeroDivisionError):
            return Ingredient(title=text)
        unit = match.group("unit")
        return Ingredient(
            title=match.group("title").strip(),
            quantity=quantity,
            quantity_max=quantity_max,
            unit=unit.rstrip(".") if unit else None,
        )
    return Ingredient(title=text)


def parse_ingredients(text: str) -> list[Ingredient]:
    """Parse all lines of a recipe."""
    return [ing for line in text.splitlines() if (ing := parse_ingredient(line))]


@dataclass(frozen=True, slots=True)
class Recipe:
    """A stored recipe."""

    id: str
    name: str
    aliases: tuple[str, ...]
    portions: int
    ingredients: tuple[Ingredient, ...]

    @classmethod
    def from_data(cls, recipe_id: str, data: Mapping[str, Any]) -> Recipe:
        """Create a recipe from subentry data."""
        aliases = tuple(
            alias.strip()
            for alias in str(data.get(CONF_RECIPE_ALIASES) or "").split(",")
            if alias.strip()
        )
        return cls(
            id=recipe_id,
            name=str(data[CONF_RECIPE_NAME]).strip(),
            aliases=aliases,
            portions=max(int(data.get(CONF_RECIPE_PORTIONS) or DEFAULT_PORTIONS), 1),
            ingredients=tuple(parse_ingredients(str(data.get(CONF_RECIPE_INGREDIENTS) or ""))),
        )

    def factor(self, portions: int | None) -> Fraction:
        """Scaling factor for the requested portions."""
        if not portions or portions <= 0:
            return Fraction(1)
        return Fraction(portions, self.portions)

    def names(self) -> tuple[str, ...]:
        """Name and aliases."""
        return (self.name, *self.aliases)


def find_recipe(recipes: Iterable[Recipe], query: str) -> Recipe | None:
    """Find a recipe by name or alias (exact, then partial match)."""
    wanted = normalize(query)
    if not wanted:
        return None
    recipes = list(recipes)
    for recipe in recipes:
        if any(normalize(name) == wanted for name in recipe.names()):
            return recipe
    for recipe in recipes:
        if any(wanted in normalize(name) or normalize(name) in wanted for name in recipe.names()):
            return recipe
    return None


def _stems(text: str) -> set[str]:
    return {stem(word) for word in tokenize(text)}


def matches_exclusion(title: str, exclusion: str) -> bool:
    """True if an excluded item ("Tomaten") covers an ingredient title.

    Every word of the exclusion must appear in the ingredient (plural
    tolerant), so "Tomaten" excludes "stückige Tomaten" but not "Tomatenmark".
    """
    wanted = _stems(exclusion)
    if not wanted:
        return False
    have = _stems(title)
    return normalize(title) == normalize(exclusion) or all(
        any(word == other or (len(word) >= 4 and other.endswith(word)) for other in have)
        for word in wanted
    )


def split_exclusions(
    ingredients: Iterable[Ingredient], exclusions: Iterable[str]
) -> tuple[list[Ingredient], list[Ingredient], list[str]]:
    """Return (kept, excluded, exclusions that matched nothing)."""
    exclusions = [e for e in exclusions if e and e.strip()]
    kept: list[Ingredient] = []
    excluded: list[Ingredient] = []
    used: set[str] = set()
    for ingredient in ingredients:
        hit = next((e for e in exclusions if matches_exclusion(ingredient.title, e)), None)
        if hit is None:
            kept.append(ingredient)
        else:
            excluded.append(ingredient)
            used.add(hit)
    return kept, excluded, [e for e in exclusions if e not in used]
