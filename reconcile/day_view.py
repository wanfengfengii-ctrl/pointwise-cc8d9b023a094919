from dataclasses import dataclass

from handoff.ownership import Assignment, read_current_book
from ledger.postings import OfficialDay


@dataclass(frozen=True)
class DayView:
    assignment: Assignment
    book: OfficialDay


def load_day_view(warehouse, day):
    return DayView(*read_current_book(warehouse, day))
