"""Post text (and optionally a photo path) to the one allowed group chat, behind the gate and the never-twice claim."""
ARGS = {"text": {"type": "string", "default": "what the dog doin"}, "file": {"type": "string", "default": None},
        "trigger": {"type": "string", "default": None, "doc": "idempotence key; defaults to a timestamp"}}


def run(text="what the dog doin", file=None, trigger=None):
    import time
    from .. import config
    from ..chat.__main__ import post
    return post(config.get("WTDD_CHAT_GUID"), trigger or f"remote-{int(time.time())}", "remote", text, file)
