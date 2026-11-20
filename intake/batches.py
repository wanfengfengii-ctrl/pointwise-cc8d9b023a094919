from dataclasses import dataclass

from intake.measurements import (Measurement, measurement_data, measurement_from_data,
                                 normalize_measurements, valid_measurements)
from intake.stations import StationDay, require_day
from storage import InvalidInput, decode, encode, identifier


@dataclass(frozen=True)
class SourceBatch:
    batch_id: str
    day: StationDay
    measurements: tuple[Measurement, ...] | list[Measurement]


@dataclass(frozen=True)
class AcceptedBatch:
    acceptance_no: int
    batch: SourceBatch

    @property
    def valid_measurements(self):
        return valid_measurements(self.batch.measurements)


def normalize_batch(batch):
    if not isinstance(batch, SourceBatch):
        raise InvalidInput('expected a source batch')
    identifier(batch.batch_id, 'batch ID')
    day = require_day(batch.day)
    return SourceBatch(batch.batch_id, day, normalize_measurements(day, batch.measurements))


def batch_identity(batch):
    return encode([batch.batch_id, batch.day.key,
                   [measurement_data(row) for row in batch.measurements]])


def batch_from_identity(identity):
    batch_id, day, rows = decode(identity)
    batch = SourceBatch(batch_id, StationDay(*day), tuple(measurement_from_data(row) for row in rows))
    return normalize_batch(batch)
