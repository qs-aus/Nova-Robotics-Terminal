# NOVA ROBOTICS // SAINT CONTROL

A self-contained, offline Python console inspired by **Short Circuit (1986)** and
the Nova Robotics SAINT program. Everything runs locally in one terminal window:
a 65-record Nova database, five everyday programs, a word processor, a Python
code studio, and a simulated remote-access console for SAINT units — plus a
pop-up on-screen keyboard for touchscreens, tablets and 2-in-1 laptops.

> Unofficial fan project. Not affiliated with the film's rights holders.
> The SAINT uplink is a simulation; no robots, radios or networks are involved.

## Quick start

Requires **Python 3.10+** and a terminal. No packages to install, no internet
connection, no build step.

```bash
python3 nova.py
```

The first launch creates a data folder (default `~/.nova_robotics`) with a
SQLite database seeded with all 65 SAINT chassis records.

Useful flags:

| Command | What it does |
| --- | --- |
| `python3 nova.py` | Start the full console |
| `python3 nova.py --report` | Print a database report without curses (works over SSH, in CI, etc.) |
| `python3 nova.py --self-test` | Run 17 internal offline checks |
| `python3 nova.py --home ./usb` | Keep all data in a custom folder |
| `python3 nova.py --no-boot` | Skip the boot animation |
| `python3 nova.py --touch` / `--no-touch` | Set the on-screen keyboard default |

On Windows, run inside WSL (the interface uses the standard `curses` module).

## What is inside

### Nova database — 65 records
The local SQLite database contains **65 SAINT unit records** (`SAINT-001` …
`SAINT-065`) with model, status, location, battery, firmware, clearance and
notes (including `SAINT-005`, the SAINT-5 prototype). It also stores personnel,
projects, documents, notes, calendar events, alarms and session logs.

Browse it under **Nova Database**: five tabs (Units, Personnel, Projects, Logs,
Stats), search with `/`, open a record with Enter, and edit a unit's status,
location and notes with `E`.

### Five everyday programs
1. **Calendar** — month grid, agenda, add/delete events, go-to-date.
2. **Clock & Timers** — live clock, stopwatch with laps, countdown timer, alarms.
3. **Calculator** — safe scientific expressions (`sqrt`, `sin`, `fact`, `pi`, …)
   with history and arrow-key recall.
4. **Notes** — quick notes with an editor, search filter, rename and delete.
5. **Unit Converter** — length, mass, data, speed, time, energy, pressure and
   temperature, with live results and one-key swap.

### Word processor
A document library with a full-screen editor: save (`Ctrl-S`), find (`Ctrl-F`),
replace-all (`F6`), go to line (`Ctrl-G`), word/character statistics (`Ctrl-W`),
plain-text export (`F8`), rename and delete.

### Code Studio
A Python workspace with line numbers, auto-indent, file/template management,
syntax checking (`Ctrl-B`) and an **offline runner** (`F9`) that executes your
code in a separate child process (`python -B -E`, 15-second timeout) and shows
stdout/stderr, exit code and runtime. Three sample programs are created on first
use, and sibling modules in the workspace import normally.

### SAINT Remote Access (simulated)
Scan the 65 chassis, authenticate with an access code, link to a unit and send
directives: `status`, `scan`, `move <location>`, `diagnose`, `recharge`,
`patch <version>`, `broadcast <message>`, `shutdown`, `revive`, `dance`,
`selfdestruct YES` (fiction only), `trace`, `disconnect`, `help`.

Commands change the local database (location, battery, firmware, status) and are
logged. Staying connected raises a security trace; at 100% the uplink is kicked.
The demo access code is **`J5-1986`** (shown on the scan screen and changeable in
**System → Settings**).

### System
Settings (operator name, access code, touch keyboard, simulation seed), session
logs, the key-reference help screen and About.

## On-screen keyboard (touch devices)

Press **F2** anywhere to pop up the keyboard, or **tap the footer**. In dialogs,
tapping the text field opens it too. The overlay can be driven three ways:

- **Tap/click keys** — works in terminal apps that forward mouse events to the
  application (most touch-capable terminal emulators do; taps arrive as clicks).
- **Arrow keys + Enter** to select and press keys, with Shift for capitals.
- **Type on a hardware keyboard** while it is open.

Touch mode can be disabled in **System → Settings** or with `--no-touch`.

## Keys

| Key | Action |
| --- | --- |
| `F1` | Help |
| `F2` | Pop-up keyboard |
| `F10` | Back / shutdown from home |
| `Ctrl-Q` | Quit (with confirmation) |
| `↑/↓`, `PgUp/PgDn` | Navigate lists and long text |
| `Enter` | Open / confirm / submit |
| `Ctrl-S` | Save (word processor, code studio, notes) |
| `Ctrl-F`, `F6`, `Ctrl-G`, `Ctrl-W` | Find, replace, go to line, statistics |
| `F9`, `Ctrl-B` | Run program, check syntax (Code Studio) |
| `F8` | Export document (word processor) |
| `F4` | Disconnect SAINT uplink |

## Offline and privacy

- **No network code**: the SAINT uplink is a local simulation; the program never
  opens sockets or makes HTTP requests.
- **Local data only**: one SQLite file plus your documents and programs under the
  Nova home folder. Override with `NOVA_HOME` or `--home`.
- **Safe calculator**: expressions are evaluated with an AST whitelist, not
  `eval`.
- **Local code runner**: Code Studio runs *your own* Python files on *your*
  machine. It is a convenience runner with a timeout, not a security sandbox.
- **Offline build**: no dependencies beyond the Python standard library.

## Tests and verification

```bash
python3 nova.py --self-test
python3 nova.py --report
python3 -m unittest discover -s tests -v
```

The test suite covers the database seed, calculator sandbox, conversions,
document editing, the code runner and the SAINT simulation, plus end-to-end
terminal tests that boot the real console in a pseudo-terminal, drive menus,
type in a prompt, tap the on-screen keyboard with synthetic mouse events, run a
program, send SAINT directives and quit cleanly.

## Layout

```
nova.py                 launcher, report and self-test
nova/config.py          paths and JSON settings
nova/store.py           SQLite schema + 65-record seed
nova/calc.py            AST-sandboxed calculator
nova/convert.py         unit conversions
nova/docs.py            testable text-document model
nova/coderun.py         offline Python runner
nova/saint.py           simulated SAINT network
nova/draw.py            curses theme and safe painting
nova/keys.py            key translation
nova/keyboard.py        pop-up on-screen keyboard
nova/ui.py              app framework, menus, dialogs, boot splash
nova/editor.py          reusable full-screen editor
nova/apps/              home, database, everyday apps, word, code, SAINT, system
tests/                  unit tests + pty/VT100 UI smoke tests
```

## Known limits

- Minimum terminal size is **40 × 12**; below that Nova asks for a larger window.
  On very short screens the calendar month and some panels become compact.
- The word processor scrolls horizontally rather than soft-wrapping long lines.
- Alarms fire while the console is open (they are not OS-level scheduled jobs).
- The 15-second code timeout and simulated trace are intentional safety rails for
  a demo console.

"Johnny 5 is alive."
