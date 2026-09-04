import re
import unicodedata

# Every character that survives normalisation: letters and digits. Anything
# else (spaces, hyphens, punctuation) is stripped.
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize_answer(text: str) -> str:
    """Normalise a free-text answer for comparison against `Question.accept`.

    Folds accents/diacritics off, lowercases, and strips every
    non-alphanumeric character, so `"GTA-4"`, `"gta 4"`, `"GTA 4"`, and
    (for a question whose `accept` list contains an accented entry)
    `"café"` vs. `"cafe"` all normalise to the same string.

    Accent folding is NFKD decomposition (splitting each accented character
    into a base letter plus a combining mark) followed by dropping every
    combining mark, NOT deletion of the accented character outright --
    deleting `"é"` wholesale would normalise `"café"` to `"caf"`, which
    would then never match a player typing the unaccented `"cafe"` (which
    normalises to `"cafe"`). Content is hand-authored and may include
    accented characters the person writing it typed correctly; a player
    typing on a keyboard without easy accent access must not be penalised
    for it.

    This is deliberately used on *both* sides of the comparison -- the
    player's submission and every string in `Question.accept` -- so the two
    can be compared with plain equality. It decides whether a correct answer
    is accepted at midnight, on a run that cannot be patched, so keep it
    simple and total: any `str` in, including an empty string or a string
    that is only punctuation, produces a `str` out (possibly `""`), never
    raises.

    `accept` exists for what this normalisation cannot do: `"gtaiv"` and
    `"gta4"` are genuinely different strings after normalisation, so both
    must be listed in `accept` when both spellings should pass.
    """
    decomposed = unicodedata.normalize("NFKD", text)
    without_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return _NON_ALNUM.sub("", without_accents.lower())
