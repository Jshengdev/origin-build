"""Sign the shift's record: one record.signed {by, at, shift_id} row closes the shift; a second signature of the same
shift is refused with its own ok=false row. by defaults to the on-call person (WTDD_ON_CALL_NAME), shift_id to
the run in force (shift.current()). The ledger is the record: the shift is closed when an ok record.signed row exists, and the
signature counts only once it is read back from the ledger. Zero flags in the shift is a WARN, not a refusal (item 03)."""
ARGS = {"by": {"type": "string", "default": None, "doc": "the signer's name; default WTDD_ON_CALL_NAME"},
        "shift_id": {"type": "string", "default": None, "doc": "the shift to close; default the run in force: shift.json, else WTDD_SHIFT, else today YYYY-MM-DD"}}


def run(by=None, shift_id=None):
    import time
    from .. import config
    from ..chat import oncall
    from ..ledger import log, rows, step
    shift_id = shift_id or oncall.shift_id()
    at = time.strftime("%Y-%m-%dT%H:%M:%S")
    all_rows = rows()
    prior = oncall.signed(shift_id, all_rows)
    flags = sum(1 for r in all_rows if r.get("tool") == "chat.post" and r.get("ok")
                and (r.get("args") or {}).get("kind") == "escalate" and r["args"].get("shift_id") == shift_id)
    if not flags:
        log("central", f"WARN shift {shift_id} has 0 flags")
    with step("central", "record.signed", "wtdd", {"by": by, "at": at, "shift_id": shift_id}, {"signed": prior is not None, "flags": flags}) as r:
        by = r["args"]["by"] = by or config.get("WTDD_ON_CALL_NAME")   # no signer named and none configured: this row fails, naming the key
        if prior:
            raise PermissionError(f"refused: shift {shift_id} already signed by {prior['args']['by']} at {prior['args']['at']}")
        r["state_after"] = {"signed": True, "at": at, "shift_id": shift_id}
    back = oncall.signed(shift_id)   # the read-back: the ledger says the shift is closed, not this function
    if not back or back["args"]["at"] != at:
        raise RuntimeError(f"record.signed for shift {shift_id} not read back from the ledger")
    return {"by": by, "at": at, "shift_id": shift_id, "signed": True, "flags": flags}
