from dataclasses import astuple, dataclass
from hashlib import sha256

from storage import Conflict, Database, InconsistentBook, encode


_SCHEMA = (
    '''CREATE TABLE IF NOT EXISTS books (
        station TEXT NOT NULL, day TEXT NOT NULL, epoch INTEGER NOT NULL,
        batch TEXT NOT NULL, initial_litres TEXT NOT NULL, current_litres TEXT NOT NULL,
        frontier INTEGER NOT NULL CHECK (frontier >= 0), inbound_move TEXT,
        accepted_digest TEXT,
        PRIMARY KEY (station, day, epoch)
    )''',
    '''CREATE TABLE IF NOT EXISTS preparations (
        station TEXT NOT NULL, day TEXT NOT NULL, epoch INTEGER NOT NULL,
        correction_id TEXT NOT NULL, new_litres TEXT NOT NULL,
        PRIMARY KEY (station, day, epoch, correction_id),
        FOREIGN KEY (station, day, epoch) REFERENCES books (station, day, epoch)
    )''',
    '''CREATE TABLE IF NOT EXISTS postings (
        station TEXT NOT NULL, day TEXT NOT NULL, epoch INTEGER NOT NULL,
        sequence INTEGER NOT NULL CHECK (sequence > 0),
        correction_id TEXT NOT NULL, body TEXT NOT NULL,
        PRIMARY KEY (station, day, epoch, sequence),
        UNIQUE (station, day, epoch, correction_id),
        FOREIGN KEY (station, day, epoch) REFERENCES books (station, day, epoch)
    )''',
    '''CREATE TABLE IF NOT EXISTS receipts (
        station TEXT NOT NULL, day TEXT NOT NULL, epoch INTEGER NOT NULL,
        correction_id TEXT NOT NULL, body TEXT NOT NULL,
        PRIMARY KEY (station, day, epoch, correction_id),
        FOREIGN KEY (station, day, epoch, correction_id)
            REFERENCES postings (station, day, epoch, correction_id)
    )''',
)

_KEY = 'station = ? AND day = ? AND epoch = ?'


def book_key(day, epoch):
    return (*day.key, epoch)


@dataclass(frozen=True)
class BookImage:
    batch: str
    initial_litres: str
    current_litres: str
    frontier: int
    postings: tuple[tuple[int, str, str], ...]
    receipts: tuple[tuple[str, str], ...]

    def digest(self):
        return sha256(encode(astuple(self)).encode('utf-8')).hexdigest()


class RegionStore(Database):
    def __init__(self, path, region):
        self.region = region
        super().__init__(path, _SCHEMA)

    def write_transaction(self):
        return self.transaction(write=True)

    @staticmethod
    def _lookup_header(connection, key):
        return connection.execute(f'SELECT * FROM books WHERE {_KEY}', key).fetchone()

    def header(self, connection, day, epoch):
        header = self._lookup_header(connection, book_key(day, epoch))
        if header is None:
            raise InconsistentBook(f'missing book for {day.key} at epoch {epoch} in {self.region}')
        return header

    def initialize_day(self, day, epoch, batch, initial):
        key = book_key(day, epoch)
        with self.write_transaction() as connection:
            connection.execute(
                '''INSERT INTO books (station, day, epoch, batch, initial_litres, current_litres, frontier)
                   VALUES (?, ?, ?, ?, ?, ?, 0) ON CONFLICT (station, day, epoch) DO NOTHING''',
                (*key, batch, initial, initial),
            )
            header = self.header(connection, day, epoch)
            if (header['batch'], header['initial_litres'], header['inbound_move']) != (batch, initial, None):
                raise Conflict('initial book differs from the reserved opening')
            return self.read_image(connection, day, epoch)

    def read_image(self, connection, day, epoch):
        key = book_key(day, epoch)
        header = self.header(connection, day, epoch)
        postings = connection.execute(
            f'SELECT sequence, correction_id, body FROM postings WHERE {_KEY} ORDER BY sequence', key
        )
        receipts = connection.execute(
            f'SELECT correction_id, body FROM receipts WHERE {_KEY} ORDER BY correction_id', key
        )
        return BookImage(header['batch'], header['initial_litres'], header['current_litres'],
                         header['frontier'], tuple(map(tuple, postings)), tuple(map(tuple, receipts)))

    def read_day(self, day, epoch):
        with self.transaction() as connection:
            return self.read_image(connection, day, epoch)

    def stage_day(self, day, epoch, move_id, image, *, final=False):
        key = book_key(day, epoch)
        with self.write_transaction() as connection:
            header = self._lookup_header(connection, key)
            if header is not None:
                if header['inbound_move'] != move_id:
                    raise Conflict('target epoch belongs to another operation')
                if header['accepted_digest'] is not None or not final:
                    return
                connection.execute(f'DELETE FROM receipts WHERE {_KEY}', key)
                connection.execute(f'DELETE FROM postings WHERE {_KEY}', key)
                connection.execute(
                    f'UPDATE books SET batch = ?, initial_litres = ?, current_litres = ?, frontier = ? WHERE {_KEY}',
                    (image.batch, image.initial_litres, image.current_litres, image.frontier, *key),
                )
            else:
                connection.execute(
                    '''INSERT INTO books (station, day, epoch, batch, initial_litres,
                       current_litres, frontier, inbound_move) VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                    (*key, image.batch, image.initial_litres, image.current_litres, image.frontier, move_id),
                )
            connection.executemany(
                'INSERT INTO postings VALUES (?, ?, ?, ?, ?, ?)', ((*key, *row) for row in image.postings)
            )
            connection.executemany(
                'INSERT INTO receipts VALUES (?, ?, ?, ?, ?)', ((*key, *row) for row in image.receipts)
            )
