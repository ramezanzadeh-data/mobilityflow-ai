from html import escape

import streamlit as st

import json
from datetime import date, datetime

from core.case.service import load_case

from db.database import (
    case_statutory_dates,
    get_tasks,
    get_documents,
    update_task,
    update_document,
    set_workflow_state,
    get_case_events,
    set_task_due_date,
    get_email_templates,
    create_email_template,
    add_task,
    add_document
)

from core.ai.engine import ask_ai

from core.reporting.pdf import export_case_pdf

from core.rules.risk import calculate_risk_from_rules
from core.rules.engine import build_workflow_from_rules

from core.rules.obligations import (
    DUE_SOON as OBLIGATION_DUE_SOON,
    DUE_TODAY as OBLIGATION_DUE_TODAY,
    OVERDUE as OBLIGATION_OVERDUE,
    UPCOMING as OBLIGATION_UPCOMING,
    build_obligations,
    missing_trigger_dates,
    unverified_count,
)

from core.documents.analyzer import (
    analyze_documents
)

from core.documents.document_processing_service import process_uploaded_document

from apps.web.utils.ui import StepNumbering
from apps.web.components.badges import badge_html
from apps.web.components.cards import field_grid, obligation_row
from apps.web.components.workflow import workflow_stepper
from apps.web.components.layout import page_header, section_header


from core.workflow.states import (
    WORKFLOW_STATES,
    get_next_state,
    get_state_index,
    normalize_legacy_state
)


from core.documents.pipeline import (
    generate_recommendation
)
from core.communication.email import (
    generate_email,
    generate_checklist,
    generate_letter,
    fill_email_template
)

from i18n.translator import t, get_lang
from auth.permissions import can_manage_email_templates, has_permission
from core.ai.agent import run_agent
from core.ai.operator import run_ai_operator

from core.workflow.transitions import (
    apply_scenario,
    SCENARIO_LABELS
)

from core.documents.validation import (
    suggest_additional_documents_with_ai
)
from i18n.labels import (
    canton_label,
    nationality_label,
    permit_label,
    mode_label,
    workflow_state_label
)


def _reset_pipeline_state_if_case_changed(case_id):

    pipeline_keys = [
        "pipeline_extraction",
        "pipeline_classification",
        "pipeline_recommendation",
        "pipeline_email",
        "pipeline_checklist",
        "pipeline_letter",
    ]

    if st.session_state.get("pipeline_case_id") != case_id:

        for key in pipeline_keys:
            st.session_state.pop(key, None)

        st.session_state["pipeline_case_id"] = case_id


def show_case_detail():

    page_header(t("case_detail_header"))

    lang = get_lang()

    case_id = st.session_state.get("selected_case")


    if not case_id:
        st.warning(t("select_case_warning"))
        return


    case = load_case(case_id)


    if not case:
        st.error(t("case_not_found"))
        return

    logged_in_user = st.session_state.get("user", {})

    # Defined here rather than part-way down the page. This is read by the
    # AI section and the Communication section, and used to be assigned
    # inside Communication - so the two were coupled by nothing but source
    # order. Regrouping the page into tabs moved the AI section above
    # Communication and the read started happening before the assignment,
    # raising UnboundLocalError on every case page.
    #
    # A value more than one section depends on belongs at the top of the
    # function, where the order cannot be rearranged out from under it.
    current_user = logged_in_user

    user_company = logged_in_user.get("company")
    case_company = case[11]

    if user_company and case_company != user_company:
        # Same message as "not found" - never confirm to a user that a
        # case belonging to another tenant exists.
        st.error(t("case_not_found"))
        return


    _reset_pipeline_state_if_case_changed(case_id)


    employee_name = case[1]
    nationality = case[2]
    canton = case[3]
    permit = case[4]
    business_mode = case[5]
    employer = case[6]
    status = case[7]
    workflow_state = case[8]
    risk_level = case[9]
    ai_summary = case[10]
    company = case[11]
    assigned_to = case[12]
    created_at = case[13]
    case_history = case[14]
    audit_log = case[15]


    nationality_display = nationality_label(nationality, lang)
    canton_display = canton_label(canton, lang)
    permit_display = permit_label(permit, lang)
    mode_display = mode_label(business_mode, lang)


    risk, trace = calculate_risk_from_rules(case)

    workflow = build_workflow_from_rules(case)


    # Was st.columns([6, 1]): the left column was never written to, so it
    # rendered as a tall empty gap under the page title, and 1/7 of the
    # width was too narrow for the button label even before the viewport
    # got small. 5:2 gives the label room at any realistic width, and the
    # left column now carries the case identity instead of nothing.
    top_left, top_right = st.columns([5, 2])

    with top_left:
        st.caption(f"{t('employee_caption')} · {employee_name}")

    with top_right:

        if st.button(
            t("back_to_dashboard_button"),
            key="back_to_dashboard_top"
        ):

            st.session_state["page"] = "Dashboard"

            if "doc_report" in st.session_state:
                del st.session_state["doc_report"]

            st.rerun()


    section_header(t("case_overview_header"))

    # Risk thresholds are unchanged and stay here, where they already
    # lived - the badge component is told the level and never derives it.
    if risk >= 60:
        risk_level, risk_text = "danger", t("risk_high")
    elif risk >= 30:
        risk_level, risk_text = "warning", t("risk_medium")
    else:
        risk_level, risk_text = "success", t("risk_low")

    # Was st.columns(8). Eight fixed fractions left each field ~90px wide,
    # so values wrapped one character per line ("Emplo/yee") and the risk
    # alert rendered as a vertical strip of letters. field_grid states a
    # minimum width per field and reflows to however many columns fit.
    field_grid([
        (t("employee_caption"), employee_name),
        (t("nationality_caption"), nationality_display),
        (t("canton_caption"), canton_display),
        (t("permit_caption"), permit_display),
        (t("mode_caption"), mode_display),
        (t("status_caption"), status),
        (t("company_caption"), company),
        (
            t("risk_score_label"),
            None,
            badge_html(risk_text, level=risk_level, score=risk),
        ),
    ])


    section_header(t("workflow_stage_header"))

    normalized_state = normalize_legacy_state(workflow_state)

    current_index = get_state_index(normalized_state)

    progress_value = int(
        ((current_index + 1) / len(WORKFLOW_STATES))
        * 100)

    # Was seven vertical emoji bullets plus an st.progress bar, wrapped in
    # a <div class="workflow-card"> whose opening and closing tags were
    # emitted by two separate st.markdown calls - so the wrapper never
    # wrapped anything and its CSS class was never defined either way.
    #
    # Same stages, same order, same current position: only the drawing
    # changed. Stage order and the active stage still come from
    # core.workflow via WORKFLOW_STATES and get_state_index() above.
    workflow_stepper(
        stages=[
            workflow_state_label(state, lang)
            for state in WORKFLOW_STATES
        ],
        current_index=current_index,
        progress_percent=progress_value,
        progress_label=t("progress_label"),
        current_stage_label=t("current_stage"),
        stage_word=t("stage_word"),
    )


    next_state = get_next_state(
        normalized_state)

    action_col1, action_col2 = st.columns(
        [2, 3])

    with action_col1:
        if next_state:
            next_label = workflow_state_label(
                next_state,
                lang)

            if st.button(
                f"➡️ {t('advance_stage_button')} {next_label}",
                type="primary",
                key="advance_stage_btn"
            ):

                set_workflow_state(
                    case_id,
                    next_state
                )
                st.rerun()
        else:
            st.success(
                t("workflow_completed_message"))
    with action_col2:
        with st.expander(
            f"⚙️ {t('manual_override_title')}"
        ):
            override_choice = st.selectbox(

                t("override_stage_label"),

                WORKFLOW_STATES,

                index=current_index,

                format_func=lambda s:
                    workflow_state_label(
                        s,
                        lang
                    ),

                key="override_stage_select"

            )


            override_note = st.text_input(

                t("override_reason_label"),

                key="override_reason"

            )

            if st.button(

                t("apply_override_button"),

                key="apply_override_btn"

            ):

                if override_choice != normalized_state:


                    set_workflow_state(

                        case_id,

                        override_choice,

                        note=override_note
                        if override_note
                        else "manual override"

                    )


                    st.rerun()


    # Nine expanders used to sit stacked on this page, so a single case
    # printed to eight pages and the operator had to scroll past every
    # section to reach any one of them. Grouping them into five tabs is
    # the pattern comparable products use: the summary and workflow
    # above stay permanently visible, and the working areas are one
    # click apart instead of one long scroll.
    #
    # Purely a container change. Every section keeps its own body, its
    # widget keys and its order within a tab; no section was merged,
    # split or dropped.
    (
        tasks_tab,
        documents_tab,
        ai_tab,
        communication_tab,
        insights_tab,
    ) = st.tabs([
        t("tasks_tab_label"),
        t("documents_tab_label"),
        t("ai_tab_label"),
        t("communication_tab_label"),
        t("insights_tab_label"),
    ])

    with tasks_tab:

        section_header(t("tasks_expander"))
        with st.container():
            tasks = get_tasks(case_id)


            if tasks:

                done = len(
                    [
                        tk for tk in tasks
                        if tk[3] == "DONE"
                    ]
                )


                st.metric(
                    t("completion_metric"),
                    f"{done}/{len(tasks)}"
                )


                for task in tasks:


                    # One row per task, not three. Previously the checkbox and
                    # due date came from st.columns([6, 2]) and the AI button
                    # from a second st.columns([1.5, 6.5]) below it, so each
                    # task occupied three ragged rows - 16 tasks became a
                    # 48-row wall that nobody reads.
                    task_col, due_col, ai_col = st.columns([6, 2, 1])


                    with task_col:

                        checked = st.checkbox(
                            task[2],
                            value=(task[3] == "DONE"),
                            key=f"task_check_{task[0]}"
                        )


                        new_status = (
                            "DONE"
                            if checked
                            else
                            "PENDING"
                        )


                        if new_status != task[3]:

                            update_task(
                                task[0],
                                new_status
                            )

                            st.rerun()


                    with due_col:

                        current_due_str = (
                            task[4]
                            if len(task) > 4
                            else None
                        )


                        current_due_date = None


                        if current_due_str:

                            try:

                                current_due_date = datetime.strptime(
                                    current_due_str,
                                    "%Y-%m-%d"
                                ).date()

                            except:

                                pass


                        # A real label, visually collapsed. The empty string
                        # this replaces still reserved vertical space for a
                        # label, which is why the date sat lower than the
                        # checkbox beside it - and it left the field unnamed
                        # for screen readers.
                        new_due_date = st.date_input(
                            t("task_due_date_label"),
                            value=current_due_date,
                            key=f"task_due_{task[0]}",
                            label_visibility="collapsed"
                        )


                        new_due_str = (
                            new_due_date.isoformat()
                            if new_due_date
                            else None
                        )


                        if new_due_str != current_due_str:

                            set_task_due_date(
                                task[0],
                                new_due_str
                            )


                    with ai_col:

                        ai_clicked = st.button(
                            t("ai_task_button"),
                            key=f"task_ai_{task[0]}"
                        )


                    # Rendered below the row rather than in a side column:
                    # an explanation is prose and needs the full width, and
                    # only one task shows one at a time. Same call, same
                    # prompt, same result - only the placement changed.
                    if ai_clicked:

                        with st.spinner(t("ai_task_thinking_label")):

                            answer = ask_ai(
                                f"""
        Explain this Swiss relocation task:

        {task[2]}

        Give a short operational explanation. """)

                        st.info(answer)

    with documents_tab:

        section_header(t("documents_expander"))
        with st.container():
            docs = get_documents(case_id)

            if docs:

                uploaded = len(
                    [
                        d for d in docs
                        if d[3] == "UPLOADED"
                    ]
                )

                docs_main, docs_metric = st.columns([4, 1])

                with docs_metric:

                    st.metric(
                        t("uploaded_metric"),
                        f"{uploaded}/{len(docs)}"
                    )

                with docs_main:

                    for doc in docs:

                        name_col, status_col = st.columns([5, 1])

                        with name_col:

                            st.write(f"📄 {doc[2]}")

                        with status_col:

                            current = st.selectbox(

                                t("status_selectbox_label"),

                                [
                                    "MISSING",
                                    "UPLOADED"
                                ],

                                index=(
                                    0
                                    if doc[3] == "MISSING"
                                    else
                                    1
                                ),

                                key=f"doc_{doc[0]}",

                                label_visibility="collapsed"
                            )

                            if current != doc[3]:

                                update_document(
                                    doc[0],
                                    current
                                )

            else:

                st.warning(
                    t("no_documents_warning")
                )

        section_header(t("doc_intelligence_expander"))
        with st.container():
            automatic_tab, manual_tab = st.tabs([
                t("doc_intelligence_automatic_tab"),
                t("doc_intelligence_manual_tab"),
            ])

            with automatic_tab:
                st.markdown(f"### {t('ai_operator_header')}")
                st.caption(t("ai_operator_subheader"))

                operator_file = st.file_uploader(
                    t("doc_pipeline_upload_label"),
                    type=["pdf"],
                    key=f"operator_uploader_{case_id}"
                )

                if operator_file is not None:

                    if st.button(
                        t("run_ai_operator_button"),
                        key="run_ai_operator_btn",
                        type="primary"
                    ):

                        with st.spinner(t("ai_operator_running_label")):

                            operator_result = run_ai_operator(
                                case, operator_file.read()
                            )

                        st.session_state["ai_operator_result"] = operator_result

                if "ai_operator_result" in st.session_state:

                    op_result = st.session_state["ai_operator_result"]

                    if op_result.get("error"):

                        st.error(op_result["error"])

                    else:

                        st.success(t("ai_operator_done_label"))

                        with st.expander(t("ai_operator_steps_label"), expanded=True):

                            # Several steps below render only when the operator
                            # produced the corresponding result. Literal numbers
                            # therefore left gaps (1, 2, 3, 4, 6, 7, 8), which reads
                            # as a missing step rather than a skipped one.
                            step = StepNumbering()

                            st.write(
                                f"**{step.next()} "
                                f"{t('doc_pipeline_extraction_method_label')}:** "
                                f"{op_result['extraction']['method']}"
                            )

                            st.write(
                                f"**{step.next()} "
                                f"{t('doc_pipeline_document_type_label')}:** "
                                f"{op_result['classification'].get('document_type', '')}"
                            )

                            if op_result["validation_warnings"]:
                                for w in op_result["validation_warnings"]:
                                    st.warning(f"⚠️ {w}")

                            expiry_status, expiry_message = op_result["expiry"]
                            if expiry_status == "expired":
                                st.error(f"🔴 {expiry_message}")
                            elif expiry_status == "expiring_soon":
                                st.warning(f"🟡 {expiry_message}")

                            missing = op_result["missing_documents_report"]["missing_documents"]
                            st.write(
                                f"**{step.next()} {t('missing_documents_label')}** "
                                f"{', '.join(missing) or '—'}"
                            )

                            risk_score, _ = op_result["risk"]
                            st.write(
                                f"**{step.next()} {t('risk_score_metric')}:** "
                                f"{risk_score}/100"
                            )

                            if op_result["tasks_created"]:
                                st.write(
                                    f"**{step.next()} "
                                    f"{t('ai_operator_tasks_created_label')}**"
                                )
                                for task_title in op_result["tasks_created"]:
                                    st.write(f"- {task_title}")

                            if op_result["reminder_due_date"]:
                                st.write(
                                    f"**{step.next()} {t('ai_operator_reminder_label')}:** "
                                    f"{op_result['reminder_due_date']}"
                                )

                            if op_result["email_draft"]:
                                st.write(
                                    f"**{step.next()} {t('ai_operator_email_label')}**"
                                )
                                st.text_area(
                                    t("doc_pipeline_generate_email_button"),
                                    op_result["email_draft"],
                                    height=150,
                                    key="operator_email_area"
                                )

                            st.write(
                                f"**{step.next()} {t('ai_operator_notification_label')}**"
                            )

                            if op_result["next_stage_recommendation"]:

                                st.info(
                                    f"**{step.next()}** "
                                    f"{op_result['next_stage_recommendation']}"
                                )

                                next_state_to_confirm = get_next_state(
                                    normalize_legacy_state(case[8])
                                )

                                if st.button(
                                    t("confirm_advance_button"),
                                    key="operator_confirm_advance_btn",
                                    type="primary"
                                ):

                                    set_workflow_state(
                                        case_id,
                                        next_state_to_confirm,
                                        note="confirmed via AI Operator recommendation"
                                    )

                                    st.success(t("stage_advanced_success"))

                                    del st.session_state["ai_operator_result"]
                                    st.rerun()

            with manual_tab:
                st.markdown(f"**{t('doc_pipeline_step1_header')}**")

                doc_names = [d[2] for d in docs] if docs else []

                target_doc_name = st.selectbox(
                    t("attach_to_document_label"),
                    doc_names + [t("new_document_option")],
                    key="pipeline_attach_doc_choice"
                ) if doc_names else t("new_document_option")

                new_doc_name = None
                if target_doc_name == t("new_document_option"):
                    new_doc_name = st.text_input(
                        t("new_document_name_label"),
                        key="pipeline_new_doc_name"
                    )

                uploaded_file = st.file_uploader(
                    t("doc_pipeline_upload_label"),
                    type=["pdf"],
                    key=f"pipeline_uploader_{case_id}"
                )

                if uploaded_file is not None:

                    if st.button(
                        t("doc_pipeline_process_button"),
                        key="process_document_btn"
                    ):

                        document_name = (
                            new_doc_name.strip()
                            if target_doc_name == t("new_document_option") and new_doc_name
                            else target_doc_name
                        )

                        if not document_name:
                            st.error(t("document_name_required_error"))
                        else:

                            with st.spinner(t("checking_defects_label")):

                                # This one call runs the ENTIRE chain: save file to
                                # object storage, save/attach the document row, OCR,
                                # AI classification, rule engine, risk update,
                                # workflow advancement, timeline + notification, and
                                # (if the document passes) automatically queuing a
                                # review email - none of that logic lives in this
                                # page anymore.
                                result = process_uploaded_document(
                                    case_id=case_id,
                                    document_name=document_name,
                                    filename=uploaded_file.name,
                                    file_bytes=uploaded_file.read(),
                                )

                            st.session_state["pipeline_result"] = result

                if "pipeline_result" in st.session_state:

                    result = st.session_state["pipeline_result"]

                    if result.get("error"):

                        st.error(result["error"])

                    else:

                        extraction = result["extraction"]
                        classification = result["classification"]

                        m1, m2 = st.columns(2)

                        with m1:
                            st.metric(t("doc_pipeline_extraction_method_label"), extraction["method"])

                        with m2:
                            st.metric(t("doc_pipeline_pages_label"), extraction["pages"])

                        if extraction["warning"]:
                            st.warning(extraction["warning"])

                        st.write(
                            f"**{t('doc_pipeline_document_type_label')}:** "
                            f"{classification.get('document_type', '')}"
                        )

                        st.write(
                            f"**{t('doc_pipeline_summary_label')}:** "
                            f"{classification.get('summary', '')}"
                        )

                        key_facts = classification.get("key_facts") or {}

                        if key_facts:

                            st.write(f"**{t('doc_pipeline_key_facts_label')}:**")

                            for fact_key, fact_value in key_facts.items():
                                st.write(f"- {fact_key}: {fact_value}")

                        for warning_msg in result["validation_warnings"]:
                            st.warning(f"⚠️ {warning_msg}")

                        doc_analysis = result["doc_analysis"]

                        r1, r2, r3 = st.columns(3)
                        with r1:
                            st.metric(t("compliance_score_label"), doc_analysis["compliance_score"])
                        with r2:
                            st.metric(t("risk_score_label"), result["risk"])
                        with r3:
                            st.metric(t("missing_documents_label"), len(doc_analysis["missing_documents"]))

                        if doc_analysis["missing_documents"]:
                            st.write(f"**{t('missing_documents_label')}:**")
                            for missing in doc_analysis["missing_documents"]:
                                st.write(f"- {missing}")

                        if result["rules_passed"]:
                            st.success(t("rules_passed_message"))
                            if result["workflow_advanced"]:
                                st.success(t("workflow_advanced_message"))
                            if result["email_job_id"]:
                                st.info(t("review_email_queued_message"))
                        else:
                            st.warning(t("rules_not_passed_message"))

                        st.caption(f"Job status: `/api/v1/jobs/{result['email_job_id']}`" if result["email_job_id"] else "")


                st.divider()


                st.markdown(f"**{t('doc_pipeline_step2_header')}**")

                if st.button(
                    t("analyze_documents_button"),
                    key="analyze_documents_btn"
                ):

                    report = analyze_documents(
                        case,
                        docs
                    )

                    st.session_state["doc_report"] = report


                if "doc_report" in st.session_state:

                    report = st.session_state["doc_report"]

                    r1, r2, r3 = st.columns(3)

                    with r1:
                        st.metric(
                            t("compliance_metric"),
                            report["compliance_score"]
                        )

                    with r2:
                        st.metric(
                            t("missing_metric"),
                            len(report["missing_documents"])
                        )

                    with r3:
                        st.metric(
                            t("risks_metric"),
                            len(report["risk_factors"])
                        )

                    if report["missing_documents"]:

                        st.warning(t("missing_documents_label"))

                        for item in report["missing_documents"]:
                            st.write(f"• {item}")

                    if report["risk_factors"]:

                        st.error(t("risk_factors_label"))

                        for item in report["risk_factors"]:
                            st.write(f"• {item}")


                    if st.button(
                        t("suggest_additional_docs_button"),
                        key="suggest_additional_docs_btn"
                    ):

                        with st.spinner(t("suggesting_docs_label")):

                            suggestions = suggest_additional_documents_with_ai(
                                case,
                                docs,
                                report["missing_documents"]
                            )

                        st.session_state["ai_doc_suggestions"] = suggestions

                    if "ai_doc_suggestions" in st.session_state:

                        suggestions = st.session_state["ai_doc_suggestions"]

                        if suggestions:

                            st.info(
                                f"**{t('ai_suggested_docs_label')}** "
                                f"_{t('ai_review_disclaimer')}_"
                            )

                            for suggestion in suggestions:
                                st.write(f"• {suggestion}")

                        else:

                            st.caption(t("no_additional_docs_suggested"))


                st.divider()


                # Step 3 is rendered unconditionally so the pipeline always reads
                # 1 - 2 - 3 - 4. It used to live inside the "doc_report" branch, so
                # before Step 2 had been run the user saw "Step 1, Step 2, Step 4"
                # and had no way to tell a skipped step from a missing feature.
                #
                # The action stays gated exactly as before: generate_recommendation()
                # needs the Step 2 report, so the button is disabled rather than
                # hidden - a visible, explained prerequisite instead of a silent gap.
                st.markdown(f"**{t('doc_pipeline_step3_header')}**")

                doc_report_ready = "doc_report" in st.session_state

                if not doc_report_ready:
                    st.caption(t("doc_pipeline_step3_requires_step2"))

                if st.button(
                    t("doc_pipeline_recommendation_button"),
                    key="generate_recommendation_btn",
                    disabled=not doc_report_ready
                ):

                    with st.spinner(t("doc_pipeline_recommendation_spinner")):

                        recommendation = generate_recommendation(
                            case,
                            risk,
                            trace,
                            workflow,
                            st.session_state["doc_report"]
                        )

                    st.session_state["pipeline_recommendation"] = recommendation

                if "pipeline_recommendation" in st.session_state:

                    st.info(st.session_state["pipeline_recommendation"])


                st.divider()


                st.markdown(f"**{t('doc_pipeline_step4_header')}**")

                step_choice = st.selectbox(
                    t("doc_pipeline_select_step_label"),
                    workflow,
                    key="pipeline_step_choice"
                )

                e1, e2, e3 = st.columns(3)

                with e1:

                    if st.button(
                        t("doc_pipeline_generate_email_button"),
                        key="generate_email_btn"
                    ):

                        with st.spinner(t("generating_email_spinner")):

                            email_text = generate_email(case, step_choice)

                        st.session_state["pipeline_email"] = email_text

                    if "pipeline_email" in st.session_state:

                        st.text_area(
                            t("doc_pipeline_generate_email_button"),
                            st.session_state["pipeline_email"],
                            height=200,
                            key="pipeline_email_area"
                        )

                        st.download_button(
                            t("doc_pipeline_download_email_button"),
                            st.session_state["pipeline_email"],
                            file_name=f"email_case_{case_id}.txt",
                            key="download_email_btn"
                        )


                with e2:

                    if st.button(
                        t("doc_pipeline_generate_checklist_button"),
                        key="generate_checklist_btn"
                    ):

                        with st.spinner(t("generating_checklist_spinner")):

                            checklist_text = generate_checklist(case, workflow)

                        st.session_state["pipeline_checklist"] = checklist_text

                    if "pipeline_checklist" in st.session_state:

                        st.text_area(
                            t("doc_pipeline_generate_checklist_button"),
                            st.session_state["pipeline_checklist"],
                            height=200,
                            key="pipeline_checklist_area"
                        )

                        st.download_button(
                            t("doc_pipeline_download_checklist_button"),
                            st.session_state["pipeline_checklist"],
                            file_name=f"checklist_case_{case_id}.txt",
                            key="download_checklist_btn"
                        )


                with e3:

                    if st.button(
                        t("doc_pipeline_generate_letter_button"),
                        key="generate_letter_btn"
                    ):

                        with st.spinner(t("generating_letter_spinner")):

                            letter_text = generate_letter(case, risk, trace, workflow)

                        st.session_state["pipeline_letter"] = letter_text

                    if "pipeline_letter" in st.session_state:

                        st.text_area(
                            t("doc_pipeline_generate_letter_button"),
                            st.session_state["pipeline_letter"],
                            height=200,
                            key="pipeline_letter_area"
                        )

                        st.download_button(
                            t("doc_pipeline_download_letter_button"),
                            st.session_state["pipeline_letter"],
                            file_name=f"letter_case_{case_id}.txt",
                            key="download_letter_btn"
                        )

    with ai_tab:

        section_header(t("ai_agent_expander"))
        with st.container():
            if not has_permission(current_user, "ai:use"):

                st.caption(t("ai_agent_no_permission_note"))

            else:

                agent_presets = {
                    t("agent_preset_review"): (
                        "Review this case end-to-end: check the risk score, missing "
                        "documents, and workflow status. If a clear follow-up action "
                        "is missing from the task list, create it. Then tell me the "
                        "single most important next action."
                    ),
                    t("agent_preset_explain"): (
                        "Explain clearly, based only on the real risk breakdown and "
                        "workflow steps you retrieve: (1) why the risk is at this "
                        "level, (2) why these workflow steps are required, and (3) "
                        "what the real priority action is right now."
                    ),
                    t("agent_preset_next_actions"): (
                        "Based on the real risk, missing documents, and workflow "
                        "status, generate exactly 3 specific, operational next "
                        "actions for this case. Do not give generic advice."
                    ),
                    t("agent_preset_action_plan"): (
                        "Based on the real risk, missing documents, and workflow "
                        "status, produce a step-by-step execution plan. For each "
                        "action include: Priority (HIGH/MEDIUM/LOW), Timeline (e.g. "
                        "Day 1, Week 1), and Dependency (what must happen first)."
                    ),
                    t("agent_preset_custom"): None,
                }

                preset_choice = st.selectbox(
                    t("agent_goal_label"),
                    list(agent_presets.keys()),
                    key="agent_preset_choice"
                )

                if agent_presets[preset_choice] is None:

                    user_goal = st.text_area(
                        t("agent_custom_goal_label"),
                        key="agent_custom_goal"
                    )

                else:

                    user_goal = agent_presets[preset_choice]
                    st.caption(user_goal)

                if st.button(t("run_agent_button"), key="run_agent_btn"):

                    if user_goal:

                        with st.spinner(t("agent_thinking_label")):

                            try:
                                result = run_agent(
                                    user_goal,
                                    case_id=case_id,
                                    current_user=current_user,
                                )
                                st.session_state["agent_result"] = result

                            except Exception as e:
                                st.error(f"{t('agent_error_label')}: {e}")

            if "agent_result" in st.session_state:

                agent_result = st.session_state["agent_result"]

                with st.expander(t("agent_steps_label"), expanded=False):

                    for step in agent_result["steps"]:

                        if step["type"] == "tool_call":

                            st.markdown(
                                f"🔧 `{step['tool']}({step['arguments']})` "
                                f"→ {step['result']}"
                            )

                        else:

                            st.markdown(f"✅ {step['content']}")

                st.success(agent_result["answer"])

    with communication_tab:

        section_header(t("communication_expander"))
        with st.container():
            templates = get_email_templates(company)
            no_template_option = t("no_template_option")
            template_names = [no_template_option] + [tpl[1] for tpl in templates]

            chosen_template_name = st.selectbox(
                t("select_template_label"),
                template_names,
                key="comm_template_choice"
            )

            if chosen_template_name != no_template_option:

                match = next(
                    (tpl for tpl in templates if tpl[1] == chosen_template_name),
                    None
                )

                if match:

                    filled_subject = fill_email_template(match[2], case)
                    filled_body = fill_email_template(match[3], case)

                    st.text_input(
                        t("subject_label"),
                        value=filled_subject,
                        key="comm_filled_subject"
                    )

                    st.text_area(
                        t("email_body_label"),
                        value=filled_body,
                        height=200,
                        key="comm_filled_body"
                    )

                    st.download_button(
                        t("download_template_email_button"),
                        f"Subject: {filled_subject}\n\n{filled_body}",
                        file_name=f"template_email_case_{case_id}.txt",
                        key="comm_download_template_email"
                    )


            st.divider()

            if can_manage_email_templates(current_user):

                st.markdown(f"**{t('create_template_header')}**")

                new_template_name = st.text_input(
                    t("template_name_label"),
                    key="comm_new_template_name"
                )

                new_template_subject = st.text_input(
                    t("template_subject_label"),
                    key="comm_new_template_subject"
                )

                new_template_body = st.text_area(
                    t("template_body_label"),
                    key="comm_new_template_body"
                )

                if st.button(
                    t("save_template_button"),
                    key="comm_save_template_btn"
                ):

                    if new_template_name and new_template_body:

                        create_email_template(
                            company,
                            new_template_name,
                            new_template_subject,
                            new_template_body
                        )

                        st.success(t("template_saved_success"))
                        st.rerun()

            else:

                st.caption(t("template_admin_only_note"))

    with insights_tab:

        # First in the tab because it is the highest-consequence thing on
        # the page: a missed immigration deadline costs a person their
        # right to work, which no amount of tidy document handling undoes.
        section_header(t("obligations_header"))

        # Spelled out rather than t(f"trigger_{name}"). A key built from a
        # variable cannot be verified without running the page, so a
        # missing one reaches the user as raw source text - and here that
        # would be inside a statutory deadline notice.
        trigger_labels = {
            "arrival_date": t("trigger_arrival_date"),
            "contract_start_date": t("trigger_contract_start_date"),
            "permit_expiry_date": t("trigger_permit_expiry_date"),
            "case_created_date": t("trigger_case_created_date"),
        }

        obligations = build_obligations(
            canton=canton,
            nationality=nationality,
            permit=permit,
            business_mode=business_mode,
            trigger_dates=case_statutory_dates(case),
        )

        if not obligations:
            st.caption(t("obligations_none"))

        else:

            unverified = unverified_count(obligations)

            if unverified:
                # Stated before the dates, not after. Someone who reads
                # the deadlines first and the caveat second has already
                # treated them as authoritative.
                st.warning(
                    t("obligations_unverified_warning").format(
                        unverified=unverified,
                        total=len(obligations),
                    )
                )

            missing = missing_trigger_dates(obligations)

            if missing:
                st.info(
                    t("obligations_missing_dates").format(
                        dates=", ".join(
                            trigger_labels.get(name, name) for name in sorted(missing)
                        )
                    )
                )

            today = date.today()

            urgency_levels = {
                OBLIGATION_OVERDUE: "danger",
                OBLIGATION_DUE_TODAY: "warning",
                OBLIGATION_DUE_SOON: "warning",
                OBLIGATION_UPCOMING: "neutral",
            }

            urgency_labels = {
                OBLIGATION_OVERDUE: t("obligation_overdue"),
                OBLIGATION_DUE_TODAY: t("obligation_due_today"),
                OBLIGATION_DUE_SOON: t("obligation_due_soon"),
                OBLIGATION_UPCOMING: t("obligation_upcoming"),
            }

            for obligation in obligations:

                urgency = obligation.urgency(today)

                if urgency is None:
                    badge = badge_html(
                        t("obligation_date_unknown"), level="neutral"
                    )
                    due_text = t("obligation_needs_date").format(
                        date_name=trigger_labels.get(
                            obligation.missing_trigger,
                            obligation.missing_trigger,
                        )
                    )
                else:
                    remaining = obligation.days_remaining(today)
                    badge = badge_html(
                        urgency_labels[urgency],
                        level=urgency_levels[urgency],
                        score=f"{remaining:+d}d",
                    )
                    due_text = t("obligation_due_on").format(
                        due_date=obligation.due_date.isoformat(),
                        trigger=trigger_labels.get(
                            obligation.trigger, obligation.trigger
                        ),
                        offset=abs(obligation.offset_days),
                        direction=(
                            t("obligation_before")
                            if obligation.offset_days < 0
                            else t("obligation_after")
                        ),
                    )

                if obligation.is_verified:
                    provenance = escape(
                        t("obligation_verified_by").format(
                            reviewer=obligation.reviewed_by or "",
                            reviewed_on=obligation.reviewed_on or "",
                        )
                    )
                else:
                    provenance = escape(
                        t("obligation_unverified_note").format(
                            note=obligation.verification_note or ""
                        )
                    )

                obligation_row(
                    title=obligation.title,
                    due_text=due_text,
                    urgency_badge_html=badge,
                    detail=obligation.consequence,
                    provenance_html=provenance,
                )

        st.divider()

        with st.expander(
            t("rule_engine_expander"),
            expanded=False
        ):

            rules_col, risk_col = st.columns([5, 1])


            with rules_col:


                for index, step in enumerate(workflow, start=1):

                    st.markdown(
                        f"""
                        <div style="
                            padding:0px 4px;
                            margin:0px;
                            font-size:13px;
                            line-height:16px;
                        ">
                            <b>{escape(str(index))}.</b> {escape(str(step))}
                        </div>
                        """,
                        unsafe_allow_html=True
                    )


            with risk_col:

                st.metric(
                    t("risk_score_metric"),
                    risk
                )

        with st.expander(
            t("life_event_expander"),
            expanded=False
        ):

            scenario_labels_map = {
                code: label for code, label in SCENARIO_LABELS.items()
            }

            scenario_choice = st.selectbox(
                t("select_scenario_label"),
                list(scenario_labels_map.keys()),
                format_func=lambda code: scenario_labels_map[code],
                key="scenario_choice"
            )

            if st.button(t("preview_scenario_button"), key="preview_scenario_btn"):

                st.session_state["scenario_preview"] = apply_scenario(
                    scenario_choice, case
                )

            if "scenario_preview" in st.session_state:

                preview = st.session_state["scenario_preview"]

                st.write(f"**{t('new_tasks_label')}:**")

                for step in preview["steps"]:
                    st.write(f"- {step}")

                st.write(f"**{t('new_documents_label')}:**")

                for doc_name in preview["documents"]:
                    st.write(f"- {doc_name}")

                if preview["canton_note"]:

                    st.warning(
                        f"⚠️ {t('canton_note_disclaimer')}\n\n{preview['canton_note']}"
                    )

                if st.button(
                    t("apply_scenario_button"),
                    key="apply_scenario_btn"
                ):

                    for step in preview["steps"]:
                        add_task(case_id, step)

                    for doc_name in preview["documents"]:
                        add_document(case_id, doc_name)

                    st.success(t("scenario_applied_success"))

                    del st.session_state["scenario_preview"]
                    st.rerun()

        with st.expander(
            t("timeline_expander"),
            expanded=False
        ):

            events = get_case_events(case_id)

            if events:

                for event in events:

                    event_timestamp = event[4]
                    event_description = event[3]


                    time_part = (
                        event_timestamp.split(" ")[1][:5]
                        if " " in event_timestamp
                        else event_timestamp
                    )

                    st.markdown(
                        f"""
                        <div style="
                        display:flex;
                        gap:12px;
                        padding:4px 0;
                        font-size:13px;
                        ">
                        <span style="color:gray; min-width:48px;">{escape(str(time_part))}</span>
                        <span>{escape(str(event_description))}</span>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )

            else:

                st.info(t("no_events_warning"))

        with st.expander(
            t("export_expander"),
            expanded=False
        ):


            if st.button(
                t("generate_pdf_button")
            ):


                file_path = (
                    f"case_{case_id}.pdf"
                )


                export_case_pdf(

                    file_path,

                    case,

                    tasks,

                    docs
                )


                st.success(
                    t("pdf_generated_success")
                )


                with open(
                    file_path,
                    "rb"
                ) as f:


                    st.download_button(

                        t("download_pdf_button"),

                        f,

                        file_name=file_path

                    )



