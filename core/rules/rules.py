
import json
import os


_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DATA_DIR = os.path.join(_PROJECT_ROOT, "data")

CANTON_DATA_FILES = {
    "VALAIS": "canton_valais_rules.json",

}

_CACHE = {}


def get_canton_knowledge(canton_code):

    if canton_code in _CACHE:
        return _CACHE[canton_code]

    filename = CANTON_DATA_FILES.get(canton_code)

    if not filename:
        return None

    path = os.path.join(_DATA_DIR, filename)

    if not os.path.exists(path):
        return None

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    _CACHE[canton_code] = data

    return data


def get_scenario_note(canton_code, scenario_code):

    kb = get_canton_knowledge(canton_code)

    if not kb:
        return None

    return kb.get("scenario_notes", {}).get(scenario_code)


def get_permit_note(canton_code, permit_code):

    kb = get_canton_knowledge(canton_code)

    if not kb:
        return None

    return kb.get("permit_notes", {}).get(permit_code)
