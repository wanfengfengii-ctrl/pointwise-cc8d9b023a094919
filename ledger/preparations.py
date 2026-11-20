from dataclasses import dataclass

from intake.stations import StationDay
from ledger.region_store import book_key
from storage import Conflict, InconsistentBook, litre_text, parse_litres


@dataclass(frozen=True)
class PreparedCorrection:
    day: StationDay
    correction_id: str
    region: str
    epoch: int
    litres: int


def bind_correction_request(directory, day, correction_id, litres):
    identity = (*day.key, litre_text(litres))
    with directory.transaction(write=True) as connection:
        row = connection.execute(
            'SELECT station, day, new_litres FROM correction_requests WHERE correction_id = ?',
            (correction_id,),
        ).fetchone()
        if row is None:
            connection.execute('INSERT INTO correction_requests VALUES (?, ?, ?, ?)', (correction_id, *identity))
        elif tuple(row) != identity:
            raise Conflict(f'correction {correction_id} has different parameters')


def load_preparation(connection, day, epoch, correction_id):
    row = connection.execute(
        '''SELECT new_litres FROM preparations WHERE station = ? AND day = ? AND epoch = ?
           AND correction_id = ?''', (*book_key(day, epoch), correction_id),
    ).fetchone()
    return None if row is None else parse_litres(row['new_litres'])


def prepare_correction(store, request):
    with store.write_transaction() as connection:
        if store.region != request.region:
            raise InconsistentBook('preparation store differs from the requested region')
        store.header(connection, request.day, request.epoch)
        key = book_key(request.day, request.epoch)
        existing = load_preparation(connection, request.day, request.epoch, request.correction_id)
        if existing is None:
            connection.execute('INSERT INTO preparations VALUES (?, ?, ?, ?, ?)',
                               (*key, request.correction_id, litre_text(request.litres)))
        elif existing != request.litres:
            raise Conflict(f'correction {request.correction_id} has different prepared parameters')
    return request
