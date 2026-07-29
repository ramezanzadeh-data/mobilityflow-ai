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


    if canton == "VALAIS":

        workflow.extend([

            "Commune registration (Valais)",

            "Cantonal approval"

        ])

    elif canton == "VAUD":

        workflow.extend([

            "Commune registration (Vaud)"

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
