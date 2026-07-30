"""
Access to the per-canton knowledge bases in ``data/``.

Which cantons exist is decided in :mod:`core.cantons`, not here. This
module used to keep its own dictionary::

    CANTON_DATA_FILES = {"VALAIS": "canton_valais_rules.json"}

which was the seventh place in the codebase with an opinion about the
supported cantons, and it disagreed with the other six - the case form
offered Vaud, this mapping did not have it, and ``get_canton_knowledge``
quietly returned ``None`` while every caller carried on.

One list, derived from the files themselves. See core/cantons.py.
"""

import json
import os

from core.cantons import is_selectable, knowledge_base_filename


_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DATA_DIR = os.path.join(_PROJECT_ROOT, "data")

_CACHE = {}


def get_canton_knowledge(canton_code):
    """
    The knowledge base for a canton, or None if it is not covered.

    Still returns None rather than raising, because the callers below are
    lookups for optional guidance notes - a missing note is a blank
    section, not a failure. Paths that compute something a customer will
    act on should call ``core.cantons.require_supported`` first, which
    does raise.
    """

    if not canton_code:
        return None

    canton_code = canton_code.upper()

    if canton_code in _CACHE:
        return _CACHE[canton_code]

    if not is_selectable(canton_code):
        return None

    path = os.path.join(_DATA_DIR, knowledge_base_filename(canton_code))

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
