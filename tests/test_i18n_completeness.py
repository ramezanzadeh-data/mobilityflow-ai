"""
Guards the user-visible text layer.

i18n.translator.t() resolves a missing key by returning the key itself
(``translations.get(key, key)``). That fallback never raises and never
logs, so a key that was added to a page but not to the translation file
reaches production silently and renders as raw source text:

    ai_operator_header
    run_ai_operator_button
    progress_label: 14%

Seventeen keys were in exactly that state and shipped to a customer-facing
screenshot. Nothing in the 144-test suite could see it, because nothing
else covers the presentation layer.

These tests close that gap at the cheapest possible point: they read the
same source files the UI runs from, so a missing key fails here instead of
appearing in the interface.

Scope note: this deliberately checks *key existence and quality*, not
translation correctness. Verifying that the German for "Risk Score" is
right is a human review task; verifying that a German string exists at all
is a machine task, and this is the machine part.
"""

import ast
import json
from pathlib import Path

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

TRANSLATIONS_DIR = REPOSITORY_ROOT / "i18n" / "translations"

# Directories whose modules render the UI and therefore call t().
UI_SOURCE_DIRS = [REPOSITORY_ROOT / "apps"]

def _python_sources():

    for directory in UI_SOURCE_DIRS:
        for path in sorted(directory.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            yield path


def _translation_calls(path):
    """
    Yield every ``t(...)`` call in a file as ``(node, first_argument)``.

    Parsed rather than pattern-matched. A line-based regex also matches
    ``t("...")`` written inside a comment or a docstring, which produced
    two false failures while this suite was being written: a comment
    explaining why a key must not be built dynamically was itself reported
    as building one. The parser sees code only.
    """

    tree = ast.parse(path.read_text(encoding="utf-8"))

    for node in ast.walk(tree):

        if not isinstance(node, ast.Call):
            continue

        if getattr(node.func, "id", None) != "t":
            continue

        yield node, (node.args[0] if node.args else None)


def _referenced_keys():
    """Every translation key the UI asks for, mapped to where it is used."""

    usages = {}

    for path in _python_sources():
        for node, first_argument in _translation_calls(path):

            if not (
                isinstance(first_argument, ast.Constant)
                and isinstance(first_argument.value, str)
            ):
                # Non-literal keys are reported by
                # test_no_dynamic_translation_keys instead.
                continue

            location = f"{path.relative_to(REPOSITORY_ROOT)}:{node.lineno}"
            usages.setdefault(first_argument.value, []).append(location)

    return usages


def _translation_files():

    files = sorted(TRANSLATIONS_DIR.glob("*.json"))

    assert files, f"No translation files found in {TRANSLATIONS_DIR}"

    return files


def _load(path):

    return json.loads(path.read_text(encoding="utf-8"))


def test_every_referenced_key_exists_in_the_reference_language():
    """
    The regression this file exists for: seventeen keys were referenced
    by the UI and defined nowhere, so the interface rendered
    ``ai_operator_header`` at a customer.

    Bound to English only, deliberately.

    English is the last link in i18n.translator's fallback chain - a key
    missing *there* has nothing left to fall back to and reaches the user
    as raw source text. A key missing from German falls back to English,
    which is a gap rather than a defect, and is measured by
    test_translation_coverage_meets_its_floor instead.

    Requiring every language to define every key would mean a language
    could never be started: the first commit of de.json would fail the
    suite. That is exactly the pressure that produces either a stalled
    translation effort or a lowered guard, and neither is worth having.
    """

    reference = TRANSLATIONS_DIR / "en.json"

    assert reference.is_file(), "en.json is the fallback language and must exist"

    available = set(_load(reference))

    missing = {
        key: locations
        for key, locations in sorted(_referenced_keys().items())
        if key not in available
    }

    assert not missing, (
        f"{len(missing)} translation key(s) referenced by the UI are absent "
        f"from en.json. English is the end of the fallback chain, so t() "
        f"would render the raw key to the user:\n"
        + "\n".join(
            f"  {key}  (used at {', '.join(locations)})"
            for key, locations in missing.items()
        )
    )


@pytest.mark.parametrize(
    "translation_file",
    _translation_files(),
    ids=lambda p: p.stem,
)
def test_no_blank_translations(translation_file):
    """
    An empty or whitespace-only value passes an existence check but still
    renders as a blank label, which reads as a broken screen.
    """

    blank = sorted(
        key
        for key, value in _load(translation_file).items()
        if not isinstance(value, str) or not value.strip()
    )

    assert not blank, (
        f"Empty translation value(s) in {translation_file.name}: {blank}"
    )


@pytest.mark.parametrize(
    "translation_file",
    _translation_files(),
    ids=lambda p: p.stem,
)
def test_no_translation_value_is_just_its_own_key(translation_file):
    """
    Catches the placeholder shortcut `"some_key": "some_key"`, which
    reproduces exactly the defect this suite is meant to prevent while
    appearing to satisfy the existence check above.
    """

    placeholders = sorted(
        key
        for key, value in _load(translation_file).items()
        if isinstance(value, str) and value.strip() == key
    )

    assert not placeholders, (
        f"Translation value is identical to its key in "
        f"{translation_file.name} — the user would see raw source text: "
        f"{placeholders}"
    )


def test_no_language_defines_a_key_english_does_not():
    """
    A key present in German but not English is a typo, not a feature.

    English is the fallback for every other language, so such a key can
    never be reached through t(): the lookup finds it, but no call site
    asks for it because the call sites were written against English. It
    is dead weight that looks like coverage.

    Note this is asymmetric on purpose. The reverse - English keys a
    language has not translated yet - is expected and is measured by
    test_translation_coverage_is_reported below, not failed here. A
    fallback chain exists precisely so a language can ship incomplete;
    requiring parity would mean no language could ever be started.
    """

    files = _translation_files()

    if len(files) == 1:
        pytest.skip("Only one language is shipped; nothing to compare yet.")

    by_language = {path.stem: set(_load(path)) for path in files}

    reference_language = "en"

    assert reference_language in by_language, (
        f"Expected {reference_language}.json to exist as the reference "
        f"language; found {sorted(by_language)}"
    )

    reference_keys = by_language[reference_language]

    differences = {}

    for language, keys in by_language.items():
        if language == reference_language:
            continue

        extra = sorted(keys - reference_keys)

        if extra:
            differences[language] = {"missing": [], "unknown": extra}

    assert not differences, (
        "Translation files define keys that "
        f"{reference_language}.json does not:\n"
        + "\n".join(
            f"  {language}: unknown={detail['unknown']}"
            for language, detail in differences.items()
        )
    )


# Ratchet. Raise these as translation work lands; never lower one. A
# language below its floor has regressed, which is the case worth
# failing on - an incomplete language is expected, a shrinking one is a
# mistake.
MINIMUM_COVERAGE = {
    "en": 100,
    "de": 30,
    "fr": 30,
}


@pytest.mark.parametrize(
    "translation_file",
    _translation_files(),
    ids=lambda p: p.stem,
)
def test_translation_coverage_meets_its_floor(translation_file):
    """
    Measures how much of the interface exists in each language.

    Coverage is a quality target rather than a crash risk, because
    i18n.translator falls back to English before it falls back to the
    key. A German user meeting an English sentence sees a product with a
    gap; before that fallback existed they would have seen
    ``obligations_header``, which looks broken.
    """

    from i18n.translator import clear_cache, translation_coverage

    clear_cache()

    language = translation_file.stem
    translated, total, missing = translation_coverage(language)

    percent = round(translated * 100 / total) if total else 0
    floor = MINIMUM_COVERAGE.get(language, 0)

    assert percent >= floor, (
        f"{language}: {percent}% translated ({translated}/{total}), below "
        f"its floor of {floor}%. {len(missing)} keys missing, first few: "
        f"{missing[:5]}"
    )


def test_every_supported_language_has_a_file():
    """
    A language offered in the selector but with no file would fall back
    to English for every string - the selector would appear to do
    nothing, which reads as a broken control rather than a missing
    translation.
    """

    from i18n.translator import SUPPORTED_LANGUAGES

    shipped = {path.stem for path in _translation_files()}

    missing = sorted(set(SUPPORTED_LANGUAGES) - shipped)

    assert not missing, (
        f"Languages offered in the selector with no translation file: "
        f"{missing}"
    )


def test_no_dynamic_translation_keys():
    """
    Keeps the static check above meaningful.

    `t(some_variable)` cannot be verified without running the page, so it
    is a hole in this suite's coverage. Rather than let such call sites
    accumulate unnoticed, they are failed here: build the key at the call
    site (`t("prefix_" ...)` is still fine) or add an explicit exemption
    with a comment explaining why it cannot be static.
    """

    dynamic = []

    for path in _python_sources():
        for node, first_argument in _translation_calls(path):

            if isinstance(first_argument, ast.Constant) and isinstance(
                first_argument.value, str
            ):
                continue

            dynamic.append(
                f"  {path.relative_to(REPOSITORY_ROOT)}:{node.lineno}: "
                f"t({ast.unparse(first_argument) if first_argument else ''})"
            )

    assert not dynamic, (
        "Translation key built from a variable - it cannot be checked "
        "statically, so a missing key would reach the UI:\n"
        + "\n".join(dynamic)
    )
