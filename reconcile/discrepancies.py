from intake.measurements import sum_litres
from ledger.receipts import PostingReceipt
from storage import InconsistentBook, InvalidInput


class ReconciliationError(InconsistentBook):
    pass


def check_day_balance(book, totals, epoch):
    try:
        from_source = sum_litres(book.batch.measurements)
    except InvalidInput as error:
        raise ReconciliationError('source batch has no effective readings') from error
    if from_source != book.initial_litres:
        raise ReconciliationError('source measurements disagree with the initial value')
    if len(book.postings) != book.frontier or len(book.receipts) != book.frontier:
        raise ReconciliationError('incomplete official postings or receipts')
    receipts = {receipt.correction_id: receipt for receipt in book.receipts}
    seen = set()
    previous = book.initial_litres
    last_epoch = 1
    last_region = None
    for sequence, (posting, (_, _, delta)) in enumerate(zip(book.postings, totals.per_posting, strict=True), 1):
        correction = posting.correction_id
        if posting.sequence != sequence or correction in seen:
            raise ReconciliationError(f'invalid official sequence at {correction}')
        if posting.old_litres != previous:
            raise ReconciliationError(f'disconnected old value at {correction}')
        if posting.delta != delta:
            raise ReconciliationError(f'incorrect signed delta at {correction}')
        if not last_epoch <= posting.issued_epoch <= epoch:
            raise ReconciliationError(f'invalid issuing epoch at {correction}')
        if last_region is not None and posting.issued_epoch == last_epoch and posting.issued_region != last_region:
            raise ReconciliationError(f'inconsistent issuing region at {correction}')
        expected = PostingReceipt(book.batch.day, correction, sequence, posting.issued_region,
                                  posting.issued_epoch, previous, posting.new_litres, delta)
        if receipts.get(correction) != expected:
            raise ReconciliationError(f'missing or mismatched first receipt at {correction}')
        seen.add(correction)
        previous = posting.new_litres
        last_epoch, last_region = posting.issued_epoch, posting.issued_region
    if previous != book.current_litres or totals.closing_litres != book.current_litres:
        raise ReconciliationError('current value disagrees with the official chain')
