from handoff.directory_store import MoveRecord
from handoff.ownership import MoveResult as MoveResult
from handoff.ownership import completed_move, get_assignment
from handoff.resume import resume_move
from intake.stations import require_day
from storage import Conflict, InvalidInput, identifier


def move(warehouse, day, move_id, target) -> MoveResult:
    require_day(day)
    identifier(move_id, 'move ID')
    warehouse.require_region(target)
    directory = warehouse.directory
    with directory.transaction(write=True) as connection:
        record = directory.get_move(move_id, connection)
        created = record is None
        if record is None:
            route = get_assignment(directory, day, connection)
            if directory.find_pending_move(day, connection) is not None:
                raise Conflict(f'{day.key} already has a pending move')
            if route.region == target:
                raise InvalidInput('the target is already the owner')
            record = MoveRecord(move_id, day, route.region, route.epoch, target)
            connection.execute(
                'INSERT INTO moves (move_id, station, day, source, source_epoch, target) VALUES (?, ?, ?, ?, ?, ?)',
                (move_id, *day.key, route.region, route.epoch, target),
            )
        elif (record.day, record.target) != (day, target):
            raise Conflict(f'move {move_id} has different parameters')
        done = completed_move(record)
    if done is not None:
        return done
    if created:
        warehouse.emit('move_registered', record)
    return resume_move(warehouse, record)
