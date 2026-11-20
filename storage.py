import json
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class WarehouseError(Exception):
    """Base error for the warehouse's public contracts."""


class InvalidInput(WarehouseError, ValueError):
    pass


class Conflict(WarehouseError):
    pass


class NotFound(WarehouseError):
    pass


class NotOwner(WarehouseError):
    pass


class Unavailable(WarehouseError):
    pass


class InconsistentBook(WarehouseError):
    pass


_IDENTIFIER = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}')


def identifier(value, label):
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise InvalidInput(f'invalid {label}')
    return value


def require_litres(value):
    if type(value) is not int:
        raise InvalidInput('litres must be an integer')
    return value


def litre_text(value):
    return format(require_litres(value), 'x')


def parse_litres(value):
    return int(value, 16)


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def decode(value):
    return json.loads(value)


class Database:
    def __init__(self, path, schema):
        self.path = Path(path)
        self._closed = False
        with self.transaction(write=True) as connection:
            for statement in schema:
                connection.execute(statement)

    @contextmanager
    def transaction(self, *, write=False):
        if self._closed:
            raise Unavailable(f'closed store {self.path.name}')
        connection = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute('PRAGMA foreign_keys = ON')
            connection.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def close(self):
        self._closed = True
