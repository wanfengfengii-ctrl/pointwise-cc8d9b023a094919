import sqlite3

from storage import NotFound
from tests.fixture import DAY, WarehouseCase
from warehouse import freeze, get_frozen, move, post, reconcile_day


class ArchiveTests(WarehouseCase):
    def setUp(self):
        super().setUp()
        self.opened()

    def test_frozen_day_after_transfer(self):
        early = freeze(self.w, DAY)
        original = get_frozen(self.w, early.number)
        post(self.w, DAY, 'C1', 'east', 11)
        move(self.w, DAY, 'M1', 'west')
        post(self.w, DAY, 'C2', 'west', 16)
        late = freeze(self.w, DAY)
        self.reopen()
        self.w.close_region('east')
        self.assertEqual(reconcile_day(self.w, DAY).current_litres, 16)
        self.w.close_region('west')
        self.w.sources.close()
        self.w.directory.close()
        again = get_frozen(self.w, early.number)
        self.assertEqual(again, original)
        self.assertEqual((again.current_litres, again.postings), (7, ()))
        self.assertEqual([row.source.locator for row in again.batch.measurements],
                         ['sheet-1/01', 'sheet-1/02', 'sheet-1/03'])
        current = get_frozen(self.w, late.number)
        self.assertNotEqual(early.number, late.number)
        self.assertEqual(current.current_litres, 16)
        self.assertEqual(current.batch, original.batch)
        self.assertEqual([(row.correction_id, row.delta) for row in current.postings], [('C1', 4), ('C2', 5)])
        self.assertEqual(get_frozen(self.w, early.number), again)

    def test_unknown_number(self):
        frozen = freeze(self.w, DAY)
        with self.assertRaises(NotFound):
            get_frozen(self.w, frozen.number + 100)

    def test_freeze_write_failure(self):
        old = freeze(self.w, DAY)
        with self.w.archive.transaction(write=True) as connection:
            connection.execute('''CREATE TRIGGER reject_freeze AFTER INSERT ON frozen_days
                BEGIN SELECT RAISE(ABORT, 'archive write refused'); END''')
        post(self.w, DAY, 'C1', 'east', 11)
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'archive write refused'):
            freeze(self.w, DAY)
        with self.w.archive.transaction() as connection:
            numbers = [row[0] for row in connection.execute('SELECT number FROM frozen_days ORDER BY number')]
        self.assertEqual(numbers, [old.number])
        self.assertEqual(get_frozen(self.w, old.number).current_litres, 7)
        with self.w.archive.transaction(write=True) as connection:
            connection.execute('DROP TRIGGER reject_freeze')
        fresh = freeze(self.w, DAY)
        self.assertEqual(get_frozen(self.w, fresh.number).current_litres, 11)
