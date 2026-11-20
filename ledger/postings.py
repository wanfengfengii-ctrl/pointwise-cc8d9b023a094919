from dataclasses import dataclass

from intake.batches import SourceBatch, batch_from_identity
from intake.stations import StationDay
from ledger.preparations import load_preparation
from ledger.receipts import (PostingReceipt, check_receipt_request, find_receipt, receipt_from_body,
                             record_receipt)
from ledger.region_store import BookImage, book_key
from storage import InconsistentBook, NotOwner, decode, encode, litre_text, parse_litres


@dataclass(frozen=True)
class Posting:
    sequence: int
    correction_id: str
    old_litres: int
    new_litres: int
    delta: int
    issued_region: str
    issued_epoch: int


@dataclass(frozen=True)
class OfficialDay:
    batch: SourceBatch
    initial_litres: int
    current_litres: int
    frontier: int
    postings: tuple[Posting, ...]
    receipts: tuple[PostingReceipt, ...]


@dataclass(frozen=True)
class SettledDay:
    day: StationDay
    source: str
    source_epoch: int
    move_id: str
    image: BookImage


def posting_body(posting):
    return encode([litre_text(posting.old_litres), litre_text(posting.new_litres),
                   litre_text(posting.delta), posting.issued_region, posting.issued_epoch])


def posting_from_row(sequence, correction_id, body):
    old, new, delta, region, epoch = decode(body)
    return Posting(sequence, correction_id, parse_litres(old), parse_litres(new),
                   parse_litres(delta), region, epoch)


def interpret_image(day, image):
    try:
        batch = batch_from_identity(image.batch)
        postings = tuple(posting_from_row(*row) for row in image.postings)
        receipts = []
        for key, body in image.receipts:
            receipt = receipt_from_body(body)
            if receipt.correction_id != key or receipt.day != day:
                raise InconsistentBook('receipt is stored under the wrong correction key')
            receipts.append(receipt)
        initial, current = parse_litres(image.initial_litres), parse_litres(image.current_litres)
    except (TypeError, ValueError, KeyError) as error:
        raise InconsistentBook('invalid official book material') from error
    if batch.day != day:
        raise InconsistentBook('source batch belongs to another station day')
    return OfficialDay(batch, initial, current, image.frontier, postings, tuple(receipts))


def read_official_day(store, day, epoch):
    return interpret_image(day, store.read_day(day, epoch))


def commit_posting(store, request):
    key = book_key(request.day, request.epoch)
    with store.write_transaction() as connection:
        header = store.header(connection, request.day, request.epoch)
        existing = find_receipt(connection, request.day, request.epoch, request.correction_id)
        if existing is not None:
            return check_receipt_request(existing, request.day, request.litres), False
        if store.region != request.region:
            raise NotOwner('correction region does not match the posting store')
        if header['inbound_move'] is not None and header['accepted_digest'] is None:
            raise NotOwner('the receiving book has not accepted the handoff')
        new = load_preparation(connection, request.day, request.epoch, request.correction_id)
        if new is None or new != request.litres:
            raise InconsistentBook('missing or mismatched correction preparation')
        old = parse_litres(header['current_litres'])
        sequence = header['frontier'] + 1
        posting = Posting(sequence, request.correction_id, old, new, new - old, store.region, request.epoch)
        receipt = PostingReceipt(request.day, request.correction_id, sequence, store.region,
                                 request.epoch, old, new, posting.delta)
        connection.execute('INSERT INTO postings VALUES (?, ?, ?, ?, ?, ?)',
                           (*key, sequence, request.correction_id, posting_body(posting)))
        record_receipt(connection, request.epoch, receipt)
        connection.execute(
            'UPDATE books SET current_litres = ?, frontier = ? WHERE station = ? AND day = ? AND epoch = ?',
            (litre_text(new), sequence, *key),
        )
        connection.execute(
            'DELETE FROM preparations WHERE station = ? AND day = ? AND epoch = ? AND correction_id = ?',
            (*key, request.correction_id),
        )
        return receipt, True
