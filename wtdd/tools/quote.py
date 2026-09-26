"""The night's quote from ui/map.json: stops x nights x price per stop-night, beside the guard shift it replaces.
wtdd/schedule.py quote(): one quote.night row; price default WTDD_PRICE_PER_STOP_NIGHT, the guard shift WTDD_GUARD_SHIFT_USD
cited by WTDD_GUARD_SHIFT_CITE (any absent = RuntimeError)."""
ARGS = {"nights": {"type": "number", "default": 1, "doc": "nights quoted, whole, at least 1"},
        "price_per_stop_night": {"type": "number", "default": None, "doc": "USD per stop per night (default: WTDD_PRICE_PER_STOP_NIGHT)"}}


def run(nights=1, price_per_stop_night=None):
    import json
    from ..field import MAP
    from ..schedule import quote
    return quote(json.loads(MAP.read_text()), price_per_stop_night, nights)
