"""The therapist UI and the demo reset (backlog batch 6 of the 2026-11-12 review).

The page itself was exercised in a browser against a running server; what can be
checked without one is checked here: colour contrast, the things the review
found in the source, and the README demo walked through the API.
"""

import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

from helpers import IsolatedData, ServerCase

from haven import config, store  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
CSS = (REPO / "web" / "style.css").read_text(encoding="utf-8")
JS = (REPO / "web" / "app.js").read_text(encoding="utf-8")
HTML = (REPO / "web" / "index.html").read_text(encoding="utf-8")


def palette(block: str) -> dict:
    return {k: v for k, v in re.findall(r"--([a-z-]+):\s*(#[0-9a-fA-F]{6})", block)}


def luminance(colour: str) -> float:
    def channel(v):
        v = int(v, 16) / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * channel(colour[1:3]) + 0.7152 * channel(colour[3:5]) + 0.0722 * channel(colour[5:7])


def contrast(a: str, b: str) -> float:
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


class ContrastTest(unittest.TestCase):
    """6.7: UX-19. Text on its background, 4.5:1 or better, in both themes."""

    PAIRS = [("ink", "bg"), ("ink", "panel"), ("muted", "panel"), ("muted", "bg"), ("accent", "panel"), ("accent", "accent-soft"),
             ("on-accent", "accent"), ("good", "good-soft"), ("good", "panel"), ("warn", "warn-soft"), ("warn", "panel"),
             ("bad", "bad-soft"), ("bad", "panel"), ("ink", "warn-soft"), ("ink", "bad-soft"), ("ink", "accent-soft"), ("ink", "hl"),
             ("muted", "accent-soft"), ("muted", "warn-soft"), ("muted", "bad-soft"), ("muted", "good-soft")]

    def test_light_and_dark(self):
        light, dark = CSS.split("@media (prefers-color-scheme: dark)")[0], CSS.split("@media (prefers-color-scheme: dark)")[1].split("}\n}")[0]
        for name, colours in (("light", palette(light)), ("dark", palette(dark))):
            self.assertEqual(len(colours), 15, name)
            for fg, bg in self.PAIRS:
                ratio = contrast(colours[fg], colours[bg])
                self.assertGreaterEqual(ratio, 4.5, f"{name}: --{fg} on --{bg} is {ratio:.2f}")

    def test_borders_are_visible(self):
        # The card border was 1.32:1 on white and vanished on a projector.
        light = palette(CSS.split("@media (prefers-color-scheme: dark)")[0])
        self.assertGreaterEqual(contrast(light["line"], light["panel"]), 1.9)


class SourceTest(unittest.TestCase):
    """What the front-end review found by reading the source."""

    def test_no_native_prompt_and_a_signing_dialog(self):  # UX-16
        self.assertNotRegex(JS, r"(?<![A-Za-z_.])prompt\(")
        self.assertIn('<dialog id="sign-dialog"', HTML)
        self.assertIn("我已逐句核對", HTML)
        self.assertRegex(HTML, r'name="checked" required')
        self.assertIn('dateStyle: "long"', JS)

    def test_api_paths_are_encoded(self):  # SEC-18
        for m in re.finditer(r"`/api/[^`]*\$\{([^}]+)\}", JS):
            self.assertTrue(m.group(1).startswith("encodeURIComponent(") or m.group(1) == "q", m.group(0))

    def test_late_answers_are_dropped(self):  # UX-4
        self.assertGreaterEqual(JS.count("my !== nav"), 6)
        self.assertIn("session.session_id !== sid", JS)

    def test_confirmations_follow_a_key_not_the_words(self):  # UX-7
        self.assertIn("confirmed.has(s.key)", JS)
        self.assertNotIn("confirmed.has(s.text)", JS)
        self.assertNotIn("confirmed.add(s.text)", JS)

    def test_status_is_not_colour_only_and_updates_are_announced(self):  # UX-19, UX-20
        for state in ("supported", "weak", "unsupported", "dirty", "confirmed"):
            self.assertRegex(JS, rf'{state}: \{{ mark: "[^"]+", name: "[^"]+" \}}')
        self.assertIn("風險線索", JS)  # the text tag on a risk line
        self.assertGreaterEqual((HTML + JS).count("aria-live"), 6)
        self.assertNotIn("placeholder=\"會談編號", HTML)  # a label, not only a placeholder
        self.assertIn('lang="en"', HTML)
        self.assertNotIn("scrollIntoView({ block: \"center\", behavior: \"smooth\" });\n  });\n}", JS.split("function focusNextBlocking")[0])

    def test_layout_keeps_two_columns_on_a_zoomed_projector(self):  # UX-18
        # 1280 px at 150% zoom is 853 CSS px: the columns must not collapse above 720.
        widths = [int(w) for w in re.findall(r"@media \(max-width: (\d+)px\)", CSS)]
        collapse = CSS.split("@media (max-width: 720px)")[1]
        self.assertIn(".workspace { grid-template-columns: minmax(0, 1fr); }", collapse)
        self.assertEqual(sorted(widths), [720, 1100])
        self.assertNotRegex(CSS.split("@media (max-width: 1100px)")[1].split("@media")[0], r"\.workspace")
        self.assertRegex(CSS, r"\.risk-panel \{[^}]*max-height: 45vh")  # UX-21

    def test_wording(self):  # UX-22, UX-17, SEC-I8
        for old in ("確認無誤", "加入測試句", "用字與引用段落相符", "無法評估評估品質", "所有資料皆為模擬會談", "rule-based demo`"):
            self.assertNotIn(old, JS + HTML, old)
        for new in ("保留此句（我已核對）", "示範：插入捏造句", "載入逐字稿", "真實個案資料", "跳到下一句待處理", "＋ 新增句子", "刪除這一句"):
            self.assertIn(new, JS + HTML, new)


class DemoWalkthroughTest(ServerCase, unittest.TestCase):
    """6.1: UX-1, UX-I3, UX-I9. The README demo, start to finish, in demo mode."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = dict(os.environ, HAVEN_DATA_DIR=str(config.DATA_DIR), HAVEN_LLM="demo")
        # A database in which S04 is already signed, as the reviewer found on the laptop.
        cls.call("/api/sessions/C002-S05/open", {})
        store.audit("before_reset", "x")
        os.rename(config.DB_FILE, config.DATA_DIR / "haven.db")
        cls.old_db = config.DB_FILE
        config.DB_FILE = config.DATA_DIR / "haven.db"
        cls.run_reset = staticmethod(lambda *args: subprocess.run([sys.executable, str(REPO / "scripts" / "reset_demo.py"), *args], env=env, capture_output=True, text=True))
        cls.out = cls.run_reset()

    @classmethod
    def tearDownClass(cls):
        config.DB_FILE = cls.old_db
        super().tearDownClass()

    def test_1_reset_leaves_every_session_drafted_and_unsigned(self):
        self.assertEqual(self.out.returncode, 0, self.out.stderr)
        self.assertEqual(len(list(config.DATA_DIR.glob("haven.db-backup-*"))), 1)  # the old database is kept, not deleted
        for sid in ("C001-S03", "C001-S04", "C002-S05"):
            self.assertIsNotNone(store.get_result(sid))
            self.assertIsNone(store.get_signature(sid))
        self.assertTrue(store.verify_audit()["ok"])

    def test_2_brief_shows_five_alerts(self):
        _, brief = self.call("/api/clients/C001/brief")
        self.assertEqual(len(brief["outcome"]["alerts"]), 5)
        self.assertEqual([m["signed"] for m in brief["sessions_meta"]], [False, False])
        self.assertTrue(all(m["simulated"] and m["processed"] for m in brief["sessions_meta"]))

    def test_3_demo_mode_has_one_red_sentence_and_says_it_was_planted(self):
        _, r = self.call("/api/sessions/C001-S04/open", {})
        red = [s for s in r["note"]["sections"]["P"] if s["status"] == "unsupported"]
        self.assertEqual([s["text"] for s in red], ["安排下週五提前會談。"])
        self.assertIn("下週", red[0]["reason"])
        self.assertTrue(any("示範用" in w for w in r["warnings"]))
        self.assertEqual(r["client_alias"], "小安（化名）")
        self.assertEqual(r["therapist"], "王心理師")

    def test_4_fix_verify_sign(self):
        r, note = self.draft("C001-S04")
        status, body = self.call("/api/sessions/C001-S04/sign", {"signed_by": "王心理師", "note": note})
        self.assertEqual(status, 409)  # blocked while the red sentence stands
        self.assertIn("message_zh", body)
        for s in note["sections"]["P"]:
            if s["text"] == "安排下週五提前會談。":
                s["text"] = "下次會談提前到這週五。"
        _, v = self.call("/api/sessions/C001-S04/verify", note)
        self.assertEqual(v["verification"]["unsupported"], 0)
        note["sections"]["S"].append({"text": "個案表示與母親關係良好，最近常一起出遊。", "evidence": []})  # 示範：插入捏造句
        self.assertEqual(self.call("/api/sessions/C001-S04/sign", {"signed_by": "王心理師", "note": note})[0], 409)
        note["sections"]["S"].pop()
        self.assertEqual(self.call("/api/sessions/C001-S04/sign", {"signed_by": "王心理師", "note": note})[0], 200)
        _, signed = self.call("/api/sessions/C001-S04")
        self.assertTrue(signed["signed"])
        self.assertIn("下次會談提前到這週五。", [s["text"] for s in signed["note"]["sections"]["P"]])

    def test_5_reset_again_unsigns_and_no_example_flag_works(self):
        out = self.run_reset("--no-example")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIsNone(store.get_signature("C001-S04"))
        self.assertEqual(store.get_result("C001-S04")["verification"]["unsupported"], 0)

    def test_6_reset_refuses_real_sessions(self):
        with IsolatedData() as data:
            data.add_session("C001-S09", [("client", "最近睡不好。")])
            path = config.SESSIONS_DIR / "C001-S09.json"
            path.write_text(json.dumps(dict(json.loads(path.read_text(encoding="utf-8")), simulated=False), ensure_ascii=False), encoding="utf-8")
            store.audit("x", "y")
            env = dict(os.environ, HAVEN_DATA_DIR=str(config.DATA_DIR), HAVEN_LLM="demo")
            out = subprocess.run([sys.executable, str(REPO / "scripts" / "reset_demo.py")], env=env, capture_output=True, text=True)
            self.assertEqual(out.returncode, 1)
            self.assertIn("C001-S09.json", out.stderr)


if __name__ == "__main__":
    unittest.main()
