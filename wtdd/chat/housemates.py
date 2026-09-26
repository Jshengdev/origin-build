"""Who the dog listens to: HOUSEMATES maps a chat.db handle to a first name.

Johnny fills it in. Keys are handles exactly as chat.db stores them (handle.id: an E.164 phone like "+13105551234", or an
email); values are first names. Get the handles from `python -m wtdd.chat chats` and the sender column of `watch`.
The dict has been empty since it was created, so every consumer's empty-dict branch is the live one: the Listener lets any
member of the group wake the dog (one WARN at the first message), `watch` never prints a TRIGGER marker, and `reply`
finds no trigger. Unknown senders render as their handle in the chat context."""
from __future__ import annotations

HOUSEMATES: dict[str, str] = {}


def name(handle: str) -> str:
    return HOUSEMATES.get(handle, handle)
