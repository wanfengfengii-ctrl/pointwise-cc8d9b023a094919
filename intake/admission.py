from intake.batches import normalize_batch


def admit(warehouse, batch):
    """Validate all source rows before claiming the batch identifier."""
    return warehouse.sources.admit_batch(normalize_batch(batch))
