"""Item 27 (legend-gauges): the map explains its own marks. Run: python -m unittest wtdd.test_page_layers -v

The page is one htm template and no browser runs here, so these are static reads of ui/index.html against the contract
the head cut for 27 (the headless screenshots 27-remote.png and 27-failed.png are the other half of the gate):
  - every top-level child of the map <svg> is the Legend mount or holds a layer wrapper, and every wrapper is exactly
    `<g data-layer="<name>" class=${layerOff("<name>")}>`: one per layer, the names equal to the legend table's
    (`const LAYERS = [...]`, one `layer: "<name>"` per row, in the 27 JS block) and covering main's eleven layers;
  - hidden is a class, never a gate: `layerOff(` appears in the svg only as a wrapper's class, the hidden set is not read
    inside the svg (the Legend mount aside), the legend maps every row (no LAYERS.filter), `[data-layer].off { display:
    none }` in the 27 CSS block; so a hidden layer stays mounted and its row keeps its count and its why;
  - the Legend is the svg's last child (drawn on top); the Gauges strip sits between the status cards and the grid, keeps
    SPARK_N = 30 served values in a useRef, reads the served keys, and neither component polls (no fetch, no setInterval);
  - no colour literal outside `var(--x, fallback)` in the 27 CSS and JS blocks, and no var() without a fallback;
  - the three reserved slots by marker: data-slot="mode" in the header (20), "livecheck" under the receipts (22),
    "camera" in the legend's Cams row (23), each on an element of class "slot", labelled with its item number;
  - the night-1 patches 1, 1b, 2 (ui/index.html) and 3 (wtdd/dog/session.py) byte for byte;
  - the shared DEMO_CACHE path: WTDD_STATE_FIXTURE=wtdd/fixtures/page/dog-state.json makes DogSession.state() that dict with
    source "stub" (labelled `# DEMO_CACHE:` where it is read; a missing file raises, never a default dog) and the page
    reads `source === "stub"`; unset, a fresh session's state() says connected false instead of raising (patch 3).
"""
from __future__ import annotations
import json
import os
import re
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("WTDD_LEDGER", os.path.join(tempfile.mkdtemp(), "ledger.jsonl"))   # before any wtdd.ledger import

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "ui" / "index.html"
SESSION = ROOT / "wtdd" / "dog" / "session.py"
FIXTURE = ROOT / "wtdd" / "fixtures" / "page" / "dog-state.json"
MAIN_LAYERS = {"house", "path", "guide", "trace", "stops", "lights", "field", "lidar", "dog", "cone", "mark"}
JS_START, JS_END = "// 27 · legend-gauges · start", "// 27 · legend-gauges · end"
CSS_START, CSS_END = "/* 27 · legend-gauges · start */", "/* 27 · legend-gauges · end */"
WRAPPER = re.compile(r'<g data-layer="([a-z0-9-]+)" class=\$\{layerOff\("([a-z0-9-]+)"\)\}>')
NAMED = ("red|green|blue|orange|yellow|white|black|gray|grey|purple|pink|brown|cyan|magenta|gold|navy|teal|lime|maroon|"
         "olive|silver|violet|crimson|tomato|coral|salmon|indigo|khaki|beige|ivory")
FUNCS = re.compile(r"\b(rgba?|hsla?|hwb|lab|lch|oklab|oklch|color)\(")
HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")
P1 = "const palette = Array.isArray(status?.hue) ? [...status.hue.filter("
P1B = '${Array.isArray(status?.hue) && status.strip && html`<div class="panel"><h2>State · read back</h2>'
P2 = ("const roomOf = (p, rooms) => ((rooms || []).find(r => inside(p, r.poly)) || {}).name || null;   "
      "// the room a map point sits in, for the page's save; field.py recomputes it anyway")
P3 = "        self.recheck = False   # no calibration loaded; state() reads this before any connect"
P3_NEXT = "        if CAL_FILE.exists():   # a calibration survives an API restart"


# ---------- a small reader for htm templates: JS expressions, strings, template literals, elements
CLOSE = {"(": ")", "[": "]", "{": "}"}


def _skip_quote(s: str, i: int) -> int:
    q, i = s[i], i + 1
    while s[i] != q:
        i += 2 if s[i] == "\\" else 1
    return i + 1


def _skip_template(s: str, i: int) -> int:
    i += 1
    while True:
        if s[i] == "\\":
            i += 2
        elif s[i] == "`":
            return i + 1
        elif s.startswith("${", i):
            i = _skip_js(s, i + 1)
        else:
            i += 1


def _skip_js(s: str, i: int) -> int:
    """s[i] is ( [ or {: the index just past its partner, skipping strings, template literals (and their ${}) and comments."""
    stack, i = [CLOSE[s[i]]], i + 1
    while i < len(s):
        c = s[i]
        if c in "\"'":
            i = _skip_quote(s, i)
        elif c == "`":
            i = _skip_template(s, i)
        elif s.startswith("//", i):
            i = s.index("\n", i)
        elif s.startswith("/*", i):
            i = s.index("*/", i) + 2
        elif c in CLOSE:
            stack.append(CLOSE[c]); i += 1
        elif c in ")]}":
            if c != stack.pop():
                raise AssertionError(f"unbalanced {c!r} at char {i}")
            i += 1
            if not stack:
                return i
        else:
            i += 1
    raise AssertionError("unterminated expression")


def _open_tag_end(s: str, i: int) -> int:
    """s[i] is the '<' of an opening tag: the index just past its '>' (attribute values and ${} skipped)."""
    j = i + 1
    while j < len(s):
        if s.startswith("${", j):
            j = _skip_js(s, j + 1)
        elif s[j] == '"':
            j = s.index('"', j + 1) + 1
        elif s[j] == ">":
            return j + 1
        else:
            j += 1
    raise AssertionError(f"unterminated tag at char {i}")


def _children(s: str, i: int) -> tuple[list[tuple[str, str, str]], int]:
    """Top-level nodes of template text from i up to the parent's closing tag: ('expr'|'elem'|'text', open, whole)."""
    out = []
    while i < len(s) and not s.startswith("</", i):
        if s.startswith("${", i):
            j = _skip_js(s, i + 1)
            out.append(("expr", s[i:j], s[i:j]))
        elif s[i] == "<":
            j = _open_tag_end(s, i)
            if s[j - 2] != "/":
                _, k = _children(s, j)
                j = s.index(">", k) + 1
            out.append(("elem", s[i:_open_tag_end(s, i)], s[i:j]))
        else:
            j = i
            while j < len(s) and s[j] != "<" and not s.startswith("${", j):
                j += 1
            out.append(("text", s[i:j], s[i:j]))
        i = j
    return out, i


def _between(text: str, start: str, end: str) -> str:
    a, b = text.find(start), text.find(end)
    if a < 0 or b < a:
        raise AssertionError(f"no block between {start!r} and {end!r} in {PAGE.name}")
    return text[a + len(start):b]


def _strip_vars(s: str) -> tuple[str, list[str]]:
    """s without its var(--x, fallback) spans; and every var() that has no fallback."""
    bad = []
    while (m := re.search(r"\bvar\(", s)):
        j = _skip_js(s, m.end() - 1)
        inner, depth, has = s[m.end():j - 1], 0, False
        for c in inner:
            depth += c in "([{"
            depth -= c in ")]}"
            if c == "," and depth == 0:
                has = True
                break
        if not has:
            bad.append(s[m.start():j])
        s = s[:m.start()] + s[j:]
    return s, bad


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = PAGE.read_text()

    def svg(self) -> tuple[str, list[tuple[str, str, str]]]:
        i = self.page.find("<svg ref=${svgRef}")
        self.assertGreaterEqual(i, 0, "the map <svg ref=${svgRef}> is gone")
        start = _open_tag_end(self.page, i)
        kids, k = _children(self.page, start)
        self.assertTrue(self.page.startswith("</svg>", k), "the map svg does not close where the reader expects")
        return self.page[start:k], [c for c in kids if not (c[0] == "text" and not c[2].strip())]

    def js(self) -> str:
        return _between(self.page, JS_START, JS_END)

    def css(self) -> str:
        return _between(self.page, CSS_START, CSS_END)

    def layers_table(self) -> list[str]:
        js = self.js()
        m = re.search(r"const LAYERS = \[", js)
        self.assertIsNotNone(m, "no `const LAYERS = [` legend table in the 27 JS block")
        table = js[m.end() - 1:_skip_js(js, m.end() - 1)]
        return re.findall(r'\blayer:\s*"([a-z0-9-]+)"', table)


class Layers(Base):
    def test_every_svg_child_is_a_layer_or_the_legend(self):
        body, kids = self.svg()
        for kind, opening, whole in kids:
            if kind == "elem" and opening.startswith("<${Legend}"):
                continue
            self.assertNotEqual(kind, "text", f"stray text at the svg's top level: {whole[:80]!r}")
            self.assertIn('data-layer="', whole, f"svg layer without a data-layer wrapper: {whole[:120]!r}")

    def test_wrappers_are_canonical_unique_and_listed(self):
        body, _ = self.svg()
        found = WRAPPER.findall(body)
        self.assertEqual(body.count('data-layer="'), len(found),
                         'every data-layer in the svg must be exactly <g data-layer="x" class=${layerOff("x")}>')
        for a, b in found:
            self.assertEqual(a, b, f"wrapper data-layer={a!r} toggles layerOff({b!r})")
        names = [a for a, _ in found]
        self.assertEqual(len(names), len(set(names)), f"one wrapper per layer: {sorted(names)}")
        self.assertLessEqual(MAIN_LAYERS, set(names), f"main's layers without a wrapper: {sorted(MAIN_LAYERS - set(names))}")
        table = self.layers_table()
        self.assertEqual(len(table), len(set(table)), f"one legend row per layer: {table}")
        self.assertEqual(set(table), set(names), "the legend table and the svg's wrappers must name the same layers")

    def test_hidden_is_a_class_never_a_gate(self):
        body, kids = self.svg()
        self.assertTrue("const layerOff = " in self.page, "no layerOff helper (the wrapper's class)")
        self.assertEqual(body.count("layerOff("), len(WRAPPER.findall(body)), "layerOff( used in the svg outside a wrapper's class")
        legend = [w for k, o, w in kids if k == "elem" and o.startswith("<${Legend}")]
        rest = body.replace(legend[0], "") if legend else body
        self.assertIsNone(re.search(r"\bhidden\b", rest), "the hidden set is read inside the svg: a hidden layer must stay mounted")
        self.assertFalse("LAYERS.filter(" in self.js(), "the legend drops rows: a hidden layer keeps its row")
        self.assertRegex(self.css(), r"\[data-layer\]\.off\s*\{\s*display\s*:\s*none\s*;?\s*\}")

    def test_legend_is_drawn_last_in_the_svg(self):
        body, kids = self.svg()
        self.assertEqual(self.page.count("<${Legend}"), 1, "exactly one Legend mount")
        self.assertTrue("function Legend(" in self.js(), "no Legend component in the 27 block")
        self.assertTrue(kids and kids[-1][1].startswith("<${Legend}"), "the Legend must be the svg's last child (on top)")


class Gauges(Base):
    def test_gauges_strip_under_the_status_cards(self):
        p = self.page
        self.assertEqual(p.count("<${Gauges}"), 1, "exactly one Gauges mount")
        self.assertLess(p.index('<div class="status-row">'), p.index("<${Gauges}"))
        self.assertLess(p.index("<${Gauges}"), p.index('<div class="grid">'))
        js = self.js()
        self.assertTrue("function Gauges(" in js, "no Gauges component in the 27 block")
        self.assertRegex(js, r"\bSPARK_N\s*=\s*30\b", "the sparkline holds thirty samples")
        self.assertTrue("useRef(" in js, "the samples live in a useRef")
        for key in ("hz", "age_ms", "dist_px", "err_deg", "age_s"):
            self.assertRegex(js, rf"\b{key}\b", f"no tile reads the served {key}")

    def test_no_new_poll(self):
        js = self.js()
        for word in ("fetch(", "setInterval("):
            self.assertFalse(word in js, f"27 adds a poll ({word}); the sparklines ride the polls already running")

    def test_stub_state_is_badged(self):
        self.assertRegex(self.js(), r'source\s*===\s*"stub"', "the page never reads source === \"stub\"")

    def test_blocks_sit_at_their_anchors(self):
        p = self.page
        self.assertTrue(all(m in p for m in (JS_START, JS_END, CSS_START, CSS_END)), "the 27 JS and CSS blocks are missing")
        self.assertLess(p.index(JS_END), p.index("createRoot("), "the 27 components go before createRoot(")
        self.assertLess(p.index(JS_START), p.index(JS_END))
        self.assertLess(p.index(CSS_END), p.index("</style>"), "the 27 CSS goes inside the style block")


class Colours(Base):
    def _check(self, where: str, text: str, css: bool) -> None:
        rest, bad = _strip_vars(text)
        self.assertEqual(bad, [], f"var() without a fallback in {where}")
        self.assertEqual(HEX.findall(rest), [], f"hex colour outside var() in {where}")
        self.assertIsNone(FUNCS.search(rest), f"colour function outside var() in {where}: {FUNCS.search(rest)}")
        named = (re.findall(rf":[^;{{}}]*\b({NAMED})\b", rest, re.I) if css else re.findall(rf"[\"']({NAMED})[\"']", rest, re.I))
        self.assertEqual(named, [], f"named colour outside var() in {where}")

    def test_new_css_colours_are_vars_with_fallback(self):
        self._check("the 27 CSS block", self.css(), css=True)

    def test_new_js_colours_are_vars_with_fallback(self):
        self._check("the 27 JS block", self.js(), css=False)


class Slots(Base):
    def _slot(self, name: str, number: str) -> int:
        hits = [m.start() for m in re.finditer(rf'data-slot="{name}"', self.page)]
        self.assertEqual(len(hits), 1, f'exactly one data-slot="{name}"')
        start = self.page.rfind("<", 0, hits[0])
        self.assertRegex(self.page[start:_open_tag_end(self.page, start)], r'\bclass="slot\b', f"the {name} slot is not an empty frame")
        self.assertRegex(self.page[hits[0]:hits[0] + 400], rf"\b{number}\b", f"the {name} slot does not name item {number}")
        return hits[0]

    def test_mode_chip_slot_in_the_header(self):
        i = self._slot("mode", "20")
        self.assertLess(self.page.index('<div class="top">'), i)
        self.assertLess(i, self.page.index('<div class="status-row">'))

    def test_livecheck_slot_under_the_receipts(self):
        i = self._slot("livecheck", "22")
        self.assertLess(self.page.index("Receipts · ledger.jsonl"), i)
        self.assertLess(i, self.page.index("Entity · the dog on the map"))

    def test_camera_glyph_slot_in_the_legend(self):
        i = self._slot("camera", "23")
        self.assertLess(self.page.index(JS_START), i)
        self.assertLess(i, self.page.index(JS_END))

    def test_slot_frame_is_drawn(self):
        self.assertRegex(self.css(), r"\.slot\b[^{]*\{[^}]*(dashed|dasharray)", "no dashed frame for the reserved slots")


class Patches(Base):
    def test_night1_page_patches_byte_for_byte(self):
        self.assertTrue(P1 in self.page, "patch 1 (palette guard) not applied byte for byte")
        self.assertFalse("const palette = status ? [" in self.page, "the unguarded palette line is still there")
        self.assertTrue(P1B in self.page, "patch 1b (read-back guard) not applied byte for byte")
        lines = self.page.splitlines()
        k = next(i for i, ln in enumerate(lines) if ln.startswith("const inside = "))
        self.assertEqual(lines[k + 1], P2, "patch 2 (roomOf) right after `const inside`")

    def test_night1_session_patch_byte_for_byte(self):
        lines = SESSION.read_text().splitlines()
        self.assertTrue(P3 in lines, "patch 3 (recheck before any calibration) not applied byte for byte")
        self.assertTrue(lines[lines.index(P3) + 1].startswith(P3_NEXT), "patch 3 sits right before `if CAL_FILE.exists()`")


class StateFixture(unittest.TestCase):
    def setUp(self):
        from wtdd import config
        config._load()   # .env first, so popping the key below is final
        self.saved = os.environ.pop("WTDD_STATE_FIXTURE", None)

    def tearDown(self):
        os.environ.pop("WTDD_STATE_FIXTURE", None)
        if self.saved is not None:
            os.environ["WTDD_STATE_FIXTURE"] = self.saved

    def test_fixture_is_served_as_stub(self):
        from wtdd.dog.session import DogSession
        os.environ["WTDD_STATE_FIXTURE"] = str(FIXTURE)
        st, fx = DogSession().state(), json.loads(FIXTURE.read_text())
        self.assertEqual(st.get("source"), "stub")
        self.assertIs(st["connected"], True)
        for k in ("hz", "age_ms"):
            self.assertEqual(st["state"][k], fx["state"][k])
        for k in ("dist_px", "err_deg"):
            self.assertEqual(st["follow"][k], fx["follow"][k])

    def test_missing_fixture_fails_loud(self):
        from wtdd.dog.session import DogSession
        os.environ["WTDD_STATE_FIXTURE"] = str(FIXTURE.with_name("absent.json"))
        with self.assertRaises(FileNotFoundError):   # the fixture read itself raises: no default dog, no silent live fallback
            DogSession().state()

    def test_unset_is_a_disconnected_dog_not_an_error(self):
        from wtdd.dog.session import DogSession
        st = DogSession().state()
        self.assertIs(st["connected"], False)
        self.assertNotEqual(st.get("source"), "stub")

    def test_fixture_read_is_labelled(self):
        lines = SESSION.read_text().splitlines()
        k = next((i for i, ln in enumerate(lines) if "WTDD_STATE_FIXTURE" in ln), None)
        self.assertIsNotNone(k, "session.py never reads WTDD_STATE_FIXTURE")
        self.assertTrue(any("# DEMO_CACHE:" in ln for ln in lines[max(0, k - 3):k + 1]), "the fixture read is not labelled # DEMO_CACHE:")


if __name__ == "__main__":
    unittest.main()
