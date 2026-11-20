import json

from ledger.postings import read_official_day
from ledger.preparations import load_preparation
from storage import Conflict, NotOwner, Unavailable
from tests.fixture import DAY, OTHER, Interruption, WarehouseCase, pause_call, source_batch
from warehouse import freeze, get_frozen, move, post, reconcile_day


class TransferTests(WarehouseCase):
    def setUp(self):
        super().setUp()
        self.opened()

    def test_receipt_after_move(self):
        original = freeze(self.w, DAY)
        with pause_call(self.events, 'candidate_copied', lambda: move(self.w, DAY, 'M1', 'west')) as moving:
            self.assertEqual(reconcile_day(self.w, DAY).region, 'east')
            self.assertEqual(read_official_day(self.w.region('west'), DAY, 2).current_litres, 7)
            self.events.interrupt_at('correction_committed')
            with self.assertRaises(Interruption) as lost:
                post(self.w, DAY, 'C1', 'east', 11)
            signed = lost.exception.payload
            self.assertEqual((signed.old_litres, signed.new_litres, signed.delta, signed.issued_region), (7, 11, 4, 'east'))
            self.assertEqual(read_official_day(self.w.region('east'), DAY, 1).receipts, (signed,))
        result = moving.result()
        self.w.close_region('east')
        with self.assertRaises(Unavailable):
            self.w.region('east')
        second = post(self.w, DAY, 'C2', 'west', 16)
        self.assertEqual((second.old_litres, second.delta), (11, 5),
                         f'C2_NET_DELTA expected +5 L, actual {second.delta:+d} L')
        replay = post(self.w, DAY, 'C1', 'west', 11)
        self.assertEqual(replay, signed)
        with self.assertRaises(Conflict):
            post(self.w, DAY, 'C1', 'west', 12)
        report = reconcile_day(self.w, DAY)
        self.assertEqual(result.frontier, 1)
        self.assertEqual((report.region, report.current_litres, report.net_litres), ('west', 16, 9))
        self.assertEqual([(entry.correction_id, entry.delta) for entry in report.postings], [('C1', 4), ('C2', 5)])
        frozen = get_frozen(self.w, original.number)
        self.assertEqual((frozen.current_litres, frozen.postings), (7, ()))
        scenario = {
            'case_id': 'moved_receipt', 'input': {'initial': 7, 'corrections': [11, 16], 'target': 'west'},
            'expected': [4, 5], 'actual': [replay.delta, second.delta],
            'downstream_expected': [16, 9, 7], 'downstream_actual': [report.current_litres, report.net_litres,
                                                                    frozen.current_litres],
            'code_paths': ['ledger/postings.py', 'handoff/resume.py', 'handoff/acceptance.py',
                           'reconcile/shift_report.py', 'closeout/retrieve.py'],
            'oracle': '11 - 7 = 4, 16 - 11 = 5, original freeze = 7',
        }
        print('POINTWISE_SCENARIO ' + json.dumps(scenario, sort_keys=True))

    def test_prepared_is_not_posted(self):
        with pause_call(self.events, 'correction_prepared', lambda: post(self.w, DAY, 'C1', 'east', 11)) as posting:
            east = self.w.region('east')
            with east.transaction() as connection:
                self.assertEqual(load_preparation(connection, DAY, 1, 'C1'), 11)
            self.assertEqual(read_official_day(east, DAY, 1).postings, ())
            moved = move(self.w, DAY, 'M1', 'west')
            self.assertEqual(moved.frontier, 0)
            self.assertEqual(reconcile_day(self.w, DAY).current_litres, 7)
        with self.assertRaises(NotOwner):
            posting.result()
        official = read_official_day(east, DAY, 1)
        self.assertEqual((official.current_litres, official.postings, official.receipts), (7, (), ()))
        second = post(self.w, DAY, 'C2', 'west', 16)
        self.assertEqual((second.old_litres, second.delta), (7, 9))
        self.assertEqual([entry.correction_id for entry in reconcile_day(self.w, DAY).postings], ['C2'])

    def test_resume_before_activation(self):
        self.events.interrupt_at('move_registered')
        with self.assertRaises(Interruption):
            move(self.w, DAY, 'M1', 'west')
        self.reopen()
        pending = self.w.directory.find_pending_move(DAY)
        self.assertEqual(pending.move_id, 'M1')
        self.assertEqual(reconcile_day(self.w, DAY).region, 'east')
        resumed = move(self.w, DAY, 'M1', 'west')
        self.assertEqual((resumed.source, resumed.target, resumed.frontier), ('east', 'west', 0))
        self.assertEqual((reconcile_day(self.w, DAY).region, reconcile_day(self.w, DAY).postings), ('west', ()))
        self.assertIsNone(self.w.directory.find_pending_move(DAY))

    def test_independent_day_during_pause(self):
        self.opened(source_batch(OTHER, 'B2', (5,)))
        with pause_call(self.events, 'candidate_copied', lambda: move(self.w, DAY, 'M1', 'west')) as moving:
            receipt = post(self.w, OTHER, 'O1', 'east', 12)
            self.assertEqual((receipt.old_litres, receipt.delta), (5, 7))
            self.assertEqual(reconcile_day(self.w, DAY).region, 'east')
        self.assertEqual(moving.result().frontier, 0)
        self.reopen()
        self.assertEqual(post(self.w, OTHER, 'O1', 'east', 12), receipt)
        self.assertEqual(reconcile_day(self.w, OTHER).current_litres, 12)
