"""Say one of the two fixed lines on the dog's own speaker (AudioHub), one dog.say row with the code and the player state read back.
Only `who dis?!` and `ok, standing down` (the chat's ask and stand-down; anything else is a FAILED row with nothing
sent); the first say of a line renders it on this Mac and uploads it once (wtdd/dog/audio.py). Not dog_say: that tool
is the vision sentence posted to the chat. volume 0..10 sets the dog's volume first and reads it back. Returns
{text, code, at, ms, uuid, seconds, player_state}."""
ARGS = {"text": {"type": "string", "default": "who dis?!", "doc": "who dis?! | ok, standing down"},
        "volume": {"type": "number", "default": None, "doc": "0..10: set the dog's volume first, read back (VUI); empty = leave it"}}


def run(text="who dis?!", volume=None):
    from .. import config
    level = int(volume) if isinstance(volume, float) and volume.is_integer() else volume   # 5.0 from JSON is 5; 5.5 is refused in the row
    if (config.maybe("WTDD_SAY_STUB") or "0").lower() not in ("0", "false", "no"):   # DEMO_CACHE: the whole say on the recording stub (rows cached/stub, no dog, no API); unset WTDD_SAY_STUB (or 0) for the dog's own speaker
        from ..dog import audio
        return audio.stub_say(text, level)
    from ..commands import _via_api
    via = _via_api("say", text=text, volume=level)
    if via is not None:
        return via
    from ..dog.session import DogSession
    return DogSession.get().say(text, level)
