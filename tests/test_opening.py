from dataclasses import replace

from intake.measurements import Measurement
from intake.stations import SourceReference
from storage import Conflict, InvalidInput, NotFound
from tests.fixture import DAY, OTHER, WarehouseCase, source_batch
from warehouse import admit, freeze, get_frozen, open_day, reconcile_day


class OpeningTests(WarehouseCase):
    def test_open_and_freeze(self):
        accepted, opened = self.opened()
        frozen = freeze(self.w, DAY)
        facts = get_frozen(self.w, frozen.number)
        self.assertEqual((opened.initial_litres, frozen.litres, facts.current_litres), (7, 7, 7))
        self.assertEqual([row.litres for row in accepted.valid_measurements], [3, 4])
        self.assertEqual([row.litres for row in facts.batch.measurements], [3, None, 4])
        self.assertEqual([row.source.locator for row in facts.batch.measurements],
                         ['sheet-1/01', 'sheet-1/02', 'sheet-1/03'])
        self.assertEqual((facts.batch.batch_id, facts.region, facts.postings), ('B1', 'east', ()))

    def test_batch_replay(self):
        source = source_batch()
        accepted, opened = self.opened(source)
        self.assertEqual(admit(self.w, source), accepted)
        with self.assertRaises(Conflict):
            admit(self.w, source_batch(values=(4, None, 3)))
        with self.assertRaises(Conflict):
            admit(self.w, replace(source, measurements=tuple(reversed(source.measurements))))
        admit(self.w, source_batch(batch_id='B2'))
        with self.assertRaises(Conflict):
            open_day(self.w, 'B2', 'east')
        self.assertEqual(open_day(self.w, 'B1', 'east'), opened)
        self.assertEqual(reconcile_day(self.w, DAY).initial_litres, 7)

    def test_provenance_conflict(self):
        source = source_batch()
        accepted, _ = self.opened(source)
        first, missing, last = source.measurements
        changed = replace(first, source=replace(first.source, locator='sheet-2/01'))
        with self.assertRaises(Conflict):
            admit(self.w, replace(source, measurements=(changed, missing, last)))
        self.assertEqual(self.w.sources.get_batch('B1'), accepted)
        facts = get_frozen(self.w, freeze(self.w, DAY).number)
        self.assertEqual(facts.batch.measurements[0].source.locator, 'sheet-1/01')
        self.assertEqual(facts.current_litres, 7)

    def test_missing_only(self):
        accepted = admit(self.w, source_batch(values=(None, None)))
        self.assertEqual(accepted.valid_measurements, ())
        self.assertEqual([row.source.locator for row in accepted.batch.measurements], ['sheet-1/01', 'sheet-1/02'])
        with self.assertRaises(InvalidInput):
            open_day(self.w, 'B1', 'east')
        with self.assertRaises(NotFound):
            freeze(self.w, DAY)
        self.assertIsNone(self.w.directory.get_assignment(DAY))

    def test_zero_litre(self):
        self.opened(source_batch(OTHER, 'B0', (None, 0)))
        self.assertEqual(reconcile_day(self.w, OTHER).initial_litres, 0)
        facts = get_frozen(self.w, freeze(self.w, OTHER).number)
        self.assertEqual((facts.current_litres, [row.litres for row in facts.batch.measurements]), (0, [None, 0]))

    def test_invalid_measurement(self):
        source = source_batch()
        first = source.measurements[0]
        invalid_rows = (replace(first, litres=True), replace(first, litres=3.0), replace(first, litres='3'),
                        replace(first, source=SourceReference(OTHER.station, 'log', '01')),
                        replace(first, source=SourceReference(DAY.station, 'log', ' ')),
                        {'litres': 3})
        for row in invalid_rows:
            with self.subTest(row=row):
                with self.assertRaises(InvalidInput):
                    admit(self.w, replace(source, measurements=(first, row)))
                with self.assertRaises(NotFound):
                    self.w.sources.get_batch('B1')
        valid = replace(source, measurements=[Measurement(0, first.source)])
        self.assertEqual(admit(self.w, valid).acceptance_no, 1)
