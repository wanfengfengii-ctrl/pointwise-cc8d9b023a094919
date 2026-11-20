import sqlite3

from ledger.postings import read_official_day
from storage import NotOwner
from tests.fixture import DAY, WarehouseCase, pause_call
from warehouse import freeze, get_frozen, move, post, reconcile_day


class SettlementTests(WarehouseCase):
    def setUp(self):
        super().setUp()
        self.opened()

    def test_source_sealed_once_settled(self):
        first = post(self.w, DAY, 'C1', 'east', 11)
        with pause_call(self.events, 'source_settled', lambda: move(self.w, DAY, 'M1', 'west')) as moving:
            report = reconcile_day(self.w, DAY)
            self.assertEqual((report.region, report.current_litres), ('east', 11))
            with self.assertRaises(NotOwner):
                post(self.w, DAY, 'C2', 'east', 16)
        moved = moving.result()
        self.assertEqual((moved.source, moved.target, moved.frontier), ('east', 'west', 1))
        self.w.close_region('east')
        second = post(self.w, DAY, 'C2', 'west', 16)
        self.assertEqual((second.old_litres, second.delta), (11, 5))
        self.assertEqual(post(self.w, DAY, 'C1', 'west', 11), first)
        self.assertEqual(read_official_day(self.w.region('west'), DAY, 2).current_litres, 16)

    def test_prepared_only_correction_continues_in_target(self):
        with pause_call(self.events, 'correction_prepared', lambda: post(self.w, DAY, 'C1', 'east', 11)) as posting:
            moved = move(self.w, DAY, 'M1', 'west')
            self.assertEqual(moved.frontier, 0)
        with self.assertRaises(NotOwner):
            posting.result()
        first = post(self.w, DAY, 'C1', 'west', 11)
        self.assertEqual((first.sequence, first.old_litres, first.delta, first.issued_region), (1, 7, 4, 'west'))
        self.assertEqual(post(self.w, DAY, 'C1', 'east', 11), first)
        second = post(self.w, DAY, 'C2', 'west', 16)
        self.assertEqual((second.old_litres, second.delta), (11, 5))
        report = reconcile_day(self.w, DAY)
        self.assertEqual([(entry.correction_id, entry.delta) for entry in report.postings], [('C1', 4), ('C2', 5)])

    def test_settled_source_stays_sealed_after_failed_install(self):
        original = freeze(self.w, DAY)
        post(self.w, DAY, 'C1', 'east', 11)
        with pause_call(self.events, 'source_settled', lambda: move(self.w, DAY, 'M1', 'west')) as moving:
            with self.w.region('west').write_transaction() as connection:
                connection.execute('''CREATE TRIGGER reject_install AFTER UPDATE OF frontier ON books
                    BEGIN SELECT RAISE(ABORT, 'target install refused'); END''')
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'target install refused'):
            moving.result()
        self.reopen()
        with self.assertRaises(NotOwner):
            post(self.w, DAY, 'C2', 'east', 16)
        self.assertEqual(reconcile_day(self.w, DAY).current_litres, 11)
        with self.w.region('west').write_transaction() as connection:
            connection.execute('DROP TRIGGER reject_install')
        self.assertEqual(move(self.w, DAY, 'M1', 'west').frontier, 1)
        self.w.close_region('east')
        self.assertEqual(post(self.w, DAY, 'C2', 'west', 16).delta, 5)
        self.assertEqual(get_frozen(self.w, original.number).current_litres, 7)
