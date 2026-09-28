"""The listener never connects the dog itself. Run: python -m unittest wtdd.test_no_second_client -v
The API process holds the dog's one WebRTC slot. During an API restart a wake's look (or dog_cmd, a round) found no API,
and commands._via_api returned None, so DogSession.get() opened a second WebRTC client inside the listener. With
WTDD_API_ONLY=1, which `python -m wtdd.chat listen` sets at start, _via_api raises a ConnectionError naming the API
address instead, and the caller's failure path runs ("couldn't look", a FAILED row). The CLI keeps its fallback.
Offline: requests.post is patched to refuse, and DogSession.get fails the test if it is ever called."""
from __future__ import annotations
import argparse
import os
import unittest
from unittest import mock

import requests

from wtdd import commands, config
from wtdd.chat import __main__ as chat_main
from wtdd.dog import session

REFUSED = mock.patch("requests.post", side_effect=requests.exceptions.ConnectionError("connection refused"))
NO_DOG = mock.patch.object(session.DogSession, "get", side_effect=AssertionError("DogSession.get() called: a second WebRTC client"))


class ApiOnly(unittest.TestCase):
    def test_the_listeners_mode_raises_naming_the_api_and_never_connects_the_dog(self):
        with mock.patch.dict(os.environ, {"WTDD_API_ONLY": "1"}), REFUSED, NO_DOG:
            os.environ.pop("WTDD_API_PROCESS", None)
            for call in (lambda: commands.look("tilt"), lambda: commands.dog_cmd("Sit"), commands.do_round):
                with self.assertRaises(ConnectionError) as c:
                    call()
                self.assertIn(config.API, str(c.exception))
                self.assertIn("never connects the dog itself", str(c.exception))

    def test_the_cli_keeps_its_fallback(self):
        with mock.patch.dict(os.environ, {}), REFUSED:
            os.environ.pop("WTDD_API_ONLY", None)
            os.environ.pop("WTDD_API_PROCESS", None)
            self.assertIsNone(commands._via_api("dog_look", look="tilt"))

    def test_listen_turns_the_mode_on_at_start(self):
        seen = []
        fake = mock.MagicMock()
        fake.return_value.run.side_effect = lambda **k: seen.append(os.environ.get("WTDD_API_ONLY"))
        with mock.patch.dict(os.environ, {}), mock.patch("wtdd.chat.listen.Listener", fake):
            os.environ.pop("WTDD_API_ONLY", None)
            chat_main.cmd_listen(argparse.Namespace(guid="test", dry_run=True, listen_s=1.0, every=1.0, once=True))
        self.assertEqual(seen, ["1"])


if __name__ == "__main__":
    unittest.main()
