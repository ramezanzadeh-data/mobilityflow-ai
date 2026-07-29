import json
from datetime import datetime, date, time as dt_time, timedelta

import pandas as pd
from html import escape

import streamlit as st

from core.case.service import (
    list_company_cases,
    delete_case_service
)

from core.rules.risk import calculate_risk_from_rules
from core.workflow.states import normalize_legacy_state
from core.reporting.excel import export_cases_to_excel
from core.reporting.analytics import export_company_summary_pdf
from core.reporting.value import (
    SWISS_RATE_GUIDANCE_HIGH,
    SWISS_RATE_GUIDANCE_LOW,
    ValueAssumptions,
    build_value_report,
)
from core.reporting.value_pdf import export_value_report_pdf
from auth.permissions import is_admin, can_export_reports

from apps.web.components.badges import badge_html
from apps.web.components.cards import empty_state, record_row
from apps.web.components.metrics import distribution, kpi
from apps.web.components.layout import page_header, section_header
from apps.web.components.metrics import EMPTY_VALUE
from apps.web.utils.task_urgency import (
    DUE_THIS_WEEK,
    DUE_TODAY,
    LATER,
    NO_DUE_DATE,
    OVERDUE,
    URGENCY_LEVELS,
    group_tasks_by_urgency,
)

from db.database import (
    get_case_events,
    get_value_assumptions_for_company,
    save_value_assumptions_for_company,
    save_filter,
    get_saved_filters,
    delete_saved_filter,
    get_recent_events_for_company,
    get_pending_tasks_for_company
)

from i18n.translator import t, get_lang
from i18n.labels import (
    canton_label,
    nationality_label,
    permit_label,
    mode_label,
    workflow_state_label
)


CANTON_FILTER_OPTIONS = ["All", "VAUD", "VALAIS"]
PERMIT_FILTER_OPTIONS = ["All", "NO_PERMIT", "N", "F", "S", "L", "B", "C", "G"]
NATIONALITY_FILTER_OPTIONS = ["All", "EU", "NON_EU"]
MODE_FILTER_OPTIONS = ["All", "SME", "RELOCATION", "RECRUITMENT"]
SORT_OPTIONS = ["newest", "oldest", "risk_desc", "risk_asc", "name"]


def _get_processing_days(case):

    case_id = case[0]
    created_at_str = case[13]

    if not created_at_str:
        return None

    events = get_case_events(case_id)

    completed_events = [
        e for e in events
        if e[2] == "WORKFLOW_STATE_CHANGED" and "COMPLETED" in e[3]
    ]

    if not completed_events:
        return None

    completed_at_str = completed_events[-1][4]

    try:
        created_dt = datetime.strptime(created_at_str, "%Y-%m-%d %H:%M:%S")
        completed_dt = datetime.strptime(completed_at_str, "%Y-%m-%d %H:%M:%S")
        return (completed_dt - created_dt).total_seconds() / 86400
    except (ValueError, TypeError):
        return None


def _render_kpis_and_charts(cases):

    total_cases = len(cases)

    risks = [calculate_risk_from_rules(c)[0] for c in cases]
    avg_risk = sum(risks) / len(risks) if risks else 0

    nationalities_count = len(set(c[2] for c in cases))

    processing_days_list = [
        d for d in (_get_processing_days(c) for c in cases)
        if d is not None
    ]

    # Same computation as before. What changed is how "nothing to measure
    # yet" is presented: this used to render the literal string "N/A",
    # which reads as a broken metric. None makes the kpi() component show
    # a muted placeholder plus the reason - no case has reached COMPLETED,
    # which is the normal state of a young account rather than a fault.
    if processing_days_list:
        avg_days = sum(processing_days_list) / len(processing_days_list)
        avg_processing_display = f"{avg_days:.1f}d"
        avg_processing_note = None
    else:
        avg_processing_display = None
        avg_processing_note = t("kpi_avg_processing_time_pending")

    k1, k2, k3, k4 = st.columns(4)

    with k1:
        kpi(t("kpi_total_cases"), total_cases)

    with k2:
        kpi(t("kpi_avg_risk"), f"{avg_risk:.0f}")

    with k3:
        kpi(t("kpi_countries"), nationalities_count)

    with k4:
        kpi(
            t("kpi_avg_processing_time"),
            avg_processing_display,
            help_text=avg_processing_note,
        )


    st.write("")

    chart_col1, chart_col2 = st.columns(2)

    # Was st.bar_chart on a value_counts() Series. With one or two
    # categories it drew a y-axis of 0.0-2.0, a single full-width block,
    # and rotated the category label to vertical ("VALAIS" read top to
    # bottom). distribution() stays readable from one category upwards and
    # prints the count as a number instead of asking the reader to
    # estimate a bar height. Same data, same value_counts() call.
    with chart_col1:
        permit_counts = pd.Series([c[4] for c in cases]).value_counts()
        distribution(
            t("chart_by_permit_title"),
            permit_counts,
            t("chart_no_data"),
        )

    with chart_col2:
        canton_counts = pd.Series([c[3] for c in cases]).value_counts()
        distribution(
            t("chart_by_canton_title"),
            canton_counts,
            t("chart_no_data"),
        )


def _render_search_and_filters(company, lang):

    with st.expander(t("search_filter_expander"), expanded=False):


        saved = get_saved_filters(company)
        none_option = t("saved_filters_none_option")
        saved_options = [none_option] + [s[1] for s in saved]

        sf1, sf2, sf3 = st.columns([3, 1, 1])

        with sf1:
            chosen_saved_name = st.selectbox(
                t("saved_filters_label"),
                saved_options,
                key="dash_saved_filter_choice"
            )

        with sf2:
            st.write("")
            st.write("")
            if st.button(t("load_saved_filter_button"), key="dash_load_saved_filter_btn"):

                if chosen_saved_name != none_option:

                    match = next(
                        (s for s in saved if s[1] == chosen_saved_name),
                        None
                    )

                    if match:
                        loaded_filter = json.loads(match[2])

                        for key, value in loaded_filter.items():
                            st.session_state[key] = value

                        st.rerun()

        with sf3:
            st.write("")
            st.write("")
            if st.button("🗑", key="dash_delete_saved_filter_btn"):

                match = next(
                    (s for s in saved if s[1] == chosen_saved_name),
                    None
                )

                if match:
                    delete_saved_filter(match[0])
                    st.rerun()

        st.divider()


        search_text = st.text_input(
            t("search_placeholder"),
            value=st.session_state.get("dash_search_text", ""),
            key="dash_search_text"
        )


        f1, f2, f3, f4 = st.columns(4)

        with f1:
            filter_canton = st.selectbox(
                t("filter_canton_label"),
                CANTON_FILTER_OPTIONS,
                index=CANTON_FILTER_OPTIONS.index(
                    st.session_state.get("dash_filter_canton", "All")
                ),
                format_func=lambda v: (
                    t("filter_all_option") if v == "All"
                    else canton_label(v, lang)
                ),
                key="dash_filter_canton"
            )

        with f2:
            filter_permit = st.selectbox(
                t("filter_permit_label"),
                PERMIT_FILTER_OPTIONS,
                index=PERMIT_FILTER_OPTIONS.index(
                    st.session_state.get("dash_filter_permit", "All")
                ),
                format_func=lambda v: (
                    t("filter_all_option") if v == "All"
                    else permit_label(v, lang)
                ),
                key="dash_filter_permit"
            )

        with f3:
            filter_nationality = st.selectbox(
                t("filter_nationality_label"),
                NATIONALITY_FILTER_OPTIONS,
                index=NATIONALITY_FILTER_OPTIONS.index(
                    st.session_state.get("dash_filter_nationality", "All")
                ),
                format_func=lambda v: (
                    t("filter_all_option") if v == "All"
                    else nationality_label(v, lang)
                ),
                key="dash_filter_nationality"
            )

        with f4:
            filter_mode = st.selectbox(
                t("filter_mode_label"),
                MODE_FILTER_OPTIONS,
                index=MODE_FILTER_OPTIONS.index(
                    st.session_state.get("dash_filter_mode", "All")
                ),
                format_func=lambda v: (
                    t("filter_all_option") if v == "All"
                    else mode_label(v, lang)
                ),
                key="dash_filter_mode"
            )


        sort_labels = {
            "newest": t("sort_newest"),
            "oldest": t("sort_oldest"),
            "risk_desc": t("sort_risk_desc"),
            "risk_asc": t("sort_risk_asc"),
            "name": t("sort_name"),
        }

        sort_by = st.selectbox(
            t("sort_by_label"),
            SORT_OPTIONS,
            index=SORT_OPTIONS.index(
                st.session_state.get("dash_sort_by", "newest")
            ),
            format_func=lambda v: sort_labels[v],
            key="dash_sort_by"
        )


        st.divider()

        save1, save2 = st.columns([3, 1])

        with save1:
            new_filter_name = st.text_input(
                t("save_filter_name_placeholder"),
                key="dash_new_filter_name"
            )

        with save2:
            st.write("")
            st.write("")
            if st.button(t("save_filter_button"), key="dash_save_filter_btn"):

                if new_filter_name:

                    current_filter = {
                        "dash_search_text": search_text,
                        "dash_filter_canton": filter_canton,
                        "dash_filter_permit": filter_permit,
                        "dash_filter_nationality": filter_nationality,
                        "dash_filter_mode": filter_mode,
                        "dash_sort_by": sort_by,
                    }

                    save_filter(company, new_filter_name, current_filter)

                    st.success(t("filter_saved_success"))
                    st.rerun()

    return {
        "search_text": search_text,
        "canton": filter_canton,
        "permit": filter_permit,
        "nationality": filter_nationality,
        "mode": filter_mode,
        "sort_by": sort_by,
    }


def _apply_filters_and_sort(cases, filters):

    search_text = filters["search_text"].strip().lower()

    def matches(case):

        employee_name = case[1]
        nationality = case[2]
        canton = case[3]
        permit = case[4]
        mode = case[5]
        employer = case[6]

        if search_text:
            haystack = f"{employee_name} {employer}".lower()
            if search_text not in haystack:
                return False

        if filters["canton"] != "All" and canton != filters["canton"]:
            return False

        if filters["permit"] != "All" and permit != filters["permit"]:
            return False

        if (
            filters["nationality"] != "All"
            and nationality != filters["nationality"]
        ):
            return False

        if filters["mode"] != "All" and mode != filters["mode"]:
            return False

        return True

    filtered = [c for c in cases if matches(c)]

    sort_by = filters["sort_by"]

    if sort_by == "newest":
        filtered = sorted(filtered, key=lambda c: c[0], reverse=True)

    elif sort_by == "oldest":
        filtered = sorted(filtered, key=lambda c: c[0])

    elif sort_by == "risk_desc":
        filtered = sorted(
            filtered,
            key=lambda c: calculate_risk_from_rules(c)[0],
            reverse=True
        )

    elif sort_by == "risk_asc":
        filtered = sorted(
            filtered,
            key=lambda c: calculate_risk_from_rules(c)[0]
        )

    elif sort_by == "name":
        filtered = sorted(filtered, key=lambda c: c[1].lower())

    return filtered


def _safe_parse_date(date_str):

    if not date_str:
        return None

    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _render_notifications(company):

    with st.expander(t("notifications_expander"), expanded=False):

        events = get_recent_events_for_company(company, limit=15)

        if events:

            for event in events:

                _, _, _, description, created_at, employee_name = event

                time_part = (
                    created_at.split(" ")[1][:5]
                    if " " in created_at
                    else created_at
                )

                # escape(): employee_name and description are stored case
                # data going into raw HTML. description in particular is
                # assembled from document filenames and AI output.
                st.markdown(
                    f"🔔 **{escape(str(employee_name))}** "
                    f"— {escape(str(description))} "
                    f"<span style='color:gray;font-size:12px;'>"
                    f"({escape(str(time_part))})</span>",
                    unsafe_allow_html=True
                )

        else:

            st.info(t("no_notifications"))


def _render_task_inbox_and_calendar(company):

    pending_tasks = get_pending_tasks_for_company(company)

    with st.expander(t("task_inbox_expander"), expanded=False):

        if pending_tasks:

            # Was one flat st.write per task in query order, so an overdue
            # task looked exactly like one due next month and could sit
            # anywhere in a thirty-line list. Grouping by urgency turns the
            # same rows into a work queue. Nothing is filtered out: every
            # pending task still appears, and no task is modified.
            groups = group_tasks_by_urgency(pending_tasks, date.today())

            # Spelled out rather than built as t(f"task_urgency_{bucket}").
            # A key assembled from a variable cannot be verified without
            # running the page, so a missing one would reach the user as
            # raw source text - the defect tests/test_i18n_completeness.py
            # exists to prevent.
            bucket_labels = {
                OVERDUE: t("task_urgency_overdue"),
                DUE_TODAY: t("task_urgency_due_today"),
                DUE_THIS_WEEK: t("task_urgency_due_this_week"),
                LATER: t("task_urgency_later"),
                NO_DUE_DATE: t("task_urgency_no_due_date"),
            }

            for bucket, entries in groups:

                st.markdown(
                    badge_html(
                        bucket_labels[bucket],
                        level=URGENCY_LEVELS[bucket],
                        score=len(entries),
                    ),
                    unsafe_allow_html=True,
                )

                for due_date, employee_name, title in entries:

                    due_display = (
                        due_date.isoformat() if due_date else EMPTY_VALUE
                    )

                    record_row([
                        f"📋 {employee_name}",
                        title,
                        f"{t('task_due_date_label')}: {due_display}",
                    ])

        else:

            st.info(t("no_pending_tasks"))


    with st.expander(t("calendar_expander"), expanded=False):

        today = date.today()
        horizon = today + timedelta(days=7)

        upcoming = []

        for pt in pending_tasks:

            _, _, title, _, due_date, employee_name = pt
            parsed = _safe_parse_date(due_date)

            if parsed and today <= parsed <= horizon:
                upcoming.append((parsed, employee_name, title))

        upcoming.sort(key=lambda item: item[0])

        if upcoming:

            for parsed_date, employee_name, title in upcoming:
                st.write(f"📅 {parsed_date.isoformat()} — **{employee_name}**: {title}")

        else:

            st.info(t("no_upcoming_tasks"))


def _value_metric_labels():
    """
    Metric key -> translated label.

    Written out rather than built as t(f"value_metric_{key}"): a key
    assembled from a variable cannot be checked statically, so a missing
    one would reach the customer as raw source text - in the one document
    that exists to justify the price.
    """

    return {
        "documents_auto_processed": t("value_metric_documents_auto_processed"),
        "ai_operator_runs": t("value_metric_ai_operator_runs"),
        "workflow_transitions_recorded": t(
            "value_metric_workflow_transitions_recorded"
        ),
        "compliance_gaps_detected": t("value_metric_compliance_gaps_detected"),
        "tasks_completed": t("value_metric_tasks_completed"),
        "cases_managed": t("value_metric_cases_managed"),
    }


def _render_value_report(company):
    """
    The commercial artefact: what the system did for this customer, and
    what that is worth using the customer's own rates.

    The assumptions live in session state for now. Persisting them per
    tenant needs a table, which is a schema change - so until that is
    agreed, the figures are recomputed from whatever the user entered in
    this session rather than silently remembering a number nobody can see.
    """

    section_header(t("value_report_header"), t("value_report_intro"))

    # None means this customer has never stated their rates - which is
    # not the same as "their rates happen to equal our defaults". The
    # distinction is shown to the user, because a report is only
    # defensible while the reader recognises the numbers as their own.
    stored = get_value_assumptions_for_company(company)

    with st.expander(t("value_report_assumptions_expander"), expanded=not stored):

        st.caption(t("value_report_assumptions_help"))

        if not stored:
            st.warning(t("value_report_assumptions_unset"))

        a1, a2 = st.columns(2)

        with a1:
            minutes_review = st.number_input(
                t("value_assumption_document_review"),
                min_value=0.0, max_value=600.0, step=1.0,
                value=float(
                    (stored or {}).get("minutes_per_document_review")
                    or ValueAssumptions.minutes_per_document_review
                ),
                key="value_minutes_review",
            )

            minutes_request = st.number_input(
                t("value_assumption_document_request"),
                min_value=0.0, max_value=600.0, step=1.0,
                value=float(
                    (stored or {}).get("minutes_per_document_request")
                    or ValueAssumptions.minutes_per_document_request
                ),
                key="value_minutes_request",
            )

        with a2:
            minutes_status = st.number_input(
                t("value_assumption_status_update"),
                min_value=0.0, max_value=600.0, step=1.0,
                value=float(
                    (stored or {}).get("minutes_per_case_status_update")
                    or ValueAssumptions.minutes_per_case_status_update
                ),
                key="value_minutes_status",
            )

            # 0 means "not supplied" rather than "free": the report then
            # reports hours only. A franc figure derived from a rate the
            # customer never gave us is the least defensible number we
            # could print.
            hourly_cost = st.number_input(
                t("value_assumption_hourly_cost"),
                min_value=0.0, max_value=10000.0, step=5.0,
                value=float((stored or {}).get("hourly_cost") or 0.0),
                help=t("value_assumption_hourly_cost_help"),
                key="value_hourly_cost",
            )

            # A range, not a prefilled value. Somebody entering CHF 5 by
            # mistake should see immediately that it is outside anything
            # plausible, without the product having chosen a number on
            # their behalf.
            st.caption(
                t("value_rate_guidance").format(
                    low=SWISS_RATE_GUIDANCE_LOW,
                    high=SWISS_RATE_GUIDANCE_HIGH,
                )
            )

            # Optional, and absent by default. Without it no comparison
            # against cost is shown at all - the product does not know
            # its own price, and a vendor computing its own return is the
            # least credible figure in a procurement pack.
            platform_cost = st.number_input(
                t("value_assumption_platform_cost"),
                min_value=0.0, max_value=1000000.0, step=50.0,
                value=float((stored or {}).get("platform_cost_per_month") or 0.0),
                help=t("value_assumption_platform_cost_help"),
                key="value_platform_cost",
            )

        if st.button(t("value_report_save_assumptions"), key="value_save_btn"):

            save_value_assumptions_for_company(
                company,
                minutes_per_document_review=minutes_review,
                minutes_per_document_request=minutes_request,
                minutes_per_case_status_update=minutes_status,
                hourly_cost=hourly_cost if hourly_cost > 0 else None,
                platform_cost_per_month=platform_cost if platform_cost > 0 else None,
                updated_by=st.session_state.get("user", {}).get("username"),
            )

            st.success(t("value_report_assumptions_saved"))
            st.rerun()

        if stored and stored.get("updated_by"):
            st.caption(
                t("value_report_assumptions_provenance").format(
                    username=stored["updated_by"],
                    timestamp=str(stored["updated_at"])[:16],
                )
            )

    assumptions = ValueAssumptions(
        minutes_per_document_review=minutes_review,
        minutes_per_document_request=minutes_request,
        minutes_per_case_status_update=minutes_status,
        hourly_cost=hourly_cost if hourly_cost > 0 else None,
        platform_cost_per_month=platform_cost if platform_cost > 0 else None,
    )

    p1, p2 = st.columns(2)

    with p1:
        period_start = st.date_input(
            t("value_report_period_start"),
            value=date.today() - timedelta(days=90),
            key="value_period_start",
        )

    with p2:
        period_end = st.date_input(
            t("value_report_period_end"),
            value=date.today(),
            key="value_period_end",
        )

    if period_start > period_end:
        st.warning(t("value_report_invalid_period"))
        return

    report = build_value_report(
        company,
        assumptions=assumptions,
        period_start=datetime.combine(period_start, dt_time.min),
        period_end=datetime.combine(period_end, dt_time.max),
    )

    labels = _value_metric_labels()

    counts = {m.key: m.count for m in report.metrics}

    # A manager reads the top of this screen for about ten seconds. The
    # facts go first - they are exact - and the estimates after.
    row_one = st.columns(4)

    with row_one[0]:
        kpi(t("value_kpi_cases"), counts.get("cases_managed", 0))

    with row_one[1]:
        kpi(t("value_kpi_documents"), counts.get("documents_auto_processed", 0))

    with row_one[2]:
        kpi(t("value_kpi_ai_runs"), counts.get("ai_operator_runs", 0))

    with row_one[3]:
        kpi(
            t("value_kpi_compliance_gaps"),
            counts.get("compliance_gaps_detected", 0),
            help_text=t("value_kpi_compliance_gaps_note"),
        )

    st.write("")

    row_two = st.columns(4)

    with row_two[0]:
        kpi(t("value_report_hours_saved"), f"{report.total_hours_saved:g} h")

    with row_two[1]:
        kpi(
            t("value_report_cost_saved"),
            (
                f"{assumptions.currency} {report.total_cost_saved:,.0f}"
                if report.total_cost_saved is not None
                else None
            ),
            help_text=(
                None
                if report.total_cost_saved is not None
                else t("value_report_cost_needs_rate")
            ),
        )

    with row_two[2]:
        # Explicitly labelled a projection. It exists because a
        # three-month window understates a recurring saving, not to make
        # a small number look bigger.
        kpi(
            t("value_kpi_annualised"),
            (
                f"{report.annualised_hours_saved:g} h"
                if report.annualised_hours_saved is not None
                else None
            ),
            help_text=t("value_kpi_annualised_note"),
        )

    with row_two[3]:
        # "Value / cost", never "ROI". Return on investment implies a
        # financial model - a horizon, discounting, a view on what the
        # freed hours were worth instead. This is one division of two
        # numbers the customer typed in, and the label says so.
        kpi(
            t("value_kpi_ratio"),
            (
                f"{report.value_cost_ratio:g}×"
                if report.value_cost_ratio is not None
                else None
            ),
            help_text=(
                t("value_kpi_ratio_basis").format(
                    value=f"{assumptions.currency} {report.total_cost_saved:,.0f}",
                    cost=f"{assumptions.currency} {report.platform_cost_for_period:,.0f}",
                )
                if report.value_cost_ratio is not None
                else t("value_kpi_ratio_needs_cost")
            ),
        )

    st.write("")

    # Where the time actually came from. A manager can see at a glance
    # which activity carries the saving, which a table of three rows
    # makes them work out.
    time_by_activity = {
        labels.get(m.key, m.key): m.hours_saved
        for m in report.metrics
        if m.hours_saved
    }

    if time_by_activity:
        distribution(
            t("value_time_breakdown_title"),
            time_by_activity,
            t("chart_no_data"),
        )

    st.write("")

    # Estimates and counts are shown apart for the same reason the PDF
    # separates them: a reader who disputes an assumption should not be
    # led to discount the counts as well.
    for entry in report.metrics:

        if entry.hours_saved is None:
            continue

        # The basis is a sentence, not a status, so it is plain text.
        # A badge is a short pill; wrapping "47 document(s) × 12 min
        # manual review" in one would stretch it across the row and stop
        # reading as a badge at all.
        record_row([
            labels.get(entry.key, entry.key),
            f"{entry.count}",
            f"{entry.hours_saved:g} h",
            entry.basis or "",
        ])

    st.caption(t("value_report_outcomes_caption"))

    for entry in report.metrics:

        if entry.hours_saved is not None:
            continue

        record_row([
            labels.get(entry.key, entry.key),
            f"{entry.count}",
            entry.basis or "",
        ])

    st.write("")

    if st.button(t("value_report_generate_pdf"), key="value_report_pdf_btn"):

        pdf_path = f"value_report_{company}.pdf"

        export_value_report_pdf(pdf_path, report, labels=labels)

        with open(pdf_path, "rb") as handle:

            st.download_button(
                t("value_report_download_pdf"),
                handle,
                file_name=pdf_path,
                mime="application/pdf",
                key="value_report_download_btn",
            )


def _render_reports(company, cases, lang):

    with st.expander(t("reports_expander"), expanded=False):

        _render_value_report(company)

        st.divider()

        r1, r2 = st.columns(2)

        with r1:

            excel_bytes = export_cases_to_excel(cases, lang=lang)

            st.download_button(
                t("export_excel_button"),
                excel_bytes,
                file_name=f"{company}_cases.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="export_excel_btn"
            )

        with r2:

            if st.button(t("export_summary_pdf_button"), key="export_summary_pdf_btn"):

                pdf_path = f"company_summary_{company}.pdf"

                export_company_summary_pdf(pdf_path, company, cases, lang=lang)

                with open(pdf_path, "rb") as f:

                    st.download_button(
                        t("download_summary_pdf_button"),
                        f,
                        file_name=pdf_path,
                        key="download_summary_pdf_btn"
                    )


def show_dashboard():

    page_header(t("dashboard_header"), t("dashboard_subtitle"))

    lang = get_lang()

    user = st.session_state["user"]
    company = user["company"]

    cases = list_company_cases(company)

    if not cases:

        # Was st.info(one line) followed by return - a dead end on the
        # first screen every new account and every demo tenant sees. An
        # empty state has to say what the screen is for, why it is blank,
        # and what to do next.
        empty_state(
            title=t("dashboard_empty_title"),
            body=t("dashboard_empty_body"),
            steps=[
                t("dashboard_empty_step_create"),
                t("dashboard_empty_step_documents"),
                t("dashboard_empty_step_review"),
            ],
        )

        # The action lives here rather than in the component: the button
        # belongs to the page that knows where it should go.
        if st.button(t("dashboard_empty_cta"), type="primary",
                     key="empty_state_create_case"):
            st.session_state["page"] = "Create Case"
            st.rerun()

        return


    _render_kpis_and_charts(cases)

    st.write("")


    filters = _render_search_and_filters(company, lang)

    filtered_cases = _apply_filters_and_sort(cases, filters)

    if not filtered_cases:
        st.warning(t("no_matching_cases"))
        return


    section_header(t("cases_title"))

    for c in filtered_cases:

        case_id = c[0]
        employee_name = c[1]
        nationality = c[2]
        canton = c[3]
        permit = c[4]
        mode = c[5]
        employer = c[6]
        status = c[7]
        workflow_state = c[8]


        nationality_display = nationality_label(nationality, lang)
        canton_display = canton_label(canton, lang)
        permit_display = permit_label(permit, lang)
        mode_display = mode_label(mode, lang)
        workflow_state_display = workflow_state_label(
            normalize_legacy_state(workflow_state),
            lang
        )


        risk_level, _ = calculate_risk_from_rules(c)


        # Same thresholds as before. The hardcoded #ffcccc / #fff0b3 /
        # #d9f2d9 fills they used to set are gone: they were a second,
        # slightly different copy of the risk palette, so the same case
        # showed one colour here and another on the Case Detail page.
        # Both now render through the shared badge component.
        if risk_level >= 60:

            risk_text = t("risk_high")
            risk_badge_level = "danger"

        elif risk_level >= 30:

            risk_text = t("risk_medium")
            risk_badge_level = "warning"

        else:

            risk_text = t("risk_low")
            risk_badge_level = "success"


        user_can_delete = is_admin(user)

        # The summary and its actions now share one row instead of the
        # summary sitting above a separate button row - the same ragged
        # three-row pattern that made the task list unreadable.
        if user_can_delete:
            summary_col, col1, col2, col3 = st.columns([8, 1, 1, 1])
        else:
            summary_col, col1, col2 = st.columns([9, 1, 1])

        with summary_col:

            # Every value below is escaped by record_row(). Previously they
            # were interpolated straight into an f-string of raw HTML, so a
            # case saved with the employee name `<img src=x onerror=...>`
            # executed in the browser of every user who opened this
            # dashboard - and the employee name is user-entered.
            record_row([
                f"👤 {employee_name}",
                f"🌍 {nationality_display}",
                f"📍 {canton_display}",
                f"📄 {permit_display}",
                f"⚙️ {mode_display}",
                f"📌 {status}",
                f"🔄 {workflow_state_display}",
                (
                    "",
                    badge_html(
                        risk_text,
                        level=risk_badge_level,
                        score=risk_level,
                    ),
                ),
            ])


        with col1:

            if st.button(
                t("open_button"),
                key=f"open_{case_id}"
            ):

                st.session_state["selected_case"] = case_id
                st.session_state["page"] = "Case Detail"

                st.rerun()


        with col2:

            if st.button(
                t("edit_button"),
                key=f"edit_{case_id}"
            ):
                st.session_state["edit_case"] = case_id
                st.session_state["page"] = "Create Case"

                st.rerun()


        if user_can_delete:

            with col3:

                if st.button(
                    t("delete_button"),
                    key=f"delete_{case_id}"
                ):
                    st.session_state["confirm_delete"] = case_id


        if (
            user_can_delete
            and st.session_state.get("confirm_delete") == case_id
        ):


            st.warning(
                t("delete_confirm")
            )


            c1, c2 = st.columns(2)


            with c1:

                if st.button(
                    t("yes_button"),
                    key=f"yes_{case_id}"
                ):

                    delete_case_service(
                        case_id
                    )

                    st.session_state[
                        "confirm_delete"
                    ] = None

                    st.rerun()


            with c2:

                if st.button(
                    t("cancel_button"),
                    key=f"cancel_{case_id}"
                ):

                    st.session_state[
                        "confirm_delete"
                    ] = None

                    st.rerun()


    _render_task_inbox_and_calendar(company)


    _render_notifications(company)


    if can_export_reports(user):

            _render_reports(company,cases,lang)
