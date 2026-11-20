from dataclasses import dataclass

from intake.stations import StationDay
from storage import Database


_SCHEMA = (
    '''CREATE TABLE IF NOT EXISTS assignments (
        station TEXT NOT NULL, day TEXT NOT NULL, batch_id TEXT NOT NULL,
        original_region TEXT NOT NULL, region TEXT NOT NULL, epoch INTEGER NOT NULL,
        published INTEGER NOT NULL CHECK (published IN (0, 1)), PRIMARY KEY (station, day)
    )''',
    '''CREATE TABLE IF NOT EXISTS moves (
        move_id TEXT PRIMARY KEY, station TEXT NOT NULL, day TEXT NOT NULL,
        source TEXT NOT NULL, source_epoch INTEGER NOT NULL, target TEXT NOT NULL,
        result_frontier INTEGER, result_digest TEXT,
        CHECK ((result_frontier IS NULL) = (result_digest IS NULL)),
        FOREIGN KEY (station, day) REFERENCES assignments (station, day)
    )''',
    '''CREATE UNIQUE INDEX IF NOT EXISTS one_pending_move ON moves (station, day)
       WHERE result_frontier IS NULL''',
    '''CREATE TABLE IF NOT EXISTS correction_requests (
        correction_id TEXT PRIMARY KEY, station TEXT NOT NULL, day TEXT NOT NULL,
        new_litres TEXT NOT NULL, FOREIGN KEY (station, day) REFERENCES assignments (station, day)
    )''',
)


@dataclass(frozen=True)
class MoveRecord:
    move_id: str
    day: StationDay
    source: str
    source_epoch: int
    target: str
    result_frontier: int | None = None
    result_digest: str | None = None

    @property
    def target_epoch(self):
        return self.source_epoch + 1


class DirectoryStore(Database):
    def __init__(self, path):
        super().__init__(path, _SCHEMA)

    def transaction(self, *, write=False):
        return super().transaction(write=write)

    def get_assignment(self, day, connection=None):
        if connection is None:
            with self.transaction() as reader:
                return self.get_assignment(day, reader)
        return connection.execute('SELECT * FROM assignments WHERE station = ? AND day = ?', day.key).fetchone()

    @staticmethod
    def _move_record(row):
        if row is None:
            return None
        return MoveRecord(row['move_id'], StationDay(row['station'], row['day']), row['source'],
                          row['source_epoch'], row['target'], row['result_frontier'], row['result_digest'])

    def get_move(self, move_id, connection=None):
        if connection is None:
            with self.transaction() as reader:
                return self.get_move(move_id, reader)
        row = connection.execute('SELECT * FROM moves WHERE move_id = ?', (move_id,)).fetchone()
        return self._move_record(row)

    def find_pending_move(self, day, connection=None):
        if connection is None:
            with self.transaction() as reader:
                return self.find_pending_move(day, reader)
        row = connection.execute(
            'SELECT * FROM moves WHERE station = ? AND day = ? AND result_frontier IS NULL', day.key
        ).fetchone()
        return self._move_record(row)
