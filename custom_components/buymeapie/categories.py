"""Category ontology and automatic categorisation for Buy Me a Pie.

Buy Me a Pie only knows colour numbers (``group_id``); the meaning lives in
the user's head. The defaults below were derived from a real account's
history: every colour stands for an area of the supermarket and the app
shows them in the order 7, 6, 5, 4, 3, 2, 1, 8...28, 0, which matches a walk
through the shop (chilled shelf first, freezer last).

A category is attached to an item *title* (the account wide "unique item"),
not to a single list entry. New titles are categorised in this order:

1. exact title in the user's history  -> the user's own choice
2. keyword ontology below              -> German supermarket knowledge
3. similar titles in the history       -> the user's habits (compound words)
4. otherwise colour 0 (no colour)
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import math
import re
from typing import Final

# Order in which the app shows the colour groups.
APP_ORDER: Final[tuple[int, ...]] = (7, 6, 5, 4, 3, 2, 1, *range(8, 29), 0)
_ORDER_INDEX: Final = {group: index for index, group in enumerate(APP_ORDER)}
MAX_GROUP_ID: Final = 28


@dataclass(frozen=True, slots=True)
class Category:
    """One colour group."""

    id: int
    name: str
    color: str
    description: str


DEFAULT_CATEGORIES: Final[dict[int, Category]] = {
    7: Category(7, "🧀 Kühlregal & Molkerei", "#26B0C7",
                "Milch, Butter, Eier, Käse, Joghurt, frische Pasta, Feinkostsalate"),
    6: Category(6, "🥦 Obst & Gemüse", "#75B35A",
                "Frisches Obst und Gemüse, frische Kräuter"),
    5: Category(5, "🥓 Fleisch & Wurst", "#FF5699",
                "Abgepacktes Fleisch, Hack, Geflügel, Wurst, Schinken, Bacon"),
    4: Category(4, "🥫 Vorrat, Brot & Getränke", "#E57542",
                "Brot, Nudeln, Reis, Mehl, Konserven, Saucen, Gewürze, Süßes, Getränke"),
    3: Category(3, "🥩 Frischetheke", "#BA2E38",
                "Fleisch- und Wursttheke: Filets, Lachsschinken, Lyoner, Fleischsalat"),
    2: Category(2, "🥐 Bäckerei", "#864F9E",
                "Brötchen und Backwaren vom Bäcker"),
    1: Category(1, "🧊 Tiefkühl", "#524DCF",
                "Tiefkühlware: Fisch, Pizza, Pommes, Gemüse, Eis"),
    0: Category(0, "🧻 Drogerie, Haushalt & Sonstiges", "#B4BEC6",
                "Ohne Farbe: Drogerie, Putzmittel, Papier und alles andere"),
}

_EXTRA_COLORS: Final[dict[int, str]] = {
    8: "#C1C12F", 9: "#20A881", 10: "#8FAECD", 11: "#416362", 12: "#F4B72F",
    13: "#A19080", 14: "#931F54", 15: "#4CC9F5", 16: "#FF2966", 17: "#C4B8CE",
    18: "#9E5E59",
}

# Keyword ontology. Entries are normalised stems (lower case, umlauts
# folded: ä->a, ö->o, ü->u, ß->ss). A stem matches a word that equals it or
# ends with it (German compounds carry their meaning at the end:
# "Hafermilch" -> "milch"), optionally followed by a plural ending. Stems
# prefixed with "=" only match the whole word. On conflicts the longest stem
# wins, so "kokosmilch" beats "milch" and "fleischsalat" beats "salat".
KEYWORDS: Final[dict[int, tuple[str, ...]]] = {
    1: (
        "=tk", "tiefkuhl", "tiefgekuhlt", "gefroren", "eiscreme", "=eis",
        "speiseeis", "wassereis", "eiswurfel", "pommes", "fischstabchen",
        "nugget", "wedges", "kroketten", "rosti", "rostiecken", "schlemmerfilet",
        "gemusepfanne", "pizza", "burgerpatties", "rahmspinat", "lachs", "fisch",
    ),
    2: (
        "brotchen", "semmel", "schrippe", "croissant", "berliner", "krapfen",
        "plunder", "teilchen",
    ),
    3: (
        "theke", "fleischsalat", "lachsschinken", "parmaschinken", "serrano",
        "prosciutto", "lyoner", "leberpastete", "frikadelle", "kalbsfilet",
        "schweinefilet", "rinderfilet", "rumpsteak", "roastbeef", "pancetta",
    ),
    4: (
        "brot", "toast", "baguette", "buns", "hamburgerbrotchen", "burgerbrotchen",
        "milchbrotchen", "aufbackbrotchen", "brezel", "kuchen", "torte", "muffin",
        "waffel", "grissini", "smarties", "maggi", "tonic", "kokos", "peperoni",
        "artischocke", "eintopf", "nudeltopf", "paste", "pulver", "mandelblattchen",
        "gewurzmischung", "kochsahne", "getrocknete tomate", "wrap", "tortilla", "zwieback", "knackebrot",
        "nudel", "spaghetti", "penne", "fusilli", "rigatoni", "farfalle",
        "spatzle", "couscous", "reis", "risotto", "mehl", "zucker", "salz",
        "pfeffer", "gewurz", "paprika edelsuss", "curry", "zimt", "oregano",
        "bruhe", "bouillon", "fond", "suppe", "konserve", "=dose", "tomatenmark",
        "passata", "stuckige tomate", "passierte tomate", "mais", "linse",
        "bohne", "kichererbse", "olive", "gewurzgurke", "cornichon", "=ol",
        "olivenol", "rapsol", "sonnenblumenol", "essig", "balsamico", "senf",
        "ketchup", "mayo", "mayonnaise", "remoulade", "sauce", "sosse", "pesto",
        "honig", "marmelade", "konfiture", "gelee", "nutella", "aufstrich",
        "erdnussbutter", "mus", "musli", "haferflocke", "flocken", "cornflakes",
        "kaffee", "espresso", "tee", "kakao", "saft", "schorle", "wasser",
        "sprudel", "limo", "limonade", "cola", "bier", "radler", "wein", "sekt",
        "gin", "rum", "chips", "cracker", "keks", "schokolade", "praline",
        "gummibarchen", "haribo", "nuss", "nusse", "mandel", "rosine",
        "pinienkerne", "kerne", "samen", "trockenhefe", "backpulver",
        "vanillezucker", "puderzucker", "speisestarke", "kokosmilch", "datteln",
        "popcorn", "nachos", "brei", "glaschen", "mark", "bratol",
    ),
    5: (
        "wurst", "hack", "hackfleisch", "fleisch", "hahnchen", "huhn", "geflugel",
        "pute", "puten", "bacon", "speck", "schinken", "salami", "steak",
        "schnitzel", "kotelett", "gulasch", "geschnetzeltes", "mett", "mettenden",
        "rind", "schwein", "lamm", "aufschnitt", "brust", "filet", "speckwurfel",
        "baconwurfel", "baconscheibe",
    ),
    6: (
        "obst", "gemuse", "apfel", "birne", "banane", "orange", "mandarine",
        "clementine", "zitrone", "limette", "traube", "beere", "kirsche",
        "pfirsich", "nektarine", "pflaume", "melone", "ananas", "mango", "kiwi",
        "feige", "avocado", "tomate", "gurke", "paprika", "zucchini", "aubergine",
        "mohre", "karotte", "kartoffel", "drillinge", "zwiebel", "knoblauch",
        "lauch", "porree", "salat", "rucola", "spinat", "kohl", "kohlrabi",
        "brokkoli", "sellerie", "fenchel", "pastinake", "kurbis", "pilz",
        "champignon", "rettich", "radieschen", "ingwer", "basilikum",
        "petersilie", "schnittlauch", "dill", "minze", "koriander", "rosmarin",
        "salbei", "kresse", "schalotte", "suppengrun", "sprossen", "mangold",
        "zuckerschote", "chili", "zitronengras", "salatkopf", "wurzel",
        "maiskolben", "majoran",
    ),
    7: (
        "milch", "butter", "kase", "joghurt", "jogurt", "quark", "sahne",
        "schmand", "creme fraiche", "fraiche", "sour cream", "mozzarella",
        "parmesan", "feta", "gouda", "camembert", "brie", "gorgonzola",
        "mascarpone", "ricotta", "cheddar", "emmentaler", "burrata", "skyr",
        "kefir", "margarine", "=ei", "=eier", "tortellini", "gnocchi",
        "maultasche", "lasagneplatten", "blatterteig", "hefeteig",
        "flammkuchenteig", "frische hefe", "eiersalat", "kartoffelsalat",
        "nudelsalat", "farmersalat", "krautsalat", "coleslaw", "tzatziki",
        "aioli", "=dip", "dressing", "wurstchen", "leberkase", "pudding",
        "bresso", "milram", "fetawurfel", "burgersauce", "knack und back",
    ),
    0: (
        "papier", "klopapier", "kuchenrolle", "taschentuch", "taschentucher",
        "tucher", "tabs", "spulmittel", "spuli", "reiniger", "waschmittel",
        "waschpulver", "weichspuler", "schwamm", "handschuh", "beutel", "sacke",
        "folie", "shampoo", "duschgel", "seife", "zahnpasta", "zahnburste",
        "zahnseide", "deo", "deodorant", "handcreme", "sonnencreme", "watte", "wattepads",
        "wattestabchen", "qtip", "qtipps", "windel", "feuchttucher", "pflaster",
        "rasierer", "mundspulung", "hygienespuler", "batterie", "gluhbirne",
        "kerze", "teelicht", "serviette", "pappteller", "besteck", "blume",
        "tulpe", "grillkohle", "=kohle", "anzunder", "zeitschrift", "mascara",
        "kajal", "make up", "makeup", "tabletten", "vitamin", "paracetamol",
    ),
}

_STOPWORDS: Final = frozenset(
    {
        "bio", "frisch", "frische", "frischer", "frisches", "klein", "kleine",
        "kleines", "kleiner", "gross", "grosse", "grosses", "mini", "mild",
        "milder", "fein", "feine", "feines", "rewe", "edeka", "aldi", "lidl",
        "penny", "netto", "kaufland", "beste", "wahl", "von", "fur", "zum",
        "zur", "mit", "und", "oder", "der", "die", "das", "den", "dem", "ein",
        "eine", "aus", "im", "in", "am", "nicht", "keine", "kein", "scheiben",
        "stuck", "packung", "pack", "glas", "becher", "flasche", "kasten",
        "kiste", "art", "typ", "gr", "auch",
    }
)

_UMLAUTS: Final = str.maketrans({"ä": "a", "ö": "o", "ü": "u", "ß": "ss", "é": "e",
                                 "è": "e", "ê": "e", "à": "a", "â": "a", "ø": "o",
                                 "å": "a", "ç": "c", "ñ": "n"})
_PLURAL_SUFFIXES: Final = ("", "n", "en", "e", "s", "er", "nen")


def normalize(text: str) -> str:
    """Lower-case, fold umlauts and keep letters and spaces only."""
    text = text.casefold().translate(_UMLAUTS)
    text = text.replace("-", "").replace("&", " ")
    return re.sub(r"[^a-z]+", " ", text).strip()


def tokenize(text: str) -> list[str]:
    """Split a title into meaningful words."""
    return [
        word
        for word in normalize(text).split()
        if word not in _STOPWORDS and (len(word) >= 3 or word in ("tk", "ei", "ol"))
    ]


def stem(word: str) -> str:
    """Very light German stemming (plural endings)."""
    for suffix in ("nen", "en", "er", "n", "e", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[: -len(suffix)]
    return word


def _keyword_match(words: list[str], phrase: str, keyword: str) -> bool:
    exact = keyword.startswith("=")
    keyword = keyword.lstrip("=")
    if " " in keyword:
        return keyword in phrase
    for word in words:
        for suffix in _PLURAL_SUFFIXES:
            candidate = keyword + suffix
            if word == candidate or (not exact and word.endswith(candidate)):
                return True
    return False


def keyword_category(title: str) -> tuple[int, str] | None:
    """Return (group_id, matched keyword) from the built-in ontology."""
    words = tokenize(title)
    if not words:
        return None
    phrase = " ".join(words)
    # Frozen food markers override everything else ("TK Himbeeren").
    if "tk" in words or any("tiefkuhl" in word or "tiefgekuhlt" in word for word in words):
        return 1, "tk"
    best: tuple[int, str] | None = None
    for group_id, keywords in KEYWORDS.items():
        for keyword in keywords:
            if not _keyword_match(words, phrase, keyword):
                continue
            plain = keyword.lstrip("=")
            if best is None or len(plain) > len(best[1]):
                best = (group_id, plain)
    return best


@dataclass(frozen=True, slots=True)
class Suggestion:
    """Result of the categorisation."""

    group_id: int
    source: str  # "history", "similar", "keyword" or "default"
    reason: str | None = None


class CategoryClassifier:
    """Suggests a colour group for an item title."""

    def __init__(self, history: Iterable[tuple[str, int, int]]) -> None:
        """Build the classifier from (title, group_id, use_count) entries."""
        self._exact: dict[str, int] = {}
        self._exact_folded: dict[str, int] = {}
        self._entries: list[tuple[tuple[str, ...], int, float, str]] = []
        for title, group_id, use_count in history:
            self._exact[title] = group_id
            self._exact_folded.setdefault(normalize(title), group_id)
            if group_id == 0:
                # Colour 0 is also "not categorised yet"; do not learn from it.
                continue
            stems = tuple(stem(word) for word in tokenize(title))
            if stems:
                weight = 1.0 + math.log1p(max(use_count, 0))
                self._entries.append((stems, group_id, weight, title))

    def known_group(self, title: str) -> int | None:
        """Return the group the user already assigned to this title."""
        if title in self._exact:
            return self._exact[title]
        return self._exact_folded.get(normalize(title))

    def _similar(self, title: str) -> tuple[int, float, float, str] | None:
        stems = [stem(word) for word in tokenize(title)]
        if not stems:
            return None
        scores: dict[int, float] = {}
        best_example: dict[int, tuple[float, str]] = {}
        frozen = "tk" in stems
        for entry_stems, group_id, weight, example in self._entries:
            match = 0.0
            for word in stems:
                for other in entry_stems:
                    if word == other:
                        value = 1.0
                    elif len(other) >= 4 and word.endswith(other):
                        value = 0.8  # new compound ends with a known item
                    elif len(word) >= 4 and other.endswith(word):
                        value = 0.4  # known compound ends with the new word
                    else:
                        continue
                    if other == "tk" and not frozen:
                        continue
                    match = max(match, value)
            if match:
                score = match * weight
                scores[group_id] = scores.get(group_id, 0.0) + score
                if score > best_example.get(group_id, (0.0, ""))[0]:
                    best_example[group_id] = (score, example)
        if not scores:
            return None
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        best_group, best_score = ranked[0]
        second = ranked[1][1] if len(ranked) > 1 else 0.0
        return best_group, best_score, second, best_example[best_group][1]

    def suggest(self, title: str) -> Suggestion:
        """Suggest a group for a (new) title.

        Measured on a real history (leave-one-out, ~400 titles) the keyword
        ontology is more precise than similarity to other titles, so it is
        consulted first; similarity covers what the keywords do not know.
        """
        known = self.known_group(title)
        if known is not None:
            return Suggestion(known, "history", title)

        keyword = keyword_category(title)
        if keyword is not None:
            return Suggestion(keyword[0], "keyword", keyword[1])

        similar = self._similar(title)
        if similar is not None and similar[1] >= 1.0:
            return Suggestion(similar[0], "similar", similar[3])

        return Suggestion(0, "default", None)


def order_index(group_id: int) -> int:
    """Position of a group in the app's display order."""
    return _ORDER_INDEX.get(group_id, len(APP_ORDER))


def category_name(group_id: int, overrides: Mapping[int, str] | None = None) -> str:
    """Display name for a group (user override, default, or 'Farbe N')."""
    if overrides and overrides.get(group_id):
        return overrides[group_id]
    if group_id in DEFAULT_CATEGORIES:
        return DEFAULT_CATEGORIES[group_id].name
    return f"Farbe {group_id}"


def category_color(group_id: int) -> str | None:
    """Hex colour the app uses for a group."""
    if group_id in DEFAULT_CATEGORIES:
        return DEFAULT_CATEGORIES[group_id].color
    return _EXTRA_COLORS.get(group_id)


def resolve_category(value: str | int, overrides: Mapping[int, str] | None = None) -> int | None:
    """Turn a user input (number or (part of a) name) into a group id."""
    if isinstance(value, int) or str(value).strip().isdigit():
        group_id = int(value)
        return group_id if 0 <= group_id <= MAX_GROUP_ID else None
    wanted = normalize(str(value))
    if not wanted:
        return None
    names = {group_id: category_name(group_id, overrides) for group_id in APP_ORDER}
    for group_id, name in names.items():
        if normalize(name) == wanted:
            return group_id
    for group_id, name in names.items():
        if wanted in normalize(name):
            return group_id
    return None
