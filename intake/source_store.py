from intake.batches import AcceptedBatch, batch_from_identity, batch_identity
from storage import Conflict, Database, NotFound, identifier


class SourceStore(Database):
    def __init__(self, path):
        super().__init__(path, ('''CREATE TABLE IF NOT EXISTS source_batches (
            acceptance_no INTEGER PRIMARY KEY,
            batch_id TEXT NOT NULL UNIQUE,
            content TEXT NOT NULL
        )''',))

    @staticmethod
    def _row(connection, batch_id):
        return connection.execute(
            'SELECT acceptance_no, content FROM source_batches WHERE batch_id = ?', (batch_id,)
        ).fetchone()

    def admit_batch(self, batch):
        identity = batch_identity(batch)
        with self.transaction(write=True) as connection:
            row = self._row(connection, batch.batch_id)
            if row is not None:
                if row['content'] != identity:
                    raise Conflict(f'batch {batch.batch_id} has different contents')
                number = row['acceptance_no']
            else:
                number = connection.execute(
                    'INSERT INTO source_batches (batch_id, content) VALUES (?, ?)',
                    (batch.batch_id, identity),
                ).lastrowid
            return AcceptedBatch(number, batch)

    def get_batch(self, batch_id):
        identifier(batch_id, 'batch ID')
        with self.transaction() as connection:
            row = self._row(connection, batch_id)
            if row is None:
                raise NotFound(f'unknown source batch {batch_id}')
            return AcceptedBatch(row['acceptance_no'], batch_from_identity(row['content']))
