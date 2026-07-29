

def calculate_risk_from_rules(case):

    nationality = case[2]
    canton = case[3]
    permit = case[4]
    business_mode = case[5]

    score = 0
    breakdown = []


    if nationality == "NON_EU":
        score += 40
        breakdown.append("+40 NON_EU permit process")

    elif nationality == "EU":
        score += 5
        breakdown.append("+5 EU process")


    permit_scores = {
        "NO_PERMIT": 30,
        "N": 60,
        "F": 45,
        "S": 35,
        "L": 20,
        "B": 15,
        "C": 5,
        "G": 20
    }

    if permit in permit_scores:
        score += permit_scores[permit]
        breakdown.append(f"+{permit_scores[permit]} Permit {permit}")


    # Only cantons the product actually covers contribute a score.
    #
    # There used to be an `elif canton == "VAUD": score += 5` here. Vaud
    # has no knowledge base in data/, so that five came from nowhere -
    # and a risk score assembled partly from invented numbers is not a
    # weaker score, it is a different kind of object. Nothing on screen
    # distinguished it from the Valais figure.
    #
    # An uncovered canton now contributes nothing and says so, which is
    # the honest answer: the product has no view on it.
    if canton == "VALAIS":
        score += 10
        breakdown.append("+10 Valais compliance")


    if business_mode == "RELOCATION":
        score += 20
        breakdown.append("+20 Relocation workflow")

    elif business_mode == "RECRUITMENT":
        score += 10
        breakdown.append("+10 Recruitment workflow")

    elif business_mode == "SME":
        score += 5
        breakdown.append("+5 SME workflow")

    score = min(score, 100)

    trace = {
        "total": score,
        "breakdown": breakdown
    }

    return score, trace
