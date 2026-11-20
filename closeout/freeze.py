from dataclasses import dataclass

from closeout.facts import capture_facts
from intake.stations import StationDay
from reconcile.day_view import load_day_view
from reconcile.discrepancies import check_day_balance
from reconcile.totals import recompute_totals


@dataclass(frozen=True)
class FreezeResult:
    number: int
    day: StationDay
    litres: int


def freeze(warehouse, day):
    view = load_day_view(warehouse, day)
    book, route = view.book, view.assignment
    check_day_balance(book, recompute_totals(book), route.epoch)
    facts = warehouse.archive.save_frozen(capture_facts(book, route.region, route.epoch))
    return FreezeResult(facts.number, facts.day, facts.current_litres)
