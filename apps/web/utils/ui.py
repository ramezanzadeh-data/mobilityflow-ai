"""
Small presentation-layer helpers shared by the Streamlit pages.

Strictly view concerns: nothing here reads the database, calls a service,
or makes a decision the backend already makes. Anything that does belongs
in core/ instead.
"""

from itertools import count


class StepNumbering:
    """
    Hands out consecutive display numbers for a list of steps whose
    membership is decided at render time.

    Numbering conditionally-rendered steps with literals produces visible
    gaps: the AI operator panel emitted a hardcoded ``1..9`` while steps
    5, 6, 7 and 9 only render when the corresponding result is present, so
    a run that created no tasks displayed ``1, 2, 3, 4, 6, 7, 8`` to the
    user. A reader cannot tell a skipped step from a lost one, and in a
    compliance product "something is missing from this report" is an
    expensive impression.

    Because a number is only consumed when a step actually renders, the
    sequence is always contiguous.

        steps = StepNumbering()
        st.write(f"{steps.next()} Extraction method: ...")
        if warnings:
            st.write(f"{steps.next()} Warnings: ...")

    Not thread-safe, and deliberately so: one instance belongs to one
    render pass of one page.
    """

    def __init__(self, start: int = 1, suffix: str = "."):
        self._counter = count(start)
        self._suffix = suffix

    def next(self) -> str:
        """Return the next label, e.g. ``"1."``, then ``"2."``."""

        return f"{next(self._counter)}{self._suffix}"

    def peek_used(self) -> int:
        """
        Number of labels handed out so far.

        Lets a caller render a heading such as "7 checks performed"
        without tracking the count separately.
        """

        # count() has no non-consuming read, so derive it from the next
        # value without advancing the shared iterator.
        current = next(self._counter)
        self._counter = count(current)

        return current - 1
