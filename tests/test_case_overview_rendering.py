"""
Three defects visible on one screenshot of the case page.

Reported by screenshot, which is worth noting: none of them raised an
error, none broke a test, and the page rendered happily with all three
present. They are the kind that only a person looking at the screen
finds.

1. Every stepper label was drawn underneath its own marker - "Draft"
   showed as "t", "Submitted" as "Sub(dot)itted". The marker sat outside
   the flow at position:absolute and the label was pushed clear of it by
   a padding that had to be kept larger than the marker by hand. It was
   not: marker 16px + 2px border each side = 22px, plus a 4px focus ring
   on the current step = 26px, against 24px of padding.

2. "1 of 4 factors reflect a documented administrative step" - plural
   verb, singular subject. And the same string ended "The rest are
   operational judgement", which is simply false when every factor is
   sourced. A sentence about provenance that is itself wrong undermines
   the thing it was written to establish.

3. The score read 100. The factors totalled 115. The product knew - the
   trace carries was_capped and raw_total - and said so inside a
   collapsed expander, so two cases that are not alike both showed 100
   with nothing on screen to distinguish them.

The CSS tests below are unusual and deliberate. A stylesheet cannot be
asserted against a rendered browser here, but the *relationship* that
broke can be: one number had to stay larger than another, nothing said
so, and it stopped being true. Now something says so.
"""

import re
from pathlib import Path

import pytest


THEME = (
    Path(__file__).resolve().parent.parent
    / "apps" / "web" / "components" / "theme.py"
).read_text(encoding="utf-8")


def _spacing_tokens():
    """The --mf-space-N scale, so declarations can be read in pixels."""

    return {
        name: int(value)
        for name, value in re.findall(
            r"(--mf-space-\d+):\s*(\d+)px", THEME
        )
    }


def _rule(selector):
    """
    The declarations of a single CSS rule, as a dict.

    Comments are stripped before parsing. Left in, a comment preceding a
    declaration is absorbed into that declaration's name - the parser
    splits on ";" and comments contain none - so the property silently
    disappears from the result and the assertion about it fails for a
    reason that has nothing to do with the stylesheet.
    """

    without_comments = re.sub(r"/\*.*?\*/", "", THEME, flags=re.DOTALL)

    pattern = re.escape(selector) + r"\s*\{([^}]*)\}"

    match = re.search(pattern, without_comments)

    assert match, f"{selector} is no longer defined in theme.py"

    declarations = {}

    for line in match.group(1).split(";"):

        if ":" not in line:
            continue

        name, _, value = line.partition(":")
        declarations[name.strip()] = value.strip()

    return declarations


def _first_length(value):
    """
    The first length in a declaration, in pixels.

    Resolves var(--mf-space-N) against the scale, because the stylesheet
    is written in tokens and a test that only understood literal pixels
    would report a missing value as a missing property.
    """

    if not value:
        return None

    token = re.search(r"var\(\s*(--mf-space-\d+)\s*\)", value)

    if token:
        return _spacing_tokens().get(token.group(1))

    literal = re.search(r"(\d+)px", value)

    return int(literal.group(1)) if literal else None


# ------------------------------------------------------- the stepper ---

def test_the_marker_occupies_space_instead_of_floating_over_the_label():
    """
    The defect, at its root.

    While the marker is position:absolute it takes no space, so nothing
    keeps the label below it except a padding somebody has to remember to
    keep large enough. In normal flow the overlap is not possible at all,
    whatever either element's size later becomes.
    """

    marker = _rule(".mf-step__marker")

    assert marker.get("position") != "absolute", (
        "the marker is out of flow again, so the label's clearance is "
        "back to being a hand-maintained padding - which is how every "
        "label came to be drawn underneath its own marker"
    )


def test_the_step_stacks_its_children_rather_than_overlaying_them():

    step = _rule(".mf-step")

    assert step.get("display") == "flex"
    assert step.get("flex-direction") == "column"


def test_the_label_is_not_kept_clear_by_a_hand_maintained_padding():
    """
    Guards against the old approach coming back by way of a padding-top
    large enough to look correct today.
    """

    step = _rule(".mf-step")

    padding_top = step.get("padding-top")

    assert padding_top is None, (
        "padding-top on .mf-step is the mechanism that failed: it has to "
        "exceed the marker's height plus the current step's focus ring, "
        "and no rule anywhere expresses that"
    )


def test_the_connector_line_does_not_take_a_slot_in_the_column():
    """
    .mf-step is a flex container now, and a ::before that is not
    absolutely positioned becomes a flex item - it would appear as a
    stripe above every marker.
    """

    connector = _rule(".mf-step::before")

    assert connector.get("position") == "absolute"


def test_the_connector_meets_the_marker_at_its_centre():
    """
    The line is drawn across the whole step at a fixed offset, so that
    offset has to equal the marker's centre or the track runs visibly
    above or below the dots.

    Centre = the step's top padding + half the marker's outer height,
    where outer height is the content box plus both borders.
    """

    step = _rule(".mf-step")
    marker = _rule(".mf-step__marker")
    connector = _rule(".mf-step::before")

    padding_top = _first_length(step.get("padding"))

    height = _first_length(marker.get("height"))
    border = _first_length(marker.get("border"))

    assert padding_top is not None, "the step's top padding is unreadable"
    assert height is not None and border is not None

    centre = padding_top + (height + 2 * border) // 2

    assert _first_length(connector.get("top")) == centre, (
        f"the connector sits at {connector.get('top')}, but the marker's "
        f"centre is at {centre}px - the track will run above or below the "
        f"dots instead of through them"
    )


def test_the_marker_is_drawn_over_the_connector_not_under_it():

    assert "z-index" in _rule(".mf-step__marker")


# -------------------------------------------------- the case identity ---

def test_the_employee_name_is_larger_than_the_labels_around_it():
    """
    It was st.caption("Employee · {name}") - 12px muted, the smallest
    text on the page and smaller than the word "NATIONALITY" on the card
    below it. The person the whole file is about was rendered as an aside
    while the labels of their attributes shouted.

    The name is the page title now, so the comparison moved with it: an
    h1 against the field labels beneath it. The property being held down
    is the same one, and it is the one that keeps getting lost - twice so
    far, each time while moving the name somewhere better.

    Asserted as a relationship rather than a fixed size, so the type
    scale can change without this becoming a maintenance chore that gets
    deleted.
    """

    label = _rule(".mf-field__label")
    name = _rule(".mf-page__title")

    scale = {
        token: int(size)
        for token, size in re.findall(r"(--mf-text-[a-z0-9]+):\s*(\d+)px", THEME)
    }

    def size_of(declarations):
        """
        A font-size in pixels, however it is written.

        Both forms occur in this stylesheet: the type scale as
        var(--mf-text-*), and a literal px where a size sits outside the
        scale on purpose - .mf-field__label is 11px, smaller than the
        smallest scale step, because it is a label rather than text.
        Reading only one form made this comparison silently unmeasurable
        rather than failing.
        """

        declared = declarations.get("font-size", "")

        token = re.search(r"var\(\s*(--mf-text-[a-z0-9]+)\s*\)", declared)

        if token:
            return scale.get(token.group(1))

        literal = re.search(r"(\d+)px", declared)

        return int(literal.group(1)) if literal else None

    label_size = size_of(label)
    name_size = size_of(name)

    assert label_size and name_size

    assert name_size > label_size, (
        f"the name renders at {name_size}px and the labels of its "
        f"attributes at {label_size}px, so the labels are at least as "
        f"loud as the person"
    )


def test_no_stylesheet_rule_outlives_the_markup_that_used_it():
    """
    .mf-section--split and .mf-section__identity* went when the two
    layout components that emitted them did.

    Kept as a test because this codebase has been on both sides of the
    same mistake. components/workflow.py records classes that were
    emitted by the markup and defined in no stylesheet, so they styled
    nothing for a release without anyone noticing. Rules defined in the
    stylesheet and emitted by nothing are the mirror image: they cost the
    same to keep and mislead the next reader the same way.
    """

    from pathlib import Path

    markup = (
        Path(__file__).resolve().parent.parent
        / "apps" / "web" / "components" / "layout.py"
    ).read_text(encoding="utf-8")

    # Comments stripped from both sides. The note recording *why* these
    # were removed names them, and a check that fails on its own
    # tombstone teaches the next person to delete the explanation.
    stylesheet = re.sub(r"/\*.*?\*/", "", THEME, flags=re.DOTALL)

    emitted = re.sub(r"#.*", "", markup)

    for orphan in (
        "mf-section--split",
        "mf-section__identity",
        "mf-section__identity-label",
        "mf-section__identity-name",
    ):
        assert f".{orphan}" not in stylesheet, (
            f".{orphan} is still in the stylesheet and nothing emits it"
        )
        assert orphan not in emitted, (
            f"{orphan} is emitted by layout.py with no rule to style it"
        )


def test_the_page_titles_itself_with_the_case_not_the_kind_of_screen():
    """
    "Case Detail" named the kind of screen and nothing about which case,
    which the sidebar already says. The employee's name is the title
    instead.

    The name was briefly moved onto the Case Overview heading line and
    the page title dropped altogether. That removed the furniture and
    took the screen's only h1 with it - leaving the page unnamed in the
    document outline however clearly a visual heading identified it. The
    two intentions are not in conflict: the title stays, and it names the
    case.

    Both halves are asserted, because either one alone comes back. A
    title that says "Case Detail" is the furniture returning; the name
    appearing on the section heading as well is the same person read
    twice in one screenful, which is what the move was trying to fix.
    """

    from pathlib import Path

    source = (
        Path(__file__).resolve().parent.parent
        / "apps" / "web" / "views" / "case_detail.py"
    ).read_text(encoding="utf-8")

    assert 'page_header(t("case_detail_header"))' not in source, (
        "the page titles itself after the kind of screen it is, which "
        "the sidebar already says"
    )

    assert "page_header(employee_name)" in source, (
        "the screen has no h1, so it is unnamed in the outline that "
        "assistive technology reads"
    )

    assert "section_header_with_identity(" not in source, (
        "the employee is named on the section heading as well as in the "
        "page title, so the reader meets the same person twice"
    )


def test_the_section_headings_are_heavier_than_body_text():
    """
    They sit inside bordered containers now. At the same weight as the
    content they name, they read as another line in the box rather than
    as its title.
    """

    title = _rule(".mf-section__title")

    assert int(title.get("font-weight", "400")) >= 700


def test_the_stage_actions_are_inside_the_workflow_container():
    """
    Advance and Manual override act on the stage shown above them.
    Outside the box they read as page-level actions belonging to nothing
    in particular.
    """

    from pathlib import Path

    source = (
        Path(__file__).resolve().parent.parent
        / "apps" / "web" / "views" / "case_detail.py"
    ).read_text(encoding="utf-8")

    box = source.index("workflow_box = st.container(border=True)")
    tabs = source.index("st.tabs([")

    advance = source.index("advance_stage_btn", box)
    override = source.index("apply_override_btn", box)

    assert box < advance < tabs
    assert box < override < tabs


def test_the_heading_below_the_identity_is_not_pushed_away_from_it():
    """
    The reported complaint alongside the size: too much space between the
    name and Case Overview. .mf-section's top margin separates one
    section from the previous one, and here there is no previous
    section - so the full gap left the first heading looking detached
    from the page it belongs to.
    """

    standard = _first_length(_rule(".mf-section").get("margin"))
    tight = _first_length(_rule(".mf-section--tight").get("margin-top"))

    assert standard is not None and tight is not None

    assert tight < standard


# ----------------------------------------------------------- tokens ---

def test_no_rule_refers_to_a_colour_token_that_does_not_exist():
    """
    Guards against a typo that renders as nothing.

    A var(--mf-thing) that was never declared silently falls back - to
    the fallback if one is given, to unset if not - so a mistyped token
    produces a rule that looks present in the stylesheet and does nothing
    on screen. Written after exactly that: --mf-surface-sunken, invented
    while adding the tab styles, with `transparent` as its fallback. The
    hover state would have been dead and the CSS would have looked fine.
    """

    declared = set(re.findall(r"(--mf-[a-z0-9-]+):", THEME))

    used = set(re.findall(r"var\(\s*(--mf-[a-z0-9-]+)", THEME))

    missing = used - declared

    assert not missing, (
        f"these tokens are used but never declared: {sorted(missing)}"
    )


# ------------------------------------------------ the provenance line ---

@pytest.fixture
def translations():

    import json

    path = (
        Path(__file__).resolve().parent.parent
        / "i18n" / "translations" / "en.json"
    )

    return json.loads(path.read_text(encoding="utf-8"))


def test_the_ungrammatical_summary_string_is_gone(translations):
    """
    "{sourced} of {total} factors reflect ..." reads "1 of 4 factors
    reflect" for the commonest case on this screen.
    """

    assert "risk_basis_summary" not in translations


def test_a_fully_sourced_score_is_not_told_it_has_a_remainder(translations):
    """
    The more serious half. The old string always ended "The rest are
    operational judgement", so a score every factor of which was sourced
    still disclaimed a remainder that did not exist.
    """

    assert "operational judgement" not in translations[
        "risk_basis_summary_all"
    ].lower()


def test_each_summary_is_grammatical_on_its_own_terms(translations):
    """
    The point of splitting one string into three: each is written for a
    situation it is only used in, so no verb has to agree with a number
    that is not known when the sentence is written.
    """

    for key in (
        "risk_basis_summary_all",
        "risk_basis_summary_mixed",
        "risk_basis_summary_none",
    ):
        assert key in translations

    # "factors reflect" is only correct where the count is genuinely
    # plural, which is the all-sourced case; the mixed one is phrased to
    # avoid the agreement entirely.
    assert "{sourced}" not in translations["risk_basis_summary_all"]
    assert "{sourced}" not in translations["risk_basis_summary_none"]
    assert "{sourced}" in translations["risk_basis_summary_mixed"]


def test_the_page_chooses_between_them_rather_than_formatting_one():

    source = (
        Path(__file__).resolve().parent.parent
        / "apps" / "web" / "views" / "case_detail.py"
    ).read_text(encoding="utf-8")

    for key in (
        "risk_basis_summary_all",
        "risk_basis_summary_mixed",
        "risk_basis_summary_none",
    ):
        assert key in source, f"{key} is never used, so a case renders nothing"


# -------------------------------------------------------- the cap ---

def test_a_capped_score_says_so_beside_the_number_not_inside_the_expander():
    """
    100 is not a value once the cap is reached; it is a floor. A case
    totalling 115 and one totalling 260 both render 100, so the note that
    distinguishes them belongs where the number is - not one click away,
    which is where nobody reads it.
    """

    source = (
        Path(__file__).resolve().parent.parent
        / "apps" / "web" / "views" / "case_detail.py"
    ).read_text(encoding="utf-8")

    body = source[source.index("def _render_risk_provenance"):]
    body = body[:body.index("\ndef ")]

    cap = body.index("was_capped")
    expander = body.index("st.expander")

    assert cap < expander, (
        "the capped-score note is rendered inside the expander, so the "
        "screen shows 100 with nothing to say the factors totalled more"
    )


def test_the_cap_is_stated_once(translations):
    """
    It was moved, not copied. The same caveat in two places on one screen
    reads as two separate findings.
    """

    source = (
        Path(__file__).resolve().parent.parent
        / "apps" / "web" / "views" / "case_detail.py"
    ).read_text(encoding="utf-8")

    assert source.count("risk_capped_note") == 1


def test_the_screenshot_case_would_actually_be_capped():
    """
    Grounds the above in the real numbers rather than in a hypothetical.

    Non-EU 40 + Permit F 45 + Valais 10 + Relocation 20 = 115, which is
    the case in the screenshot: it displayed HIGH Risk 100.
    """

    import json

    weights = json.loads(
        (
            Path(__file__).resolve().parent.parent
            / "data" / "risk_weights.json"
        ).read_text(encoding="utf-8")
    )["weights"]

    total = (
        weights["nationality"]["NON_EU"]["points"]
        + weights["permit"]["F"]["points"]
        + weights["canton"]["VALAIS"]["points"]
        + weights["business_mode"]["RELOCATION"]["points"]
    )

    assert total > 100, (
        f"these four factors total {total}, so the case in the screenshot "
        f"would no longer be capped and this test no longer describes it"
    )
