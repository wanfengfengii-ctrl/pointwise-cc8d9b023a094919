from reconcile.discrepancies import ReconciliationError
from tests.fixture import DAY, WarehouseCase, pause_call
from warehouse import freeze, post, reconcile_day


class IntegrityTests(WarehouseCase):
    def setUp(self):
        super().setUp()
        self.opened()

    def test_disconnected_chain_with_correct_total(self):
        post(self.w, DAY, 'C1', 'east', 11)
        post(self.w, DAY, 'C2', 'east', 14)
        post(self.w, DAY, 'C3', 'east', 16)
        report = reconcile_day(self.w, DAY)
        self.assertEqual((report.net_litres, report.current_litres), (9, 16))
        with self.w.region('east').write_transaction() as connection:
            connection.execute('UPDATE postings SET body = ? WHERE correction_id = ?',
                               ('["c","f","3","east",1]', 'C2'))
            connection.execute('UPDATE receipts SET body = ? WHERE correction_id = ?',
                               ('[["CP01","2026-11-18"],"C2",2,"east",1,"c","f","3"]', 'C2'))
        with self.assertRaisesRegex(ReconciliationError, 'disconnected old value at C2'):
            reconcile_day(self.w, DAY)
        with self.assertRaisesRegex(ReconciliationError, 'disconnected old value at C2'):
            freeze(self.w, DAY)

    def test_missing_receipt_is_incomplete(self):
        post(self.w, DAY, 'C1', 'east', 11)
        with self.w.region('east').write_transaction() as connection:
            connection.execute('DELETE FROM receipts WHERE correction_id = ?', ('C1',))
        with self.assertRaisesRegex(ReconciliationError, 'incomplete official postings or receipts'):
            reconcile_day(self.w, DAY)

    def test_old_value_is_taken_at_commit(self):
        with pause_call(self.events, 'correction_prepared', lambda: post(self.w, DAY, 'C1', 'east', 16)) as later:
            first = post(self.w, DAY, 'C2', 'east', 11)
            self.assertEqual((first.sequence, first.delta), (1, 4))
        second = later.result()
        self.assertEqual((second.sequence, second.old_litres, second.delta), (2, 11, 5))
        self.assertEqual([item.correction_id for item in reconcile_day(self.w, DAY).postings], ['C2', 'C1'])

    def test_concurrent_same_number_records_one_receipt(self):
        with pause_call(self.events, 'correction_prepared', lambda: post(self.w, DAY, 'C1', 'east', 11)) as delayed:
            first = post(self.w, DAY, 'C1', 'east', 11)
        self.assertEqual(delayed.result(), first)
        self.assertEqual(len(reconcile_day(self.w, DAY).postings), 1)
