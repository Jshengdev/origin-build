"""A camera's person sends the dog, as an ask: plan over the grid, a typed decision, the ask, the walk.
The route is planned first from where the dog believes it is to the camera's spot (ui/map.json cameras[]), then one
decision on words (dispatch / ask / ignore: Jev with JEV_API_KEY, else a stub that never dispatches); with WTDD_DISPATCH_AUTO off
(the default) a dispatch is asked in the thread first, and a person's yes runs approved=true. dry=true plans and decides
only (the page draws it; nothing posts, nothing moves) and never goes through the API; otherwise the API process that
owns the dog runs it. approved=true is refused unless the thread's own row says a person said yes to this trigger
(dispatch.approval), whoever the caller is. wtdd/dispatch.py is the contract; the page reads GET /dispatch.
  cp wtdd/fixtures/grid_wall.json ui/grid.json && python -m wtdd dispatch cam=lap1 dry=true; rm -f ui/grid.json"""
ARGS = {"cam": {"type": "string", "default": None, "doc": "a camera id on ui/map.json cameras[] (lap1)"},
        "approved": {"type": "boolean", "default": False,
                     "doc": "true = a person said yes on the thread: refused unless the listener's approved intruder.verdict "
                            "row for this trigger is in the ledger, under 120 s old; no model call, the dog walks"},
        "dry": {"type": "boolean", "default": False, "doc": "true = plan and decide only: no post, no pending question, no walk"},
        "trigger": {"type": "string", "default": None, "doc": "the sighting's key (cam:<id>:<epoch>); the posts are keyed on it"},
        "file": {"type": "string", "default": None, "doc": "the camera's frame to ask with (default: cams/<id>-boxed.jpg)"},
        "by": {"type": "string", "default": None, "doc": "not trusted when approved: the row's by is the verdict's sender"}}


def run(cam=None, approved=False, dry=False, trigger=None, file=None, by=None):
    if not cam:
        raise ValueError("cam= is required: a camera id from ui/map.json cameras[]")
    if not dry:   # dry never goes through _via_api: its default port 7788 is Johnny's live API
        from ..commands import _via_api
        via = _via_api("dispatch", cam=cam, approved=approved, trigger=trigger, file=file, by=by)
        if via is not None:
            return via
    from .. import dispatch
    if approved:   # a person's yes is the thread's row, never an argument: checked in the process that walks
        by = dispatch.approval(cam, trigger, by)
    return dispatch.run(cam, approved=approved, dry=dry, trigger=trigger, file=file, by=by)
