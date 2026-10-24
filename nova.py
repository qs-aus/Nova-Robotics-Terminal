#!/usr/bin/env python3
"""Nova Robotics SAINT Control — launch the offline field console.

Examples
--------
    python3 nova.py                 # start the console
    python3 nova.py --report        # print a database report without curses
    python3 nova.py --self-test     # run internal offline checks
    python3 nova.py --home ./usb    # keep all data on a USB stick
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nova import calc, coderun, config, convert  # noqa: E402
from nova.docs import Doc  # noqa: E402
from nova.store import Store  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nova",
        description="Nova Robotics SAINT Control — a self-contained, offline field console.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "The console stores everything in one folder (default ~/.nova_robotics).\n"
            "No network access is used or required."
        ),
    )
    parser.add_argument("--home", metavar="DIR", help="data folder (overrides NOVA_HOME)")
    parser.add_argument("--report", action="store_true", help="print the offline database report and exit")
    parser.add_argument("--self-test", action="store_true", help="run internal self checks and exit")
    parser.add_argument("--no-boot", action="store_true", help="skip the boot animation")
    parser.add_argument("--touch", dest="touch", action="store_true", help="enable the on-screen keyboard by default")
    parser.add_argument("--no-touch", dest="touch", action="store_false", help="disable the on-screen keyboard by default")
    parser.add_argument("--version", action="version", version=f"Nova {config.VERSION} (offline)")
    parser.set_defaults(touch=None)
    return parser


def report(store: Store, settings: config.Settings, path_map: dict) -> None:
    stats = store.unit_stats()
    line = "=" * 68
    print(line)
    print(f" {config.APP_NAME}   v{config.VERSION}   [OFFLINE]")
    print(f" {config.TAGLINE}")
    print(line)
    print(f"Data folder : {path_map['home']}")
    print(f"Database    : {path_map['db']}")
    print(f"Documents   : {path_map['docs']}")
    print(f"Programs    : {path_map['code']}")
    print(f"Operator    : {settings.get('operator')}")
    print(f"Touch keys  : {'enabled' if settings.get('touch_keyboard') else 'disabled'}")
    print()
    print(f"NOVA DATABASE — {stats['total']} SAINT chassis records")
    for status, count in sorted(stats["by_status"].items()):
        print(f"  {status:<12} {count:>3}")
    print(f"  average battery {stats['average_battery']}%")
    units = store.list_units()
    if units:
        first, last = units[0], units[-1]
        print(f"  range: {first['callsign']} .. {last['callsign']}")
        johnny = store.get_unit("SAINT-005")
        if johnny:
            print(f"  SAINT-005: {johnny['model']} at {johnny['location']} ({johnny['status']})")
    print()
    print("TABLES")
    for table in ("units", "personnel", "projects", "documents", "notes", "events", "alarms", "logs"):
        print(f"  {table:<12} {store.count(table):>4}")
    print()
    print("PROGRAMS")
    for name in (
        "Nova Database (65 records)",
        "Calendar",
        "Clock & Timers (stopwatch, countdown, alarms)",
        "Calculator",
        "Notes",
        "Unit Converter",
        "Word Processor",
        "Code Studio (Python, offline runner)",
        "SAINT Remote Access (simulated)",
        "System / Settings / Logs",
    ):
        print(f"  - {name}")
    print()
    if str(settings.get("access_code")) == config.DEFAULT_ACCESS_CODE:
        print(f"Demo SAINT access code: {config.DEFAULT_ACCESS_CODE} (change it in System > Settings)")
    else:
        print("SAINT access code: configured in System > Settings")
    print(line)


def self_test(store: Store, settings: config.Settings) -> int:
    results: list[tuple[str, bool, str]] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        results.append((name, bool(condition), detail))

    units = store.list_units()
    check("database holds 65 units", len(units) == config.RECORD_COUNT, f"found {len(units)}")
    check("unit callsigns are SAINT-001..065", bool(units) and units[0]["callsign"] == "SAINT-001" and units[-1]["callsign"] == "SAINT-065")
    check("personnel records seeded", store.count("personnel") >= 10, str(store.count("personnel")))
    check("projects seeded", store.count("projects") >= 5, str(store.count("projects")))

    try:
        check("calculator arithmetic", calc.evaluate("2 + 3 * 4") == 14)
        check("calculator functions", abs(calc.evaluate("sqrt(81)") - 9) < 1e-9)
        blocked = False
        try:
            calc.evaluate("__import__('os').system('echo hi')")
        except calc.CalcError:
            blocked = True
        check("calculator rejects code injection", blocked)
    except Exception as exc:  # pragma: no cover - defensive
        check("calculator arithmetic", False, str(exc))

    try:
        check("converter length", abs(convert.convert("Length", 1, "kilometers", "meters") - 1000) < 1e-9)
        check("converter temperature", abs(convert.convert("Temperature", 100, "celsius", "fahrenheit") - 212) < 1e-9)
    except Exception as exc:  # pragma: no cover
        check("converter", False, str(exc))

    doc = Doc.from_text("hello world\nsecond line")
    doc.set_cursor(0, 5)
    doc.insert(",")
    check("editor buffer editing", doc.lines[0].startswith("hello,"))
    check("editor search and replace", doc.replace_all("line", "row") >= 1 and "row" in doc.text)

    check("code syntax check accepts valid Python", coderun.syntax_error("print('hi')\n") is None)
    check("code syntax check rejects broken Python", coderun.syntax_error("def broken(:\n") is not None)

    try:
        from nova.saint import SaintNetwork

        network = SaintNetwork(store, access_code=settings.get("access_code"), seed=1986)
        check("SAINT rejects bad access code", network.authenticate("wrong") and not network.authenticated)
        check("SAINT accepts configured access code", network.authenticate(str(settings.get("access_code"))).kind == "ok")
        linked = network.connect("SAINT-005")
        check("SAINT links to SAINT-005", network.unit is not None, linked.text.split("\n")[0])
        status = network.command("status")
        check("SAINT telemetry responds", "CALLSIGN" in status.text)
        network.disconnect()
    except Exception as exc:  # pragma: no cover - defensive
        check("SAINT simulation", False, str(exc))

    print(f"NOVA SELF-TEST — v{config.VERSION} [OFFLINE]")
    print("-" * 60)
    failures = 0
    for name, ok, detail in results:
        mark = "PASS" if ok else "FAIL"
        suffix = f"  ({detail})" if detail else ""
        print(f"[{mark}] {name}{suffix}")
        if not ok:
            failures += 1
    print("-" * 60)
    print(f"{len(results) - failures}/{len(results)} checks passed")
    return 0 if failures == 0 else 1


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.home:
        os.environ["NOVA_HOME"] = str(Path(args.home).expanduser())
    path_map = config.ensure_dirs()
    settings = config.Settings()
    if args.touch is not None:
        settings.set("touch_keyboard", args.touch)
    store = Store(path_map["db"])

    if args.report:
        report(store, settings, path_map)
        store.close()
        return 0
    if args.self_test:
        code = self_test(store, settings)
        store.close()
        return code

    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print("Nova needs an interactive terminal for its console interface.")
        print("Try:  python3 nova.py --report      (offline database report)")
        print("      python3 nova.py --self-test   (internal checks)")
        store.close()
        return 2

    store.log("SYSTEM", "Console boot")
    try:
        from nova.ui import run_console

        run_console(store, settings, path_map, boot=not args.no_boot)
    except KeyboardInterrupt:
        pass
    except Exception as exc:  # curses/terminfo failures should not be tracebacks
        store.log("ERROR", f"Console failed to start: {exc}")
        print(f"\nNova could not start its terminal interface: {exc}")
        print("Check that TERM is set (for example TERM=xterm-256color) and that the terminal supports cursor addressing.")
        print("You can still use: python3 nova.py --report  or  --self-test")
        return 3
    finally:
        store.close()
    print("\nNova console offline. Johnny 5 is alive.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
