"""Offline unit tests for Nova's non-UI logic."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nova import calc, coderun, config, convert  # noqa: E402
from nova.docs import Doc, safe_filename  # noqa: E402
from nova.saint import SaintNetwork  # noqa: E402
from nova.store import Store  # noqa: E402


class StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "nova.db"
        self.store = Store(self.path)

    def tearDown(self) -> None:
        self.store.close()
        self.tmp.cleanup()

    def test_database_holds_65_units(self) -> None:
        units = self.store.list_units()
        self.assertEqual(len(units), config.RECORD_COUNT)
        self.assertEqual(units[0]["callsign"], "SAINT-001")
        self.assertEqual(units[-1]["callsign"], "SAINT-065")
        self.assertEqual(len({unit["callsign"] for unit in units}), 65)

    def test_seed_is_idempotent(self) -> None:
        second = Store(self.path)
        self.assertEqual(second.count("units"), 65)
        self.assertEqual(second.count("personnel"), self.store.count("personnel"))
        second.close()

    def test_unit_lookup_and_update(self) -> None:
        unit = self.store.get_unit("SAINT-005")
        self.assertIsNotNone(unit)
        self.assertIn("Johnny 5", unit["notes"])
        self.assertTrue(self.store.update_unit(unit["id"], status="maintenance", location="Bay 9", battery=42))
        updated = self.store.get_unit(5)
        self.assertEqual(updated["status"], "maintenance")
        self.assertEqual(updated["location"], "Bay 9")
        self.assertEqual(updated["battery"], 42)

    def test_unit_stats(self) -> None:
        stats = self.store.unit_stats()
        self.assertEqual(stats["total"], 65)
        self.assertEqual(sum(stats["by_status"].values()), 65)
        self.assertGreater(stats["average_battery"], 0)

    def test_people_and_projects(self) -> None:
        self.assertEqual(self.store.count("personnel"), 12)
        self.assertEqual(self.store.count("projects"), 8)
        self.assertTrue(self.store.list_projects("saint"))
        self.assertTrue(self.store.list_personnel("crosby"))

    def test_events_round_trip(self) -> None:
        event_id = self.store.add_event("2026-10-20", "09:00", "Standup")
        events = self.store.events_for_day("2026-10-20")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["title"], "Standup")
        self.assertEqual(len(self.store.events_for_month(2026, 10)), 1)
        self.store.delete_event(event_id)
        self.assertEqual(self.store.events_for_day("2026-10-20"), [])

    def test_notes_documents_and_alarms(self) -> None:
        note_id = self.store.create_note("Field note", "hello")
        self.store.save_note(note_id, "Field note", "hello world")
        self.assertEqual(self.store.get_note(note_id)["body"], "hello world")
        doc_id = self.store.create_document("Report", "body")
        self.store.save_document(doc_id, "Report", "new body")
        self.assertEqual(self.store.get_document(doc_id)["body"], "new body")
        alarm_id = self.store.add_alarm("07:30", "Shift")
        self.store.set_alarm_enabled(alarm_id, False)
        self.assertFalse(self.store.list_alarms()[0]["enabled"])
        self.store.delete_alarm(alarm_id)
        self.assertEqual(self.store.list_alarms(), [])

    def test_logs(self) -> None:
        before = self.store.count("logs")
        self.store.log("TEST", "one entry")
        self.assertEqual(self.store.count("logs"), before + 1)
        self.assertIn("one entry", self.store.list_logs(1)[0]["message"])


class ConfigTests(unittest.TestCase):
    def test_settings_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"NOVA_HOME": tmp}):
            paths = config.ensure_dirs()
            self.assertTrue(paths["home"].exists())
            settings = config.Settings()
            self.assertEqual(settings.get("access_code"), config.DEFAULT_ACCESS_CODE)
            self.assertTrue(settings.get("touch_keyboard"))
            settings.set("operator", "Tester")
            reloaded = config.Settings()
            self.assertEqual(reloaded.get("operator"), "Tester")
            self.assertFalse(reloaded.toggle("touch_keyboard"))
            self.assertFalse(config.Settings().get("touch_keyboard"))


class CalculatorTests(unittest.TestCase):
    def test_basic_arithmetic(self) -> None:
        self.assertEqual(calc.evaluate("2 + 3 * 4"), 14)
        self.assertEqual(calc.evaluate("(2 + 3) * 4"), 20)
        self.assertAlmostEqual(calc.evaluate("2 ** 10"), 1024)
        self.assertAlmostEqual(calc.evaluate("7 % 4"), 3)

    def test_functions_and_constants(self) -> None:
        self.assertAlmostEqual(calc.evaluate("sqrt(81)"), 9)
        self.assertAlmostEqual(calc.evaluate("fact(5)"), 120)
        self.assertAlmostEqual(calc.evaluate("round(pi, 2)"), 3.14)
        self.assertAlmostEqual(calc.evaluate("max(1, 5, 3)"), 5)

    def test_rejects_dangerous_input(self) -> None:
        for expression in ("__import__('os')", "open('x')", "().__class__", "lambda: 1"):
            with self.assertRaises(calc.CalcError):
                calc.evaluate(expression)

    def test_errors(self) -> None:
        with self.assertRaises(calc.CalcError):
            calc.evaluate("1/0")
        with self.assertRaises(calc.CalcError):
            calc.evaluate("nope(3)")
        with self.assertRaises(calc.CalcError):
            calc.evaluate("2 ** 9000")
        with self.assertRaises(calc.CalcError):
            calc.evaluate("")

    def test_format(self) -> None:
        self.assertEqual(calc.format_number(4.0), "4")
        self.assertEqual(calc.format_number(3.5), "3.5")


class ConverterTests(unittest.TestCase):
    def test_length_and_mass(self) -> None:
        self.assertAlmostEqual(convert.convert("Length", 1, "kilometers", "meters"), 1000)
        self.assertAlmostEqual(convert.convert("Mass", 1, "kilograms", "pounds"), 2.2046226218, places=6)
        self.assertEqual(convert.convert("Length", 0, "miles", "feet"), 0)

    def test_temperature(self) -> None:
        self.assertAlmostEqual(convert.convert("Temperature", 100, "celsius", "fahrenheit"), 212)
        self.assertAlmostEqual(convert.convert("Temperature", 32, "fahrenheit", "celsius"), 0)
        self.assertAlmostEqual(convert.convert("Temperature", 0, "celsius", "kelvin"), 273.15)

    def test_data_and_errors(self) -> None:
        self.assertEqual(convert.convert("Data", 1, "kilobytes", "bytes"), 1024)
        with self.assertRaises(convert.ConversionError):
            convert.convert("Length", 1, "meters", "bogus")
        with self.assertRaises(convert.ConversionError):
            convert.convert("Temperature", -500, "celsius", "kelvin")
        with self.assertRaises(convert.ConversionError):
            convert.parse_value("abc")

    def test_units_listing(self) -> None:
        self.assertIn("Length", convert.categories())
        self.assertIn("meters", convert.units("Length"))


class DocumentTests(unittest.TestCase):
    def test_editing(self) -> None:
        doc = Doc.from_text("hello world\nsecond line")
        doc.set_cursor(0, 5)
        doc.insert(",")
        self.assertEqual(doc.lines[0], "hello, world")
        doc.end()
        doc.newline()
        self.assertEqual(doc.lines[1], "")
        doc.insert("inserted")
        doc.backspace()
        self.assertEqual(doc.lines[1], "inserte")
        doc.delete()
        doc.move(-1, 0)
        self.assertEqual(doc.cy, 0)

    def test_line_merging(self) -> None:
        doc = Doc.from_text("one\ntwo")
        doc.set_cursor(1, 0)
        doc.backspace()
        self.assertEqual(doc.text, "onetwo")
        doc.set_cursor(0, 3)
        doc.delete()
        self.assertEqual(doc.text, "onewo")
        doc.set_cursor(0, 3)
        doc.delete()
        doc.delete()
        doc.delete()
        self.assertEqual(doc.text, "one")

    def test_search_and_replace(self) -> None:
        doc = Doc.from_text("Alpha beta\nALPHA gamma")
        hit = doc.find("alpha")
        self.assertEqual(hit[0], 0)
        doc.set_cursor(0, 1)
        hit = doc.find("alpha")
        self.assertEqual(hit[0], 1)
        self.assertEqual(doc.replace_all("alpha", "omega"), 2)
        self.assertEqual(doc.text, "omega beta\nomega gamma")
        self.assertTrue(doc.modified)

    def test_stats_and_filenames(self) -> None:
        doc = Doc.from_text("one two three\n\nfour")
        stats = doc.stats()
        self.assertEqual(stats["lines"], 3)
        self.assertEqual(stats["words"], 4)
        self.assertEqual(stats["paragraphs"], 2)
        self.assertEqual(safe_filename("Field Report: #1"), "Field_Report_1.txt")
        self.assertTrue(safe_filename("").endswith(".txt"))


class CodeRunnerTests(unittest.TestCase):
    def test_syntax_check(self) -> None:
        self.assertIsNone(coderun.syntax_error("print('ok')\n"))
        self.assertIn("line", coderun.syntax_error("def broken(:\n"))

    def test_run_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = coderun.run_source("print('hello nova')", tmp)
            self.assertTrue(result.ok)
            self.assertIn("hello nova", result.stdout)
            self.assertEqual(result.exit_code, 0)

    def test_failure_and_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            failed = coderun.run_source("raise SystemExit(3)", tmp)
            self.assertFalse(failed.ok)
            self.assertEqual(failed.exit_code, 3)
            slow = coderun.run_source("import time\ntime.sleep(2)", tmp, timeout=0.2)
            self.assertFalse(slow.ok)
            self.assertIn("Stopped after", slow.note)

    def test_sibling_imports_work(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "helper.py").write_text("VALUE = 42\n", encoding="utf-8")
            program = Path(tmp, "uses_helper.py")
            program.write_text("from helper import VALUE\nprint('value', VALUE)\n", encoding="utf-8")
            result = coderun.run_file(program)
            self.assertTrue(result.ok)
            self.assertIn("value 42", result.stdout)

    def test_console_has_no_network_code(self) -> None:
        banned = ("socket", "urllib", "http.client", "ftplib", "telnetlib", "requests", "aiohttp")
        for path in (ROOT / "nova").rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            for module in banned:
                self.assertNotIn(f"import {module}", source, f"{path} imports {module}")
                self.assertNotIn(f"from {module}", source, f"{path} imports {module}")


class SaintTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "nova.db")
        self.network = SaintNetwork(self.store, access_code="J5-1986", seed=1986)

    def tearDown(self) -> None:
        self.store.close()
        self.tmp.cleanup()

    def test_authentication(self) -> None:
        self.assertEqual(self.network.connect("SAINT-005").kind, "error")
        self.assertFalse(self.network.authenticated)
        self.assertEqual(self.network.authenticate("bad").kind, "error")
        self.assertEqual(self.network.authenticate("j5-1986").kind, "ok")
        self.assertTrue(self.network.authenticated)

    def test_lockout(self) -> None:
        for _ in range(3):
            self.network.authenticate("bad")
        self.assertTrue(self.network.locked)
        self.assertEqual(self.network.authenticate("J5-1986").kind, "error")

    def test_directives(self) -> None:
        self.network.authenticate("J5-1986")
        self.network.connect("SAINT-005")
        status = self.network.command("status")
        self.assertIn("CALLSIGN : SAINT-005", status.text)
        moved = self.network.command("move Bay 9")
        self.assertEqual(moved.kind, "ok")
        self.assertEqual(self.store.get_unit("SAINT-005")["location"], "Bay 9")
        dance = self.network.command("dance")
        self.assertIn("input", dance.text.lower())
        self.assertEqual(self.network.command("selfdestruct").kind, "warn")
        self.assertIsNotNone(self.network.unit)
        self.assertEqual(self.network.command("unknown-directive").kind, "warn")

    def test_self_destruct_requires_confirmation(self) -> None:
        self.network.authenticate("J5-1986")
        self.network.connect("SAINT-005")
        result = self.network.command("selfdestruct YES")
        self.assertTrue(result.kicked)
        self.assertIsNone(self.network.unit)
        self.assertEqual(self.store.get_unit("SAINT-005")["status"], "offline")

    def test_trace_terminates_link(self) -> None:
        self.network.authenticate("J5-1986")
        self.network.connect("SAINT-001")
        kicked = False
        for _ in range(120):
            result = self.network.command("scan")
            if result.kicked:
                kicked = True
                break
        self.assertTrue(kicked)
        self.assertIsNone(self.network.unit)


if __name__ == "__main__":
    unittest.main()
