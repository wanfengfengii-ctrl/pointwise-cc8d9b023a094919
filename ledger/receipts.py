from dataclasses import dataclass

from intake.stations import StationDay
from ledger.region_store import book_key
from storage import Conflict, InconsistentBook, decode, encode, litre_text, parse_litres


@dataclass(frozen=True)
class PostingReceipt:
    day: StationDay
    correction_id: str
    sequence: int
    issued_region: str
    issued_epoch: int
    old_litres: int
    new_litres: int
    delta: int


def receipt_body(receipt):
    return encode([receipt.day.key, receipt.correction_id, receipt.sequence,
                   receipt.issued_region, receipt.issued_epoch,
                   litre_text(receipt.old_litres), litre_text(receipt.new_litres), litre_text(receipt.delta)])


def receipt_from_body(body):
    day, correction_id, sequence, region, epoch, old, new, delta = decode(body)
    return PostingReceipt(StationDay(*day), correction_id, sequence, region, epoch,
                          parse_litres(old), parse_litres(new), parse_litres(delta))


def record_receipt(connection, epoch, receipt):
    connection.execute('INSERT INTO receipts VALUES (?, ?, ?, ?, ?)',
                       (*book_key(receipt.day, epoch), receipt.correction_id, receipt_body(receipt)))


def find_receipt(connection, day, epoch, correction_id):
    row = connection.execute(
        'SELECT body FROM receipts WHERE station = ? AND day = ? AND epoch = ? AND correction_id = ?',
        (*book_key(day, epoch), correction_id),
    ).fetchone()
    if row is None:
        return None
    receipt = receipt_from_body(row['body'])
    if receipt.day != day or receipt.correction_id != correction_id:
        raise InconsistentBook('receipt is stored under the wrong correction key')
    return receipt


def check_receipt_request(receipt, day, litres):
    if (receipt.day, receipt.new_litres) != (day, litres):
        raise Conflict(f'correction {receipt.correction_id} has different parameters')
    return receipt
