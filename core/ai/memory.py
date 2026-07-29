MAX_TURNS_PER_CASE = 12


class ConversationMemory:

    def __init__(self, max_turns=MAX_TURNS_PER_CASE):
        self._max_turns = max_turns
        self._history_by_case = {}

    def get_history(self, case_id):
        return list(self._history_by_case.get(case_id, []))

    def append_turn(self, case_id, user_goal, answer):
        history = self._history_by_case.setdefault(case_id, [])

        history.append({"role": "user", "content": user_goal})
        history.append({"role": "assistant", "content": answer})

        overflow = len(history) - (self._max_turns * 2)
        if overflow > 0:
            del history[:overflow]

    def reset(self, case_id):
        self._history_by_case.pop(case_id, None)


_default_memory = ConversationMemory()


def get_history(case_id):
    return _default_memory.get_history(case_id)


def append_turn(case_id, user_goal, answer):
    return _default_memory.append_turn(case_id, user_goal, answer)


def reset(case_id):
    return _default_memory.reset(case_id)
