import sqlite3

from handoff.acceptance import accept_candidate
from handoff.ownership import completed_move, publish_move
from ledger.postings import SettledDay
from storage import WarehouseError


def resume_move(warehouse, record):
    current = warehouse.directory.get_move(record.move_id)
    done = completed_move(current)
    if done is not None:
        return done
    try:
        source = warehouse.region(record.source)
        target = warehouse.region(record.target)
        preview = source.read_day(record.day, record.source_epoch)
        target.stage_day(record.day, record.target_epoch, record.move_id, preview)
        warehouse.emit('candidate_copied', record)
        source_export = SettledDay(record.day, record.source, record.source_epoch, record.move_id, preview)
        warehouse.emit('source_settled', source_export)
        accepted = accept_candidate(target, record)
        warehouse.emit('target_accepted', accepted)
        result = publish_move(warehouse.directory, record, accepted)
    except (WarehouseError, sqlite3.Error):
        # Another executor may have published while this caller was reading the prior epoch.
        done = completed_move(warehouse.directory.get_move(record.move_id))
        if done is None:
            raise
        return done
    warehouse.emit('move_published', result)
    return result
