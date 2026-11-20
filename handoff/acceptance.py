from dataclasses import dataclass

from intake.stations import StationDay
from ledger.postings import interpret_image
from ledger.region_store import book_key
from reconcile.discrepancies import check_day_balance
from reconcile.totals import recompute_totals
from storage import InconsistentBook


@dataclass(frozen=True)
class AcceptedHandoff:
    move_id: str
    day: StationDay
    source: str
    source_epoch: int
    target: str
    target_epoch: int
    frontier: int
    digest: str

    @property
    def identity(self):
        return self.move_id, self.day, self.source, self.source_epoch, self.target, self.target_epoch


def accept_candidate(target, record):
    if target.region != record.target:
        raise InconsistentBook('the installed candidate belongs to another region')
    day, target_epoch, move_id = record.day, record.target_epoch, record.move_id
    with target.write_transaction() as connection:
        header = target.header(connection, day, target_epoch)
        if header['inbound_move'] != move_id:
            raise InconsistentBook('the installed candidate belongs to another move')
        actual = target.read_image(connection, day, target_epoch)
        book = interpret_image(day, actual)
        check_day_balance(book, recompute_totals(book), record.source_epoch)
        digest = actual.digest()
        if header['accepted_digest'] not in (None, digest):
            raise InconsistentBook('durable target acceptance differs from the installed book')
        if header['accepted_digest'] is None:
            connection.execute(
                'UPDATE books SET accepted_digest = ? WHERE station = ? AND day = ? AND epoch = ?',
                (digest, *book_key(day, target_epoch)),
            )
    return AcceptedHandoff(move_id, day, record.source, record.source_epoch, target.region,
                           target_epoch, actual.frontier, digest)
