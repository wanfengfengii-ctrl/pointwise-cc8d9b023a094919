from closeout.facts import load_facts
from storage import Database, InconsistentBook, InvalidInput, NotFound


class ArchiveStore(Database):
    def __init__(self, path):
        super().__init__(path, ('''CREATE TABLE IF NOT EXISTS frozen_days (
            number INTEGER PRIMARY KEY, body TEXT NOT NULL
        )''',))

    def save_frozen(self, body):
        with self.transaction(write=True) as connection:
            number = connection.execute('INSERT INTO frozen_days (body) VALUES (?)', (body,)).lastrowid
            return load_facts(number, body)

    def load_frozen(self, number):
        if type(number) is not int or number < 1:
            raise InvalidInput('freeze number must be a positive integer')
        if number > (1 << 63) - 1:
            raise NotFound(f'unknown frozen day number')
        with self.transaction() as connection:
            row = connection.execute('SELECT body FROM frozen_days WHERE number = ?', (number,)).fetchone()
            if row is None:
                raise NotFound(f'unknown frozen day number {number}')
            try:
                return load_facts(number, row['body'])
            except (TypeError, ValueError, KeyError) as error:
                raise InconsistentBook(f'invalid frozen body for {number}') from error
