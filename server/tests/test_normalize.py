import pytest

from xxvi.normalize import normalize_answer

# --- The normaliser decides whether a correct answer is accepted at
# midnight, on a run that cannot be patched. Every case below is a
# character class the brief calls out by name: case differences, internal
# spaces, hyphens, punctuation, leading/trailing whitespace, an empty
# submission, and a submission that is only punctuation.
CASES = [
    ("gta4", "gta4", "already normalised"),
    ("GTA4", "gta4", "case difference"),
    ("gta 4", "gta4", "internal space"),
    ("GTA 4", "gta4", "case difference + internal space"),
    ("GTA-4", "gta4", "hyphen"),
    ("gta-4", "gta4", "hyphen, lowercase"),
    ("GTA_4", "gta4", "underscore"),
    ("gta4!", "gta4", "trailing punctuation"),
    ("g.t.a.4", "gta4", "internal punctuation"),
    ("  gta4  ", "gta4", "leading and trailing whitespace"),
    ("\tgta4\n", "gta4", "leading/trailing whitespace, tab and newline"),
    ("", "", "empty submission"),
    ("   ", "", "whitespace-only submission"),
    ("!!!", "", "punctuation-only submission"),
    ("---...???", "", "punctuation-only submission, mixed marks"),
]


@pytest.mark.parametrize("raw,expected,label", CASES, ids=[c[2] for c in CASES])
def test_normalize_answer_cases(raw, expected, label):
    assert normalize_answer(raw) == expected


def test_normalize_is_used_identically_on_both_sides_of_a_comparison():
    # accept exists for what normalisation cannot do -- "gtaiv" and "gta4"
    # are genuinely different strings even after normalisation, so both
    # would need listing. This pins that normalising both a submission and
    # an accept-list entry the same way is what makes the comparison work.
    submission = "  GTA-4 "
    accept = ["gta4", "gtaiv"]
    assert normalize_answer(submission) in {normalize_answer(a) for a in accept}


def test_normalize_does_not_collapse_genuinely_different_spellings():
    assert normalize_answer("gtaiv") != normalize_answer("gta4")


def test_normalize_never_raises_on_pure_punctuation_or_empty_input():
    # Must be total: any str in, a str out, never an exception. A raise here
    # would turn a legitimate (if wrong) player submission into a 500 at
    # midnight instead of a graceful "incorrect".
    for value in ("", "   ", "!!!", "\t\n", "-_.,;:!?"):
        assert normalize_answer(value) == ""


# --- Accent folding. Content is hand-authored and may contain accented
# characters (e.g. a question whose real accept entry is "café"); a player
# typing on a keyboard without easy accent access types "cafe" and must
# still be accepted. NFKD decomposition + dropping combining marks, not
# deleting the accented character outright -- deletion would fold "café"
# to "caf" (dropping the e entirely), which a plain "cafe" submission
# would never match.
ACCENT_CASES = [
    ("café", "cafe", "acute accent"),
    ("CAFÉ", "cafe", "acute accent, uppercase"),
    ("cafe", "cafe", "unaccented, must match the accented entry after folding"),
    ("naïve", "naive", "diaeresis"),
    ("crème brûlée", "cremebrulee", "multiple accents plus a space"),
    ("Ångström", "angstrom", "ring above"),
    ("São Paulo", "saopaulo", "tilde"),
]


@pytest.mark.parametrize("raw,expected,label", ACCENT_CASES, ids=[c[2] for c in ACCENT_CASES])
def test_normalize_folds_accents_by_decomposition_not_deletion(raw, expected, label):
    assert normalize_answer(raw) == expected


def test_an_accented_accept_entry_matches_an_unaccented_submission():
    # The concrete failure mode this closes: accept=["café"], player types
    # "cafe" -- must be accepted, not silently rejected because deletion
    # (rather than folding) turned the accept entry into "caf".
    accept = ["café"]
    submission = "cafe"
    assert normalize_answer(submission) in {normalize_answer(a) for a in accept}
