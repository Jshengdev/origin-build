# 18-1 · a fixture ledger puts a real photo in the screenshot

**Symptom.** The first `docs/evidence/night-2/18-remote.png`, taken with the dry API serving
`WTDD_LEDGER=<a copy of wtdd/fixtures/evals/dispatch.jsonl>`, showed a photo of people in "The eye · what it sees"
panel. Nothing in the fixture is a photo.

**Root cause.** The page's eye panel draws `/pictures/look-tilt.jpg?t=<ts>` as soon as the ledger has an ok
`llm.generate` row with `agent: "watch"` (ui/index.html, the eye panel's `seen` lookup). The API serves `/pictures/`
from `~/Pictures/wtdd` on this Mac, the real dog's last look, whatever the ledger says. A fixture row that copies the
look's `llm.generate` shape therefore pulls a real, personal frame into any screenshot of the remote.

**Fix (verbatim).** The screenshot's scratch ledger drops that one row; the committed fixture is unchanged:

    grep -v '"tool": "llm.generate"' wtdd/fixtures/evals/dispatch.jsonl > /tmp/night1/18/shots/ledger-asked.jsonl
    WTDD_LEDGER=/tmp/night1/18/shots/ledger-asked.jsonl .venv/bin/python -m wtdd.api 7925

**Verify.** The retaken `18-remote.png` shows "no look yet · python -m wtdd dog_say" in the eye panel and no photo
anywhere; `18-failed.png` (its ledger has no `llm.generate` row) likewise. Before committing any remote screenshot,
look at the eye panel.
