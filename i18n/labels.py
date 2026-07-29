"""
Display names for the domain's controlled vocabularies.

Separate from translations/*.json because these are not interface copy -
they are the names of legal instruments. "Permit B" is
"Aufenthaltsbewilligung B" in German and "permis B de séjour" in French,
and these are the terms a Swiss HR specialist reads most closely. Getting
one wrong is worse than leaving it in English: B (residence) and C
(settlement) confer different rights, and a mislabelled permit in a
compliance tool is a mistake a customer will notice immediately.

Every function already accepted a ``lang`` argument and ignored it, so
the whole interface stayed English no matter what was selected. They now
honour it, falling back to English for any language that does not define
a term.

⚠️ The German and French permit names below need review by a Swiss
immigration specialist before this product is sold in those languages.
They follow the standard federal terminology as commonly used, but
"commonly used" is not the standard this product is held to elsewhere -
see data/obligations.json for the same principle applied to deadlines.
"""

from i18n.translator import DEFAULT_LANGUAGE, normalize_language


CANTON_LABELS = {
    # Vaud is kept although the product no longer covers it. Cases
    # created while it was on the menu still exist, and a record that
    # displays its canton as a raw code - or not at all - is a record the
    # customer cannot recognise. Coverage is decided in core/cantons.py;
    # this table only says how a code is written in each language.
    "en": {"VAUD": "Vaud", "VALAIS": "Valais"},
    # Canton names are proper nouns, but each has an endonym in the
    # relevant language and Swiss users expect their own.
    "de": {"VAUD": "Waadt", "VALAIS": "Wallis"},
    "fr": {"VAUD": "Vaud", "VALAIS": "Valais"},
}

NATIONALITY_LABELS = {
    "en": {"EU": "EU / EFTA", "NON_EU": "Non-EU / EFTA"},
    "de": {"EU": "EU / EFTA", "NON_EU": "Nicht-EU / EFTA"},
    "fr": {"EU": "UE / AELE", "NON_EU": "Hors UE / AELE"},
}

PERMIT_LABELS = {
    "en": {
        "NO_PERMIT": "No permit",
        "N": "Permit N (Asylum seeker)",
        "F": "Permit F (Temporary admission)",
        "S": "Permit S (Protection status)",
        "L": "Permit L (Short-term)",
        "B": "Permit B (Residence)",
        "C": "Permit C (Settlement)",
        "G": "Permit G (Cross-border)",
    },
    "de": {
        "NO_PERMIT": "Keine Bewilligung",
        "N": "Ausweis N (Asylsuchende)",
        "F": "Ausweis F (Vorläufig aufgenommen)",
        "S": "Ausweis S (Schutzbedürftige)",
        "L": "Ausweis L (Kurzaufenthalt)",
        "B": "Ausweis B (Aufenthalt)",
        "C": "Ausweis C (Niederlassung)",
        "G": "Ausweis G (Grenzgänger)",
    },
    "fr": {
        "NO_PERMIT": "Aucun permis",
        "N": "Permis N (Requérant d'asile)",
        "F": "Permis F (Admission provisoire)",
        "S": "Permis S (Statut de protection)",
        "L": "Permis L (Courte durée)",
        "B": "Permis B (Séjour)",
        "C": "Permis C (Établissement)",
        "G": "Permis G (Frontalier)",
    },
}

MODE_LABELS = {
    "en": {
        "SME": "SME",
        "RELOCATION": "Relocation",
        "RECRUITMENT": "Recruitment",
    },
    "de": {
        "SME": "KMU",
        "RELOCATION": "Umzug",
        "RECRUITMENT": "Rekrutierung",
    },
    "fr": {
        "SME": "PME",
        "RELOCATION": "Relocation",
        "RECRUITMENT": "Recrutement",
    },
}

RISK_LEVEL_LABELS = {
    "en": {"HIGH": "HIGH", "MEDIUM": "MEDIUM", "LOW": "LOW"},
    "de": {"HIGH": "HOCH", "MEDIUM": "MITTEL", "LOW": "NIEDRIG"},
    "fr": {"HIGH": "ÉLEVÉ", "MEDIUM": "MOYEN", "LOW": "FAIBLE"},
}

WORKFLOW_STATE_LABELS = {
    "en": {
        "DRAFT": "Draft",
        "SUBMITTED": "Submitted",
        "REVIEW": "Review",
        "EMPLOYER": "Employer",
        "AUTHORITIES": "Authorities",
        "DECISION": "Decision",
        "COMPLETED": "Completed",
    },
    "de": {
        "DRAFT": "Entwurf",
        "SUBMITTED": "Eingereicht",
        "REVIEW": "Prüfung",
        "EMPLOYER": "Arbeitgeber",
        "AUTHORITIES": "Behörden",
        "DECISION": "Entscheid",
        "COMPLETED": "Abgeschlossen",
    },
    "fr": {
        "DRAFT": "Brouillon",
        "SUBMITTED": "Soumis",
        "REVIEW": "Examen",
        "EMPLOYER": "Employeur",
        "AUTHORITIES": "Autorités",
        "DECISION": "Décision",
        "COMPLETED": "Terminé",
    },
}


def _lookup(table, code, lang):
    """
    Resolve one code in one language.

    Falls through language -> English -> the raw code. The raw code is
    the last resort and is deliberately not hidden: an unmapped value
    showing as ``NO_PERMIT`` is a visible bug, whereas silently rendering
    it as an empty string would hide a gap in a compliance screen.
    """

    language = normalize_language(lang)

    value = table.get(language, {}).get(code)

    if value is None:
        value = table.get(DEFAULT_LANGUAGE, {}).get(code)

    return value if value is not None else code


def canton_label(code, lang=None):
    return _lookup(CANTON_LABELS, code, lang)


def nationality_label(code, lang=None):
    return _lookup(NATIONALITY_LABELS, code, lang)


def permit_label(code, lang=None):
    return _lookup(PERMIT_LABELS, code, lang)


def mode_label(code, lang=None):
    return _lookup(MODE_LABELS, code, lang)


def risk_level_label(code, lang=None):
    return _lookup(RISK_LEVEL_LABELS, code, lang)


def workflow_state_label(code, lang=None):
    return _lookup(WORKFLOW_STATE_LABELS, code, lang)
