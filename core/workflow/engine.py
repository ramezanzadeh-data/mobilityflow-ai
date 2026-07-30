def build_workflow(nationality, permit, canton, mode):
    workflow = [
        "Initial case review",
        "Collect identity documents",
        "Verify employment contract"
    ]


    if nationality == "NON_EU":

        workflow.extend([

            "Validate visa eligibility",

            "Check immigration quota",

            "Prepare entry authorization"

        ])

    else:

        workflow.append(

            "Process EU registration"

        )


    if permit in ["NO_PERMIT", "N", "F", "S"]:

        workflow.extend([

            "Prepare permit application",

            "Collect biometric data",

            "Schedule cantonal appointment"

        ])

    elif permit in ["L", "B"]:

        workflow.extend([

            "Validate existing permit",

            "Employer eligibility verification"

        ])

    elif permit == "C":

        workflow.append(

            "Validate permanent residence"

        )

    elif permit == "G":

        workflow.extend([

            "Cross-border worker verification",

            "Tax registration",

            "Social insurance registration"

        ])


    # Canton-specific steps come from a canton with a knowledge base.
    #
    # The Vaud branch that stood here added one commune registration step
    # with nothing behind it - no data/canton_vaud_rules.json, no source,
    # no review. A user in Vaud was handed a checklist that looked like
    # the Valais one and was not. Removed rather than left in place: it
    # was not partial support, it was a guess presented as procedure.
    if canton == "VALAIS":

        workflow.extend([

            "Commune registration (Valais)",

            "Cantonal approval"

        ])


    if mode == "RELOCATION":

        workflow.extend([

            "Housing registration",

            "Family relocation support"

        ])

    elif mode == "RECRUITMENT":

        workflow.append(

            "Employer sponsorship verification"

        )

    elif mode == "SME":

        workflow.append(

            "SME compliance review"

        )


    workflow.append(

        "Close relocation case"

    )

    return workflow
