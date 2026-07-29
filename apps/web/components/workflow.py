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


def workflow_stepper(
    stages,
    current_index: int,
    progress_percent: int,
    progress_label: str,
    current_stage_label: str,
    stage_word: str,
) -> None:
    """
    Render the case workflow as a horizontal stepper.

    Args:
        stages: Display labels, already translated, in order.
        current_index: Position of the active stage.
        progress_percent: Completion percentage, computed by the caller so
            this component never re-derives a number the page already has.
        progress_label: Translated word for "Progress".
        current_stage_label: Translated words for "current stage",
            announced to screen readers on the active step.
        stage_word: Translated word for "Stage", used in "Stage 2 of 7".

    Emitted as one ``st.markdown`` call - see the module docstring.
    """

    steps_html = []

    for index, stage in enumerate(stages):

        state = _stage_state(index, current_index)

        # aria-current is the standard way to tell assistive technology
        # which step of a process the user is on.
        aria = ' aria-current="step"' if state == "current" else ""

        screen_reader_note = (
            f'<span class="mf-visually-hidden"> — {escape(current_stage_label)}</span>'
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

    position = (
        f"{escape(stage_word)} {current_index + 1}/{len(stages)}"
        f" · {escape(progress_label)} {int(progress_percent)}%"
    )

    st.markdown(
        f'<div class="mf-stepper">'
        f'<ol class="mf-stepper__track">{"".join(steps_html)}</ol>'
        f'<div class="mf-stepper__meta">{position}</div>'
        f"</div>",
        unsafe_allow_html=True,
    )
