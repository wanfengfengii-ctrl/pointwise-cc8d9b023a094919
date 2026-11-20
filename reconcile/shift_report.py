from dataclasses import dataclass

from intake.stations import StationDay
from ledger.postings import Posting
from reconcile.day_view import load_day_view
from reconcile.discrepancies import ReconciliationError, check_day_balance
from reconcile.totals import recompute_totals
from storage import InconsistentBook


@dataclass(frozen=True)
class ShiftReport:
    day: StationDay
    region: str
    epoch: int
    batch_id: str
    initial_litres: int
    current_litres: int
    net_litres: int
    postings: tuple[Posting, ...]


def reconcile_day(warehouse, day):
    try:
        view = load_day_view(warehouse, day)
    except InconsistentBook as error:
        raise ReconciliationError(str(error)) from error
    book, route = view.book, view.assignment
    totals = recompute_totals(book)
    check_day_balance(book, totals, route.epoch)
    return ShiftReport(day, route.region, route.epoch, book.batch.batch_id, book.initial_litres,
                       book.current_litres, totals.net_litres, book.postings)
