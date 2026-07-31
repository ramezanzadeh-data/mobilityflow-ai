"""
Horizontal workflow stepper.

Replaces a vertical list of emoji bullets - one ``st.markdown`` call per
stage - with a single stepper that shows the whole process at a glance.

Two defects in the previous version are worth recording, because both are
easy to reintroduce:

1. It wrapped the stages in ``st.markdown('<div class="workflow-card">')``
   and closed the tag in a separate ``st.markdown('</div>')`` call.
   Streamlit renders every markdown call into its own DOM container, so
   the two halves landed in different containers and the wrapper never
   wrapped anything. Any styling hung on that class silently did nothing.
   Hence: one element per markdown call, always self-contained.

2. ``.workflow-card`` and ``.stage-item`` were never defined in any
   stylesheet, so the classes were inert and the stages fell back to
   plain text bullets. All classes used here are defined in
   components/theme.py.

Stage order, stage labels and which stage is current are decided by
core.workflow and passed in. This module only draws them.
"""

from html import escape

import streamlit as st


def _stage_state(index: int, current_index: int) -> str:

    if index < current_index:
        return "done"

    if index == current_index:
        return "current"

    return "upcoming"


def workflow_stage_row(
    title,
    stages,
    current_index: int,
    progress_percent: int,
    progress_label: str,
    current_stage_label: str,
    stage_word: str,
) -> None:
    """
    Heading, track and stage counter on one row.

    All three describe the same thing, and stacked they made the reader
    assemble them: a title, then a track, then a counter underneath. Side
    by side they read as one statement - "Workflow Stage: [track] 1/7".

    Emitted as a single st.markdown call, which is not a style choice.
    Streamlit renders each markdown call into its own DOM container, so
    three calls could never share a flex row however the CSS was written;
    that is the same constraint recorded at the top of this module, where
    a wrapper div split across two calls wrapped nothing.
    """

    # Both built before the markup rather than inlined into it.
    #
    # Not a style preference. tests/test_ui_html_escaping.py reads this
    # file rather than running it, so it can only trust an interpolation
    # it can recognise: a call to a known escaping producer, or a local
    # on its explicit list. A call to _steps_html() inlined in the
    # template is escaped in fact and unverifiable in form, and the guard
    # cannot tell that apart from the stored-XSS it exists to catch.
    #
    # The same goes for the counter. `{current_index + 1}/{len(stages)}`
    # is arithmetic and can only ever be digits, but teaching the rule to
    # trust arbitrary expressions would also teach it to trust `a + b` on
    # two strings - so the counter is assembled here and escaped as one
    # value instead.
    steps_html = _steps_html(stages, current_index, current_stage_label)

    counter = f"{stage_word} {current_index + 1}/{len(stages)}"

    st.markdown(
        '<div class="mf-stage-row">'
        f'<h2 class="mf-section__title mf-stage-row__title">{escape(str(title))}</h2>'
        f'<ol class="mf-stepper__track">{steps_html}</ol>'
        f'<div class="mf-section__meta mf-stage-row__meta">{escape(counter)}</div>'
        "</div>",
        unsafe_allow_html=True,
    )


def _steps_html(stages, current_index, current_stage_label):
    """The <li> elements for a track. Shared by both renderers."""

    steps_html = []

    for index, stage in enumerate(stages):

        state = _stage_state(index, current_index)

        aria = ' aria-current="step"' if state == "current" else ""

        screen_reader_note = (
            f'<span class="mf-visually-hidden"> \u2014 {escape(current_stage_label)}</span>'
            if state == "current"
            else ""
        )

        steps_html.append(
            f'<li class="mf-step mf-step--{state}"{aria}>'
            f'<span class="mf-step__marker" aria-hidden="true"></span>'
            f'<span class="mf-step__label">{escape(str(stage))}'
            f"{screen_reader_note}</span>"
            f"</li>"
        )

    return "".join(steps_html)
