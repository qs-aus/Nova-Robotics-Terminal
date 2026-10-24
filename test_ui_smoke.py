"""End-to-end smoke tests: drive the real console through a pseudo-terminal."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
if str(HERE.parent) not in sys.path:
    sys.path.insert(0, str(HERE.parent))

from vt import ConsoleSession  # noqa: E402


class ConsoleTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.session = ConsoleSession(rows=30, cols=100)
        self.assertTrue(self.session.wait_for("NOVA / SAINT CONTROL", 10), self.screen())
        self.session.read(0.3)

    def tearDown(self) -> None:
        self.session.close()

    def screen(self) -> str:
        return self.session.screen()

    def expect(self, needle: str, timeout: float = 6.0) -> None:
        self.assertTrue(
            self.session.wait_for(needle, timeout),
            f"Expected {needle!r} on screen:\n{self.screen()}",
        )


class HomeAndDatabaseTests(ConsoleTestCase):
    def test_home_lists_every_program(self) -> None:
        screen = self.screen()
        for label in (
            "Nova Database",
            "Calendar",
            "Clock & Timers",
            "Calculator",
            "Notes",
            "Unit Converter",
            "Word Processor",
            "Code Studio",
            "SAINT Remote Access",
            "System",
        ):
            self.assertIn(label, screen)
        self.assertIn("65 SAINT records", screen)
        self.assertIn("F2 Keyboard", screen)

    def test_database_has_65_units_and_stats(self) -> None:
        self.session.key("enter")
        self.expect("NOVA DATABASE")
        self.expect("SAINT-001")
        self.expect("65 units")
        self.session.type_text("5")
        self.expect("NOVA DATABASE SUMMARY")
        self.expect("chassis records : 65")
        self.session.key("f10")
        self.expect("NOVA / SAINT CONTROL")


class DailyProgramTests(ConsoleTestCase):
    def test_calculator_evaluates(self) -> None:
        self.session.type_text("4")
        self.expect("CALCULATOR")
        self.session.type_text("2+2\r")
        self.expect("Evaluated locally")
        self.expect("2+2 = 4")

    def test_calendar_adds_an_event(self) -> None:
        self.session.type_text("2")
        self.expect("CALENDAR")
        self.session.type_text("a")
        self.expect("NEW EVENT")
        self.session.key("enter")
        self.expect("Title:")
        self.session.type_text("Nova test event\r")
        self.expect("Added")
        self.session.type_text("v")
        self.expect("MONTH AGENDA")
        self.expect("Nova test event")
        self.session.key("f10")
        self.expect("CALENDAR")
        self.session.key("f10")
        self.expect("NOVA / SAINT CONTROL")

    def test_converter_swaps_units(self) -> None:
        self.session.type_text("6")
        self.expect("CONVERTER")
        self.expect("RESULT")
        self.session.type_text("s")
        self.expect("1,000 meters")


class ProductivityTests(ConsoleTestCase):
    def test_word_processor_saves(self) -> None:
        self.session.type_text("7")
        self.expect("DOCUMENTS")
        self.session.key("enter")
        self.expect("Welcome Packet")
        self.session.type_text("Q")
        self.session.key("ctrl-s")
        self.expect("Saved")
        self.session.key("f10")
        self.expect("DOCUMENTS")
        self.session.key("f10")
        self.expect("NOVA / SAINT CONTROL")

    def test_code_studio_runs_a_program(self) -> None:
        self.session.type_text("8")
        self.expect("CODE STUDIO")
        self.session.key("enter")
        self.expect("CODE STUDIO")
        self.session.key("f9")
        self.expect("RUN OUTPUT", 8)
        self.expect("Exit code: 0")
        self.session.key("f10")
        self.expect("CODE STUDIO")
        self.session.key("f10")
        self.expect("PYTHON WORKSPACE")
        self.session.key("f10")
        self.expect("NOVA / SAINT CONTROL")


class SaintTests(ConsoleTestCase):
    def test_remote_access_authenticates_and_commands(self) -> None:
        self.session.type_text("9")
        self.expect("SAINT REMOTE ACCESS")
        self.expect("Demo access code: J5-1986")
        self.session.key("enter")
        self.expect("NOVA SECURITY")
        self.session.type_text("J5-1986\r", 0.8)
        self.expect("UPLINK —")
        self.session.type_text("status\r")
        self.expect("CALLSIGN")
        self.session.type_text("dance\r")
        self.expect("jaunty")
        self.session.key("f4")
        self.expect("UPLINK SCAN")
        self.session.key("f10")
        self.expect("NOVA / SAINT CONTROL")


class TouchKeyboardTests(ConsoleTestCase):
    def test_mouse_taps_type_into_a_prompt(self) -> None:
        self.session.type_text("5")
        self.expect("QUICK NOTES")
        self.session.type_text("n")
        self.expect("NEW NOTE")
        self.session.key("f2")
        self.expect("ON-SCREEN KEYBOARD")
        self.expect("SHIFT")
        # Geometry for a 100x30 terminal, verified by keyboard._Layout:
        # box starts at x=21, y=17; digit row begins at (23, 19); controls at y=25.
        self.session.click(24, 19)
        self.session.read(0.3)
        self.session.click(68, 25)
        self.session.read(0.4)
        self.expect("Field note1")
        self.session.key("esc")
        self.expect("QUICK NOTES")
        self.session.key("f10")
        self.expect("NOVA / SAINT CONTROL")


class BootAndExitTests(unittest.TestCase):
    def test_boot_splash_and_quit_confirmation(self) -> None:
        session = ConsoleSession(rows=30, cols=100, args=())
        try:
            self.assertTrue(session.wait_for("Nova Database", 10), session.screen())
            session.send(b"\x11", 0.5)
            self.assertIn("QUIT NOVA", session.screen())
            session.send(b"y", 1.5)
            code = session.proc.wait(timeout=5)
            self.assertEqual(code, 0)
            self.assertIn("Johnny 5 is alive", session.raw.decode("utf-8", "replace"))
        finally:
            session.close()


if __name__ == "__main__":
    unittest.main()
