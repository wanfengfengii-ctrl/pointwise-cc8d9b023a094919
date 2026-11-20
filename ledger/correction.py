from handoff.ownership import read_current_book
from intake.stations import require_day
from ledger.postings import commit_posting
from ledger.preparations import PreparedCorrection, bind_correction_request, prepare_correction
from ledger.receipts import check_receipt_request
from storage import NotOwner, identifier, require_litres


def post(warehouse, day, correction_id, region, litres):
    require_day(day)
    identifier(correction_id, 'correction ID')
    warehouse.require_region(region)
    require_litres(litres)
    route, book = read_current_book(warehouse, day)
    for receipt in book.receipts:
        if receipt.correction_id == correction_id:
            return check_receipt_request(receipt, day, litres)
    if route.region != region:
        raise NotOwner(f'{region} is not the current owner of {day.key}')
    bind_correction_request(warehouse.directory, day, correction_id, litres)
    store = warehouse.region(region)
    request = prepare_correction(store, PreparedCorrection(day, correction_id, region, route.epoch, litres))
    warehouse.emit('correction_prepared', request)
    receipt, created = commit_posting(store, request)
    if created:
        warehouse.emit('correction_committed', receipt)
    return receipt
