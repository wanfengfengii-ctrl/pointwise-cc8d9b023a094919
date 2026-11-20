import sqlite3
from dataclasses import dataclass

from handoff.ownership import publish_initial_assignment, reserve_initial_assignment
from intake.batches import batch_identity
from intake.measurements import sum_litres
from intake.stations import StationDay
from storage import Unavailable, litre_text


@dataclass(frozen=True)
class OpenedDay:
    day: StationDay
    batch_id: str
    region: str
    initial_litres: int


def open_day(warehouse, batch_id, region):
    warehouse.require_region(region)
    batch = warehouse.sources.get_batch(batch_id).batch
    initial = sum_litres(batch.measurements)
    reserved = reserve_initial_assignment(warehouse.directory, batch.day, batch_id, region)
    if not reserved.published:
        identity, amount = batch_identity(batch), litre_text(initial)
        try:
            image = warehouse.region(region).initialize_day(batch.day, 1, identity, amount)
        except (Unavailable, sqlite3.Error):
            if not warehouse.directory.get_assignment(batch.day)['published']:
                raise
        else:
            warehouse.emit('opening_stored', reserved)
            publish_initial_assignment(warehouse.directory, reserved, image, identity, amount)
    return OpenedDay(batch.day, batch_id, reserved.original_region, initial)
