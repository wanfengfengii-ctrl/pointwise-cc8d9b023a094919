from dataclasses import dataclass
from datetime import date as CalendarDate

from storage import InvalidInput, identifier


@dataclass(frozen=True)
class StationDay:
    station: str
    date: str

    def __post_init__(self):
        identifier(self.station, 'station')
        if not isinstance(self.date, str):
            raise InvalidInput('station date must be YYYY-MM-DD')
        try:
            parsed = CalendarDate.fromisoformat(self.date)
        except ValueError as error:
            raise InvalidInput('station date must be YYYY-MM-DD') from error
        if parsed.isoformat() != self.date:
            raise InvalidInput('station date must be YYYY-MM-DD')

    @property
    def key(self):
        return self.station, self.date


@dataclass(frozen=True)
class SourceReference:
    station: str
    record: str
    locator: str


def require_day(day):
    if not isinstance(day, StationDay):
        raise InvalidInput('expected a station day')
    return day


def validate_source(day, source):
    if not isinstance(source, SourceReference) or source.station != day.station:
        raise InvalidInput('observation source must belong to the station')
    for field in (source.record, source.locator):
        if not isinstance(field, str) or not field.strip():
            raise InvalidInput('observation needs a record and locator')
    return source
