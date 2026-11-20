from dataclasses import dataclass

from intake.stations import SourceReference, validate_source
from storage import InvalidInput, litre_text, parse_litres, require_litres


@dataclass(frozen=True)
class Measurement:
    litres: int | None
    source: SourceReference


def normalize_measurements(day, rows):
    if not isinstance(rows, (list, tuple)):
        raise InvalidInput('measurements must be an ordered list or tuple')
    normalized = []
    for row in rows:
        if not isinstance(row, Measurement):
            raise InvalidInput('expected a measurement')
        if row.litres is not None:
            require_litres(row.litres)
        normalized.append(Measurement(row.litres, validate_source(day, row.source)))
    return tuple(normalized)


def valid_measurements(rows):
    return tuple(row for row in rows if row.litres is not None)


def sum_litres(rows):
    valid = valid_measurements(rows)
    if not valid:
        raise InvalidInput('opening requires at least one valid measurement')
    return sum(row.litres for row in valid)


def measurement_data(row):
    litres = None if row.litres is None else litre_text(row.litres)
    return [litres, row.source.station, row.source.record, row.source.locator]


def measurement_from_data(data):
    litres, station, record, locator = data
    value = None if litres is None else parse_litres(litres)
    return Measurement(value, SourceReference(station, record, locator))
