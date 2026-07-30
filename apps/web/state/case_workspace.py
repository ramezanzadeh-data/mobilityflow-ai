"""
What the user has in progress on a case, kept across reruns.

Streamlit re-executes the whole script on every interaction. Anything not
in ``st.session_state`` is gone by the next click - including the bytes
returned by ``st.file_uploader``, which are only available on the run
where the file was selected.

The case detail page had no home for that, so an upload survived exactly
one interaction. Pressing any other button on the page - confirming a
stage, ticking a task, expanding a section - discarded the processed
result and the user had to upload and re-run OCR and the model again. One
handler even deleted the result outright::

    del st.session_state["ai_operator_result"]

Which is why the page felt like it forgot everything: it did.

Why a module and not a few keys
-------------------------------
The page had ten session keys - ``ai_operator_result``,
``pipeline_result``, ``doc_report``, ``ai_doc_suggestions``,
``pipeline_recommendation``, ``pipeline_email``, and more - written and
deleted from a dozen places, with no single point that knew what a
"workspace" contained or when it should be cleared. Two of them held
overlapping copies of the same analysis from the two parallel upload
paths.

Everything in-progress for one case now lives behind this module, keyed
by case id, so opening a different case cannot show the previous case's
document analysis - which the flat keys allowed.
"""

import streamlit as st


# One dict per session, keyed by case id. Namespaced so it cannot collide
# with a widget key: Streamlit stores widget values in the same mapping.
_ROOT = "_case_workspace"


def _workspaces():

    if _ROOT not in st.session_state:
        st.session_state[_ROOT] = {}

    return st.session_state[_ROOT]


def workspace(case_id):
    """
    The in-progress state for one case, created empty on first use.

    Keyed by case id rather than held flat, because the flat keys leaked:
    opening case 12 after working on case 7 showed case 7's document
    analysis until something happened to overwrite it.
    """

    workspaces = _workspaces()

    if case_id not in workspaces:
        workspaces[case_id] = {}

    return workspaces[case_id]


def remember_upload(case_id, filename, file_bytes):
    """
    Hold an uploaded file so it survives the next rerun.

    st.file_uploader returns the bytes only on the run where the file was
    chosen. Without this, any subsequent interaction means re-uploading -
    and re-running OCR and the model, which is where the time goes.
    """

    workspace(case_id)["upload"] = {
        "filename": filename,
        "bytes": file_bytes,
    }


def current_upload(case_id):
    """The file currently being worked on, or None."""

    return workspace(case_id).get("upload")


def remember_analysis(case_id, analysis):
    """
    Hold the processed result of the current upload.

    Kept separately from the file so a rerun that does not re-process
    still has both, and so clearing one is a deliberate act rather than a
    side effect of the other.
    """

    workspace(case_id)["analysis"] = analysis


def current_analysis(case_id):
    return workspace(case_id).get("analysis")


def clear_upload(case_id):
    """
    Finish with the current file.

    Called when the user attaches it to a checklist item or explicitly
    starts over - not on every rerun, and not as a side effect of an
    unrelated button. That distinction is the whole bug: results were
    being dropped by handlers that had nothing to do with the upload.
    """

    space = workspace(case_id)

    space.pop("upload", None)
    space.pop("analysis", None)


def clear_case(case_id):
    """Discard everything in progress for one case."""

    _workspaces().pop(case_id, None)
