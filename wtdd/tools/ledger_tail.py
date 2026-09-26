"""The last N ledger rows (the receipts)."""
ARGS = {"n": {"type": "number", "default": 20}}


def run(n=20):
    from ..ledger import rows
    return {"rows": rows(int(n))}
