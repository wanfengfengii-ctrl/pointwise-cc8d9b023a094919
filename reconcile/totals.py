from dataclasses import dataclass

from ledger.postings import OfficialDay


@dataclass(frozen=True)
class RecomputedTotals:
    per_posting: tuple[tuple[int, str, int], ...]
    net_litres: int
    closing_litres: int


def recompute_totals(book: OfficialDay):
    per_posting = tuple((posting.sequence, posting.correction_id, posting.new_litres - posting.old_litres)
                        for posting in book.postings)
    net = sum(delta for _, _, delta in per_posting)
    return RecomputedTotals(per_posting, net, book.initial_litres + net)
