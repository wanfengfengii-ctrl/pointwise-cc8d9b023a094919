import unittest
from concurrent.futures import Future
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Lock, Thread

from intake.batches import SourceBatch
from intake.measurements import Measurement
from intake.stations import SourceReference, StationDay
from warehouse import Warehouse, admit, open_day


DAY = StationDay('CP01', '2026-11-18')
OTHER = StationDay('CP02', '2026-11-18')


def source_batch(day=DAY, batch_id='B1', values=(3, None, 4)):
    return SourceBatch(batch_id, day, tuple(
        Measurement(value, SourceReference(day.station, 'morning-survey', f'sheet-1/{index:02}'))
        for index, value in enumerate(values, 1)
    ))


class Interruption(RuntimeError):
    def __init__(self, event, payload):
        super().__init__(event)
        self.payload = payload


class Events:
    def __init__(self):
        self._actions = {}
        self._lock = Lock()

    def on(self, name, action):
        with self._lock:
            if name in self._actions:
                raise AssertionError(f'event already armed {name}')
            self._actions[name] = action

    def __call__(self, name, payload):
        with self._lock:
            action = self._actions.pop(name, None)
        if action is not None:
            action(payload)

    def interrupt_at(self, name):
        def interrupt(payload):
            raise Interruption(name, payload)
        self.on(name, interrupt)


@contextmanager
def pause_call(events, event, operation):
    reached, release = Event(), Event()
    outcome = Future()

    def stop_at_boundary(_payload):
        reached.set()
        if not release.wait(15):
            raise TimeoutError(f'no release at {event}')

    def run():
        try:
            outcome.set_result(operation())
        except BaseException as error:
            outcome.set_exception(error)

    events.on(event, stop_at_boundary)
    worker = Thread(target=run, name=f'warehouse-{event}', daemon=True)
    worker.start()
    try:
        if not reached.wait(10):
            if outcome.done():
                outcome.result()
            raise AssertionError(f'operation did not reach {event}')
        yield outcome
    finally:
        release.set()
        worker.join(10)
        if worker.is_alive():
            raise AssertionError(f'operation did not return after {event}')


class WarehouseCase(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory(prefix='chengpu-test-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.events = Events()
        self.w = Warehouse(self.root, events=self.events)
        self.addCleanup(lambda: self.w.close())

    def reopen(self):
        self.w.close()
        self.w = Warehouse(self.root, events=self.events)

    def opened(self, batch=None, region='east'):
        if batch is None:
            batch = source_batch()
        accepted = admit(self.w, batch)
        return accepted, open_day(self.w, batch.batch_id, region)
