def detect_mode(nationality, permit, job_type):


    if job_type == "High Volume":
        return "RECRUITMENT"


    if nationality == "NON_EU":
        return "RELOCATION"


    return "SME"


def calculate_risk(nationality, permit):

    score = 0

    if nationality == "NON_EU":
        score += 40

    if permit == "B":
        score += 20

    if score >= 60:
        return "HIGH"

    elif score >= 30:
        return "MEDIUM"

    return "LOW"


def generate_summary(name,
                     nationality,
                     canton,
                     permit,
                     mode,
                     risk):

    return f"""
Employee : {name}

Nationality : {nationality}

Canton : {canton}

Permit : {permit}

Business Mode : {mode}

Risk Level : {risk}

AI Recommendation

• Review required documents
• Verify canton-specific requirements
• Prepare commune registration
• Generate standard emails
"""