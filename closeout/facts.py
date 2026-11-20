from dataclasses import dataclass

from intake.batches import SourceBatch, batch_from_identity, batch_identity
from ledger.postings import OfficialDay, Posting, posting_body, posting_from_row
from storage import decode, encode, litre_text, parse_litres


@dataclass(frozen=True)
class FrozenFacts:
    number: int
    batch: SourceBatch
    region: str
    epoch: int
    initial_litres: int
    current_litres: int
    postings: tuple[Posting, ...]

    @property
    def day(self):
        return self.batch.day


def capture_facts(book: OfficialDay, region, epoch):
    return encode({
        'batch': batch_identity(book.batch),
        'region': region,
        'epoch': epoch,
        'initial': litre_text(book.initial_litres),
        'current': litre_text(book.current_litres),
        'postings': [[entry.sequence, entry.correction_id, posting_body(entry)] for entry in book.postings],
    })


def load_facts(number, body):
    contents = decode(body)
    return FrozenFacts(number, batch_from_identity(contents['batch']), contents['region'], contents['epoch'],
                       parse_litres(contents['initial']), parse_litres(contents['current']),
                       tuple(posting_from_row(*row) for row in contents['postings']))
