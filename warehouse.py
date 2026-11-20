import argparse
import json
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import RLock

from closeout.archive import ArchiveStore
from closeout.freeze import freeze as freeze
from closeout.retrieve import get_frozen as get_frozen
from handoff.directory_store import DirectoryStore
from handoff.transfer import move as move
from intake.admission import admit as admit
from intake.batches import SourceBatch
from intake.measurements import Measurement
from intake.source_store import SourceStore
from intake.stations import SourceReference, StationDay
from ledger.correction import post as post
from ledger.day_open import open_day as open_day
from ledger.region_store import RegionStore
from reconcile.shift_report import reconcile_day as reconcile_day
from storage import InvalidInput, Unavailable, identifier


class Warehouse:
    def __init__(self, root, *, regions=('east', 'west'), events=None):
        self.root = Path(root)
        self.regions = frozenset(identifier(region, 'region') for region in regions)
        if not self.regions:
            raise InvalidInput('at least one configured region is required')
        self.root.mkdir(parents=True, exist_ok=True)
        self.directory = DirectoryStore(self.root / 'directory.sqlite3')
        self.sources = SourceStore(self.root / 'sources.sqlite3')
        self.archive = ArchiveStore(self.root / 'archive.sqlite3')
        self._events = events
        self._lock = RLock()
        self._stores = {}
        self._offline = set()
        self._closed = False

    def require_region(self, region):
        identifier(region, 'region')
        if region not in self.regions:
            raise InvalidInput(f'unknown region {region}')

    def region(self, region):
        self.require_region(region)
        with self._lock:
            if self._closed or region in self._offline:
                raise Unavailable(f'region {region} is closed')
            if region not in self._stores:
                self._stores[region] = RegionStore(self.root / f'region-{region}.sqlite3', region)
            return self._stores[region]

    def close_region(self, region):
        self.require_region(region)
        with self._lock:
            self._offline.add(region)
            store = self._stores.pop(region, None)
            if store is not None:
                store.close()

    def emit(self, name, payload):
        if self._events is not None:
            self._events(name, payload)

    def close(self):
        with self._lock:
            self._closed = True
            for store in (*self._stores.values(), self.directory, self.sources, self.archive):
                store.close()
            self._stores.clear()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()


def init_sample(warehouse):
    path = Path(__file__).resolve().parent / 'examples' / 'shift.json'
    data = json.loads(path.read_text(encoding='utf-8'))
    day = StationDay(data['station'], data['date'])
    rows = tuple(Measurement(item['litres'], SourceReference(day.station, item['record'], item['locator']))
                 for item in data['measurements'])
    accepted = admit(warehouse, SourceBatch(data['batch_id'], day, rows))
    return accepted, open_day(warehouse, accepted.batch.batch_id, data['region'])


class _LostReply(Exception):
    pass


def run_demo():
    with TemporaryDirectory(prefix='chengpu-daybook-') as root:
        def events(name, payload):
            if name == 'candidate_copied':
                try:
                    post(warehouse, payload.day, 'C1', 'east', 11)
                except _LostReply:
                    return
                raise RuntimeError('the demonstration did not encounter the lost response')
            if name == 'correction_committed' and payload.correction_id == 'C1':
                raise _LostReply

        with Warehouse(root, events=events) as warehouse:
            source, opened = init_sample(warehouse)
            day = opened.day
            original = freeze(warehouse, day)
            transfer = move(warehouse, day, 'M1', 'west')
            warehouse.close_region('east')
            second = post(warehouse, day, 'C2', 'west', 16)
            first = post(warehouse, day, 'C1', 'west', 11)
        with Warehouse(root) as warehouse:
            warehouse.close_region('east')
            report = reconcile_day(warehouse, day)
            frozen = get_frozen(warehouse, original.number)
            repeated = init_sample(warehouse)
            if repeated != (source, opened):
                raise RuntimeError('sample initialization changed an existing result')
            if move(warehouse, day, 'M1', 'west') != transfer:
                raise RuntimeError('move replay differs from its first result')
        expected = {'first_old': 7, 'first_delta': 4, 'second_old': 11, 'second_delta': 5,
                    'first_issuer': 'east', 'moved_frontier': 1}
        actual = {'first_old': first.old_litres, 'first_delta': first.delta, 'second_old': second.old_litres,
                  'second_delta': second.delta, 'first_issuer': first.issued_region,
                  'moved_frontier': transfer.frontier}
        downstream_expected = {'region': 'west', 'current': 16, 'net': 9, 'corrections': ['C1', 'C2'],
                               'frozen': 7, 'frozen_readings': [3, None, 4],
                               'frozen_locators': ['sheet-1/01', 'sheet-1/02', 'sheet-1/03']}
        downstream_actual = {'region': report.region, 'current': report.current_litres, 'net': report.net_litres,
                             'corrections': [row.correction_id for row in report.postings],
                             'frozen': frozen.current_litres,
                             'frozen_readings': [row.litres for row in frozen.batch.measurements],
                             'frozen_locators': [row.source.locator for row in frozen.batch.measurements]}
        if actual != expected or downstream_actual != downstream_expected:
            raise RuntimeError(f'daily reconciliation mismatch {actual!r} {downstream_actual!r}')
        scenario = {'case_id': 'moved_receipt', 'input': {'day': day.key, 'observations': [asdict(row) for row in
                    source.batch.measurements], 'corrections': [['C1', 11], ['C2', 16]], 'target': 'west'},
                    'expected': expected, 'actual': actual, 'downstream_expected': downstream_expected,
                    'downstream_actual': downstream_actual, 'oracle': '3 + 4 = 7, 11 - 7 = 4, 16 - 11 = 5',
                    'code_paths': ['ledger/day_open.py', 'ledger/postings.py', 'handoff/resume.py',
                                   'handoff/acceptance.py', 'reconcile/shift_report.py', 'closeout/retrieve.py']}
        print('POINTWISE_SCENARIO ' + json.dumps(scenario, ensure_ascii=False, sort_keys=True))


def main():
    parser = argparse.ArgumentParser(description='澄浦河口监测日仓')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('demo', help='run the full shift in a temporary warehouse')
    sample = commands.add_parser('init-sample', help='admit and open the sample in a data directory')
    sample.add_argument('data_dir', type=Path)
    args = parser.parse_args()
    if args.command == 'demo':
        run_demo()
    else:
        with Warehouse(args.data_dir) as warehouse:
            accepted, opened = init_sample(warehouse)
            print(json.dumps({'acceptance_no': accepted.acceptance_no, 'opening': asdict(opened)}, sort_keys=True))


if __name__ == '__main__':
    main()
