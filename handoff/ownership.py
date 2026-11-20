import sqlite3
from dataclasses import dataclass

from intake.stations import StationDay, require_day
from ledger.postings import read_official_day
from storage import Conflict, InconsistentBook, NotFound, Unavailable


@dataclass(frozen=True)
class Assignment:
    day: StationDay
    batch_id: str
    original_region: str
    region: str
    epoch: int
    published: bool


@dataclass(frozen=True)
class MoveResult:
    move_id: str
    day: StationDay
    source: str
    source_epoch: int
    target: str
    target_epoch: int
    frontier: int


def _assignment(day, row):
    if row is None:
        raise NotFound(f'unknown station day {day.key}')
    return Assignment(day, row['batch_id'], row['original_region'], row['region'], row['epoch'], bool(row['published']))


def get_assignment(directory, day, connection=None):
    require_day(day)
    current = _assignment(day, directory.get_assignment(day, connection))
    if not current.published:
        raise NotFound(f'station day {day.key} has not finished opening')
    return current


def reserve_initial_assignment(directory, day, batch_id, region):
    with directory.transaction(write=True) as connection:
        connection.execute(
            '''INSERT INTO assignments VALUES (?, ?, ?, ?, ?, 1, 0)
               ON CONFLICT (station, day) DO NOTHING''', (*day.key, batch_id, region, region),
        )
        reserved = _assignment(day, directory.get_assignment(day, connection))
        if (reserved.batch_id, reserved.original_region) != (batch_id, region):
            raise Conflict('opening differs from the original batch or region')
        return reserved


def publish_initial_assignment(directory, reserved, opened_image, batch, initial):
    with directory.transaction(write=True) as connection:
        current = _assignment(reserved.day, directory.get_assignment(reserved.day, connection))
        if (current.batch_id, current.original_region) != (reserved.batch_id, reserved.original_region):
            raise Conflict('initial assignment no longer matches the reservation')
        if current.published:
            return current
        if (opened_image.batch, opened_image.initial_litres, opened_image.current_litres,
                opened_image.frontier, opened_image.postings, opened_image.receipts) != (batch, initial, initial, 0, (), ()):
            raise InconsistentBook('the initial book is incomplete')
        connection.execute('UPDATE assignments SET published = 1 WHERE station = ? AND day = ?', reserved.day.key)
        return _assignment(reserved.day, directory.get_assignment(reserved.day, connection))


def completed_move(record):
    if record.result_frontier is None:
        return None
    return MoveResult(record.move_id, record.day, record.source, record.source_epoch,
                      record.target, record.target_epoch, record.result_frontier)


def publish_move(directory, requested, accepted):
    with directory.transaction(write=True) as connection:
        record = directory.get_move(requested.move_id, connection)
        if record is None:
            raise Conflict('move registration is missing')
        done = completed_move(record)
        if done is not None:
            return done
        expected = (record.move_id, record.day, record.source, record.source_epoch, record.target, record.target_epoch)
        if accepted.identity != expected:
            raise Conflict('target acceptance does not match the pending move')
        current = get_assignment(directory, record.day, connection)
        if (current.region, current.epoch) != (record.source, record.source_epoch):
            raise Conflict('pending move no longer owns its source assignment')
        connection.execute('UPDATE assignments SET region = ?, epoch = ? WHERE station = ? AND day = ?',
                           (record.target, record.target_epoch, *record.day.key))
        connection.execute('UPDATE moves SET result_frontier = ?, result_digest = ? WHERE move_id = ?',
                           (accepted.frontier, accepted.digest, record.move_id))
        return completed_move(directory.get_move(record.move_id, connection))


def read_current_book(warehouse, day):
    while True:
        route = get_assignment(warehouse.directory, day)
        try:
            book = read_official_day(warehouse.region(route.region), day, route.epoch)
        except (Unavailable, InconsistentBook, sqlite3.Error):
            if get_assignment(warehouse.directory, day) == route:
                raise
            continue
        if get_assignment(warehouse.directory, day) == route:
            return route, book
