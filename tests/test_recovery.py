import sqlite3

from ledger.postings import read_official_day
from storage import Conflict, NotFound, NotOwner
from tests.fixture import DAY, OTHER, Interruption, WarehouseCase, pause_call, source_batch
from warehouse import admit, freeze, get_frozen, init_sample, move, open_day, post, reconcile_day


class RecoveryTests(WarehouseCase):
    def test_resume_opening_and_preserve_original(self):
        batch = source_batch()
        accepted = admit(self.w, batch)
        self.events.interrupt_at('opening_stored')
        with self.assertRaises(Interruption):
            open_day(self.w, 'B1', 'east')
        self.reopen()
        self.assertEqual(read_official_day(self.w.region('east'), DAY, 1).current_litres, 7)
        with self.assertRaises(NotFound):
            reconcile_day(self.w, DAY)
        with self.assertRaises(Conflict):
            open_day(self.w, 'B1', 'west')
        opened = open_day(self.w, 'B1', 'east')
        post(self.w, DAY, 'C1', 'east', 11)
        move(self.w, DAY, 'M1', 'west')
        self.reopen()
        self.w.close_region('east')
        self.assertEqual(admit(self.w, batch), accepted)
        self.assertEqual(open_day(self.w, 'B1', 'east'), opened)
        self.assertEqual((reconcile_day(self.w, DAY).region, reconcile_day(self.w, DAY).current_litres), ('west', 11))

    def test_resume_after_target_acceptance(self):
        self.opened()
        first = post(self.w, DAY, 'C1', 'east', 11)
        self.events.interrupt_at('target_accepted')
        with self.assertRaises(Interruption) as paused:
            move(self.w, DAY, 'M1', 'west')
        self.reopen()
        self.assertEqual(reconcile_day(self.w, DAY).region, 'east')
        self.assertEqual(read_official_day(self.w.region('west'), DAY, 2).receipts, (first,))
        self.assertIsNone(self.w.directory.get_move('M1').result_frontier)
        with self.assertRaises(NotOwner):
            post(self.w, DAY, 'C2', 'east', 16)
        moved = move(self.w, DAY, 'M1', 'west')
        self.assertEqual(self.w.directory.get_move('M1').result_digest, paused.exception.payload.digest)
        self.reopen()
        self.w.close_region('east')
        self.assertEqual(move(self.w, DAY, 'M1', 'west'), moved)
        self.assertEqual(post(self.w, DAY, 'C1', 'west', 11), first)
        self.assertEqual(post(self.w, DAY, 'C2', 'west', 16).delta, 5)

    def test_move_conflicts_while_pending_and_after_completion(self):
        self.opened()
        self.opened(source_batch(OTHER, 'B2'))
        self.events.interrupt_at('candidate_copied')
        with self.assertRaises(Interruption):
            move(self.w, DAY, 'M1', 'west')
        with self.assertRaises(Conflict):
            move(self.w, DAY, 'M2', 'west')
        with self.assertRaises(Conflict):
            move(self.w, OTHER, 'M1', 'west')
        done = move(self.w, DAY, 'M1', 'west')
        with self.assertRaises(Conflict):
            move(self.w, DAY, 'M1', 'east')
        self.assertEqual(move(self.w, DAY, 'M1', 'west'), done)
        self.assertEqual(reconcile_day(self.w, OTHER).region, 'east')

    def test_retry_target_write_after_source_settlement(self):
        self.opened()
        with pause_call(self.events, 'candidate_copied', lambda: move(self.w, DAY, 'M1', 'west')) as moving:
            first = post(self.w, DAY, 'C1', 'east', 11)
            with self.w.region('west').write_transaction() as connection:
                connection.execute('''CREATE TRIGGER reject_install AFTER UPDATE OF frontier ON books
                    BEGIN SELECT RAISE(ABORT, 'target install refused'); END''')
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'target install refused'):
            moving.result()
        self.reopen()
        self.assertEqual((reconcile_day(self.w, DAY).region, reconcile_day(self.w, DAY).current_litres), ('east', 11))
        pending = read_official_day(self.w.region('west'), DAY, 2)
        self.assertEqual((pending.current_litres, pending.postings, pending.receipts), (7, (), ()))
        with self.w.region('west').write_transaction() as connection:
            connection.execute('DROP TRIGGER reject_install')
        self.assertEqual(move(self.w, DAY, 'M1', 'west').frontier, 1)
        self.w.close_region('east')
        self.assertEqual(post(self.w, DAY, 'C1', 'west', 11), first)

    def test_sample_initialization_is_reusable(self):
        initial = init_sample(self.w)
        self.assertEqual(init_sample(self.w), initial)
        day = initial[1].day
        frozen = freeze(self.w, day)
        first = post(self.w, day, 'C1', 'east', 11)
        transferred = move(self.w, day, 'M1', 'west')
        self.reopen()
        self.w.close_region('east')
        self.assertEqual(init_sample(self.w), initial)
        self.assertEqual(move(self.w, day, 'M1', 'west'), transferred)
        self.assertEqual(post(self.w, day, 'C1', 'west', 11), first)
        self.assertEqual(reconcile_day(self.w, day).current_litres, 11)
        self.assertEqual(get_frozen(self.w, frozen.number).current_litres, 7)

    def test_return_to_prior_region_uses_new_epoch(self):
        self.opened()
        first = post(self.w, DAY, 'C1', 'east', 11)
        move(self.w, DAY, 'M1', 'west')
        second = post(self.w, DAY, 'C2', 'west', 16)
        back = move(self.w, DAY, 'M2', 'east')
        self.assertEqual((back.target_epoch, back.frontier), (3, 2))
        self.w.close_region('west')
        self.assertEqual(post(self.w, DAY, 'C1', 'east', 11), first)
        self.assertEqual(post(self.w, DAY, 'C2', 'east', 16), second)
        third = post(self.w, DAY, 'C3', 'east', 10)
        self.assertEqual((third.sequence, third.old_litres, third.delta), (3, 16, -6))
        self.assertEqual(read_official_day(self.w.region('east'), DAY, 1).current_litres, 11)
