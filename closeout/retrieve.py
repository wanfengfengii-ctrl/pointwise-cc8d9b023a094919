def get_frozen(warehouse, number):
    """Load the numbered immutable record from the archive alone."""
    return warehouse.archive.load_frozen(number)
