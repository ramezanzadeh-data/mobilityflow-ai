def analyze_documents(case, documents):

    nationality = case[2]
    canton = case[3]
    permit = case[4]
    mode = case[5]

    missing = []
    risks = []


    base_docs = [
        "Passport Copy",
        "Employment Contract",
        "CV",
    ]

    for d in base_docs:
        if not any(d.lower() in doc[2].lower() for doc in documents):
            missing.append(d)


    if nationality == "NON_EU":
        if not any("visa" in doc[2].lower() for doc in documents):
            missing.append("Entry Visa Documentation")
            risks.append("NON-EU compliance risk: visa missing")


    # See core/cantons.py. The Vaud line removed from here asserted a
    # "strict onboarding timeline" that no source in this repository
    # establishes - a compliance claim invented in a docstring-free
    # if-statement and shown to the user as a risk.
    if canton == "VALAIS":

        # The existence check was absent here, and only here. Every other
        # requirement above is guarded by `if not any(...)`; this one
        # appended unconditionally, so Commune Registration Form was
        # reported missing on every Valais case forever - including
        # immediately after the user uploaded it.
        #
        # It reads as a small omission and was not. The product is Valais
        # only, so every case in it carried one requirement that could
        # never be discharged: the compliance score could not reach 100,
        # the checklist could not be cleared, and any gate that asks
        # "are all documents present" answered no permanently. The user's
        # own upload was the correction that never took effect.
        if not any("commune registration" in doc[2].lower() for doc in documents):
            missing.append("Commune Registration Form")

        risks.append("Valais requires commune registration")


    if permit == "B":
        risks.append("Permit B requires employment validation")


    if mode == "RELOCATION":
        risks.append("Relocation mode requires multi-step approval flow")


    return {
        "missing_documents": list(set(missing)),
        "risk_factors": risks,
        "compliance_score": max(0, 100 - len(missing)*10 - len(risks)*5)
    }
