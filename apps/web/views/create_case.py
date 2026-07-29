import streamlit as st

from core.case.service import (
    create_case,
    update_case_service
)

from core.rules.risk import calculate_risk_from_rules
from core.documents.intake import generate_summary

from db.database import (
    case_statutory_dates,
    add_task,
    add_document,
    load_case,
    delete_tasks_for_case,
    delete_documents_for_case
)

from core.workflow.engine import build_workflow

from apps.web.utils.validators import validate_case_form
from apps.web.components.layout import page_header, section_header

from i18n.translator import t, get_lang
from i18n.labels import (
    canton_label,
    nationality_label,
    permit_label,
    mode_label
)


def show_create_case():

    page_header(t("create_edit_header"), t("create_edit_subtitle"))

    lang = get_lang()

    company = st.session_state["user"]["company"]

    edit_case_id = st.session_state.get("edit_case")

    widget_suffix = f"_{edit_case_id}" if edit_case_id else "_new"


    if edit_case_id:

        old_case = load_case(edit_case_id)

        employee_name_default = old_case[1]
        nationality_default = old_case[2]
        canton_default = old_case[3]
        permit_default = old_case[4]
        mode_default = old_case[5]
        employer_default = old_case[6]

        # Read through a named helper rather than old_case[16..18]: the
        # positions come from migration 0003 appending columns, and a bare
        # index here would silently feed the wrong value into a statutory
        # deadline if the table were ever reordered.
        stored_dates = case_statutory_dates(old_case)
        arrival_default = stored_dates["arrival_date"]
        contract_start_default = stored_dates["contract_start_date"]
        permit_expiry_default = stored_dates["permit_expiry_date"]

    else:

        employee_name_default = ""
        nationality_default = "EU"
        canton_default = "VAUD"
        permit_default = "NO_PERMIT"
        mode_default = "SME"
        employer_default = ""

        # None, not today(): these drive legal deadlines, and a prefilled
        # date is a date somebody will accept without reading.
        arrival_default = None
        contract_start_default = None
        permit_expiry_default = None


    # Inside st.form, so nothing is submitted until the button is
    # pressed. Without it every select box change re-ran the whole page -
    # recomputing risk and re-querying - and there was no single moment
    # at which the input could be checked as a whole.
    form = st.form(key=f"case_form{widget_suffix}")

    with form:

        st.caption(t("form_required_note"))

        employee_name = st.text_input(
            f"{t('employee_name_label')} *",
            value=employee_name_default,
            key=f"employee_name{widget_suffix}",
            placeholder=t("employee_name_placeholder"),
        )

        employer = st.text_input(
            f"{t('employer_label')} *",
            value=employer_default,
            key=f"employer{widget_suffix}",
        )

    nationality_options = ["EU", "NON_EU"]
    canton_options = ["VAUD", "VALAIS"]
    permit_list = ["NO_PERMIT", "N", "F", "S", "L", "B", "C", "G"]
    mode_list = ["SME", "RELOCATION", "RECRUITMENT"]

    with form:

        # Two per row: six stacked full-width selects made the form feel
        # longer than it is, and these pair naturally.
        left, right = st.columns(2)

        with left:
            nationality = st.selectbox(
                t("nationality_label"),
                nationality_options,
                index=nationality_options.index(nationality_default),
                format_func=lambda code: nationality_label(code, lang),
                key=f"nationality{widget_suffix}"
            )

            permit = st.selectbox(
                t("permit_label"),
                permit_list,
                index=permit_list.index(permit_default),
                format_func=lambda code: permit_label(code, lang),
                key=f"permit{widget_suffix}"
            )

        with right:
            canton = st.selectbox(
                t("canton_label"),
                canton_options,
                index=canton_options.index(canton_default),
                format_func=lambda code: canton_label(code, lang),
                key=f"canton{widget_suffix}"
            )

            job_type = st.selectbox(
                t("business_mode_label"),
                mode_list,
                index=mode_list.index(mode_default),
                format_func=lambda code: mode_label(code, lang),
                key=f"mode{widget_suffix}"
            )

        # Optional, and left empty by default on purpose. These drive
        # statutory deadlines, so a guessed value is worse than none: the
        # obligation engine reports "not recorded" rather than computing a
        # legal date from something that only looks like the right one.
        st.divider()
        section_header(t("statutory_dates_header"), t("statutory_dates_help"))

        date_left, date_middle, date_right = st.columns(3)

        with date_left:
            arrival_date = st.date_input(
                t("arrival_date_label"),
                value=arrival_default,
                format="YYYY-MM-DD",
                key=f"arrival_date{widget_suffix}",
            )

        with date_middle:
            contract_start_date = st.date_input(
                t("contract_start_date_label"),
                value=contract_start_default,
                format="YYYY-MM-DD",
                key=f"contract_start_date{widget_suffix}",
            )

        with date_right:
            permit_expiry_date = st.date_input(
                t("permit_expiry_date_label"),
                value=permit_expiry_default,
                format="YYYY-MM-DD",
                key=f"permit_expiry_date{widget_suffix}",
            )


    if edit_case_id:
        button_text = t("update_case_button")
    else:
        button_text = t("create_case_button")

    with form:
        submitted = st.form_submit_button(button_text, type="primary")

    # Outside the form: a cancel must not be a submission, and a form
    # submit button always submits.
    if edit_case_id:

        if st.button(t("cancel_edit_button"), key=f"cancel_edit{widget_suffix}"):

            st.session_state.pop("edit_case")
            st.session_state["page"] = "Dashboard"
            st.rerun()


    if submitted:

        # The form previously wrote whatever it was given. An empty
        # employee name saved silently, which is how the database came to
        # hold cases identified by a single lowercase word. A case is a
        # compliance record about a named person; incomplete is worse
        # than absent, because it looks finished.
        validation = validate_case_form(
            employee_name=employee_name,
            employer=employer,
            nationality=nationality,
            canton=canton,
            permit=permit,
            business_mode=job_type,
            valid_nationalities=nationality_options,
            valid_cantons=canton_options,
            valid_permits=permit_list,
            valid_modes=mode_list,
        )

        for message in validation.errors.values():
            st.error(message)

        for message in validation.warnings.values():
            st.warning(message)

        if not validation.is_valid:
            # Nothing is written, and every problem is shown at once so
            # the operator does not fix them one round trip at a time.
            return

        # Stored trimmed: " zohre " and "zohre" are the same person, and
        # the document-validation step compares this against names read
        # out of PDFs.
        employee_name = employee_name.strip()
        employer = employer.strip()

        mode = job_type


        temp_case_for_risk = (
            None,
            employee_name,
            nationality,
            canton,
            permit,
            mode
        )

        risk, trace = calculate_risk_from_rules(temp_case_for_risk)

        if risk >= 60:
            risk_label = "HIGH"
        elif risk >= 30:
            risk_label = "MEDIUM"
        else:
            risk_label = "LOW"


        summary = generate_summary(
            employee_name,
            nationality,
            canton,
            permit,
            mode,
            risk_label
        )


        workflow = build_workflow(
            nationality=nationality,
            permit=permit,
            canton=canton,
            mode=mode
        )


        docs = [
            "Passport Copy",
            "Employment Contract",
            "CV"
        ]


        if nationality == "NON_EU":
            docs.append("Entry Visa")

        if permit in ["L", "B", "C"]:
            docs.append("Permit Application")

        if canton == "VALAIS":
            docs.append("Commune Registration")

        if canton == "VAUD":
            docs.append("Residence Registration")


        if edit_case_id:

            update_case_service(
                edit_case_id,
                {
                    "employee_name": employee_name,
                    "nationality": nationality,
                    "canton": canton,
                    "permit": permit,
                    "business_mode": mode,
                    "employer": employer,
                    "risk_level": risk,
                    "ai_summary": summary,
                    "arrival_date": arrival_date,
                    "contract_start_date": contract_start_date,
                    "permit_expiry_date": permit_expiry_date
                }
            )

            delete_tasks_for_case(edit_case_id)
            delete_documents_for_case(edit_case_id)

            for step in workflow:
                add_task(edit_case_id, step)

            for d in docs:
                add_document(edit_case_id, d)

            st.success(t("case_updated_success"))

            st.session_state.pop("edit_case")

            st.session_state["selected_case"] = edit_case_id
            st.session_state["page"] = "Case Detail"

            st.rerun()


        else:

            case_id = create_case(
                employee_name,
                nationality,
                canton,
                permit,
                mode,
                employer,
                company,
                risk,
                summary,
                "admin",
                arrival_date=arrival_date,
                contract_start_date=contract_start_date,
                permit_expiry_date=permit_expiry_date
            )

            for step in workflow:
                add_task(case_id, step)

            for d in docs:
                add_document(case_id, d)

            st.success(t("case_created_success"))

            st.session_state["selected_case"] = case_id
            st.session_state["page"] = "Case Detail"

            st.rerun()
