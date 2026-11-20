from storage import Conflict, InvalidInput, NotFound
from tests.fixture import DAY, OTHER, WarehouseCase, source_batch
from warehouse import post, reconcile_day


class CorrectionTests(WarehouseCase):
    def setUp(self):
        super().setUp()
        self.opened()

    def test_signed_net(self):
        first = post(self.w, DAY, 'C9', 'east', 11)
        second = post(self.w, DAY, 'C2', 'east', 9)
        self.assertEqual((first.old_litres, first.new_litres, first.delta, first.sequence), (7, 11, 4, 1))
        self.assertEqual((second.old_litres, second.new_litres, second.delta, second.sequence), (11, 9, -2, 2))
        self.assertEqual(post(self.w, DAY, 'C2', 'east', 9), second)
        report = reconcile_day(self.w, DAY)
        self.assertEqual((report.initial_litres, report.current_litres, report.net_litres), (7, 9, 2))
        self.assertEqual([(entry.correction_id, entry.delta) for entry in report.postings], [('C9', 4), ('C2', -2)])

    def test_post_conflict(self):
        first = post(self.w, DAY, 'C1', 'east', 11)
        self.assertEqual(post(self.w, DAY, 'C1', 'east', 11), first)
        with self.assertRaises(Conflict):
            post(self.w, DAY, 'C1', 'east', 12)
        self.opened(source_batch(OTHER, 'B2'))
        with self.assertRaises(Conflict):
            post(self.w, OTHER, 'C1', 'east', 11)
        self.assertEqual(post(self.w, DAY, 'C1', 'east', 11), first)
        self.assertEqual(len(reconcile_day(self.w, DAY).postings), 1)
        self.assertEqual(reconcile_day(self.w, OTHER).postings, ())

    def test_zero_delta(self):
        receipt = post(self.w, DAY, 'C0', 'east', 7)
        self.assertEqual((receipt.old_litres, receipt.new_litres, receipt.delta), (7, 7, 0))
        report = reconcile_day(self.w, DAY)
        self.assertEqual((report.net_litres, len(report.postings)), (0, 1))

    def test_integer_precision(self):
        target = 1 << 100
        first = post(self.w, DAY, 'C1', 'east', target)
        self.reopen()
        second = post(self.w, DAY, 'C2', 'east', target - 9)
        self.assertEqual((first.delta, second.old_litres, second.delta), (target - 7, target, -9))
        self.assertEqual(reconcile_day(self.w, DAY).current_litres, target - 9)

    def test_invalid_amount_and_unknown_day(self):
        with self.assertRaises(InvalidInput):
            post(self.w, DAY, 'invalid', 'east', True)
        with self.assertRaises(NotFound):
            post(self.w, OTHER, 'unknown', 'east', 1)
        with self.assertRaises(NotFound):
            reconcile_day(self.w, OTHER)
        self.assertEqual(reconcile_day(self.w, DAY).postings, ())
