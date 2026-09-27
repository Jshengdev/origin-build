"""S9 · the dog on the remote's map is a pill at its real size: the Go2's body, 0.70 m long and 0.31 m wide, centred on the
position the dog reports (its body's middle), long axis along its heading, the head end marked. Johnny, live on
2026-09-27: "for the dog shape make it a pill so that i can see its butt from the head down". Drawn from the scale in
force (GET /dog/scale), so the slider resizes it; with no scale known yet, only the dot is drawn. Reads ui/index.html's
source, as test_drive_keys does.
  python -m unittest wtdd.test_dog_pill
"""
import pathlib
import unittest

PAGE = (pathlib.Path(__file__).resolve().parent.parent / "ui" / "index.html").read_text()


class DogPill(unittest.TestCase):
    def test_the_scale_is_read_in_every_view(self):
        self.assertIn("useEffect(() => { readScale(); }, [admin]);", PAGE)

    def test_the_body_is_drawn_at_the_go2s_size_from_the_scale(self):
        body = next((l for l in PAGE.splitlines() if "const m = scale?.px_per_m" in l), "")
        self.assertIn("0.70 * m", body)
        self.assertIn("0.31 * m", body)
        self.assertIn('class="dogbody"', PAGE)
        self.assertIn('class="doghead"', PAGE)

    def test_the_body_is_a_round_capped_line_that_takes_no_clicks(self):
        css = next((l for l in PAGE.splitlines() if l.strip().startswith(".dogbody")), "")
        self.assertIn("stroke-linecap: round", css)
        self.assertIn("pointer-events: none", css)


if __name__ == "__main__":
    unittest.main()
