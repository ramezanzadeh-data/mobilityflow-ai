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


    if canton == "VALAIS":
        missing.append("Commune Registration Form")
        risks.append("Valais requires commune registration")

    if canton == "VAUD":
        risks.append("Vaud canton requires strict onboarding timeline")


    if permit == "B":
        risks.append("Permit B requires employment validation")


    if mode == "RELOCATION":
        risks.append("Relocation mode requires multi-step approval flow")


    return {
        "missing_documents": list(set(missing)),
        "risk_factors": risks,
        "compliance_score": max(0, 100 - len(missing)*10 - len(risks)*5)
    }
