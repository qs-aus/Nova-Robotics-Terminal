"""The Nova console framework: screens, menus, dialogs and the main loop."""

from __future__ import annotations

import curses
import sys
import textwrap
import time
from dataclasses import dataclass

from . import config
from .draw import Painter, Theme
from .keyboard import keyboard_popup
from .keys import is_printable, translate

HELP_TEXT = """NOVA CONSOLE — KEY REFERENCE

Everywhere
  F1            This help screen
  F2            Pop up the on-screen keyboard (touch/keyboardless devices)
  Tap footer    Same as F2 on touchscreens and mice
  F10           Back / close the current screen
  Ctrl-Q        Quit the console
  Arrow keys    Move through lists and text
  PgUp / PgDn   Page through long content
  Enter         Open, confirm or submit

On-screen keyboard
  Tap a key     Type that character (mouse reporting must be on)
  Arrows        Move between keys; Enter presses the selected key
  Enter         Accept the text (or newline in multiline mode)
  Esc           Close without changes
  Shift         Toggle upper-case letters

Word Processor and Code Studio
  Ctrl-S        Save
  Ctrl-F        Find next
  F6            Find and replace
  Ctrl-G        Go to line
  Ctrl-W        Word / character statistics
  Ctrl-K        Insert text using the on-screen keyboard
  Tab           Insert four spaces
  F8            Export (word processor)
  F9            Run program (Code Studio)
  Ctrl-B        Check syntax (Code Studio)

SAINT Remote Access
  Type          Enter a directive, Enter sends it
  Up / Down     Recall previous directives
  F4            Disconnect from the chassis
  Ctrl-L        Clear the session pane

Offline promise: Nova never opens a network connection. The SAINT uplink is a
local simulation, and every document, note and unit record lives in one SQLite
file inside your Nova home folder.
"""


class QuitSignal(Exception):
    """Raised to leave the console cleanly from any depth."""


@dataclass
class Context:
    store: object
    settings: config.Settings
    paths: dict
    theme: Theme | None = None
    stdscr: object | None = None

    @property
    def touch(self) -> bool:
        return bool(self.settings.get("touch_keyboard"))

    @property
    def operator(self) -> str:
        return str(self.settings.get("operator") or "FIELD OPERATOR")

    def log(self, source: str, message: str) -> None:
        try:
            self.store.log(source, message)
        except Exception:
            pass


class App:
    """Base class for a full-screen console screen."""

    title = "NOVA"
    hint = "F10 Back"
    frame_ms = 400
    multiline_keyboard = False

    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx
        self.status = ""
        self.status_kind = "info"
        self.cursor: tuple[int, int] | None = None
        self.finished = False

    # ------------------------------------------------------------- lifecycle
    def on_enter(self) -> None:
        pass

    def on_exit(self) -> None:
        pass

    def tick(self) -> None:
        pass

    def render(self, p: Painter) -> None:
        raise NotImplementedError

    def handle(self, key: str) -> bool:
        return True

    def handle_mouse(self, y: int, x: int, bstate: int) -> bool:
        return False

    def on_keyboard(self, text: str) -> None:
        self.say("This screen does not accept typed text", "warn")

    def can_exit(self) -> bool:
        return True

    def say(self, message: str, kind: str = "info") -> None:
        self.status = message
        self.status_kind = kind


# --------------------------------------------------------------------- input
def _safe_get(stdscr):
    try:
        return stdscr.get_wch()
    except curses.error:
        return None


def _status_attr(ctx: Context, kind: str) -> int:
    theme = ctx.theme
    if theme is None:
        return 0
    return {"error": theme.error, "warn": theme.warn, "ok": theme.ok}.get(kind, theme.dim)


def _draw_chrome(p: Painter, app: App, ctx: Context) -> None:
    p.header(app.title, f"{config.SHORT_NAME} {config.VERSION}")
    if p.h < 6:
        return
    status_row = p.h - 2
    if app.status:
        p.put(status_row, 1, app.status, _status_attr(ctx, app.status_kind), max(0, p.w - 2))
    else:
        p.put(status_row, 1, f"OPERATOR: {ctx.operator}", ctx.theme.dim, max(0, p.w - 2))
    hint = app.hint
    p.put(p.h - 1, 1, hint, ctx.theme.dim, max(0, p.w - 2))
    if ctx.touch:
        badge = "F2 Keyboard"
        if len(hint) + len(badge) + 4 < p.w:
            p.put(p.h - 1, p.w - len(badge) - 2, badge, ctx.theme.accent, len(badge))


def run_app(stdscr, ctx: Context, app: App) -> None:
    """Run one screen until it closes or the program quits."""
    if ctx.theme is None:
        ctx.theme = Theme(stdscr)
    if ctx.stdscr is None:
        ctx.stdscr = stdscr
    app.ctx = ctx
    try:
        app.on_enter()
    except Exception as exc:
        app.say(f"Startup error: {exc}", "error")

    while not app.finished:
        p = Painter(stdscr, ctx.theme)
        stdscr.erase()
        app.cursor = None
        try:
            if p.too_small():
                p.size_warning()
            else:
                app.render(p)
        except Exception as exc:
            p.put(2, 1, f"Render error: {type(exc).__name__}: {exc}", ctx.theme.error, max(0, p.w - 2))
            ctx.log("ERROR", f"render {type(app).__name__}: {exc}")
        if not p.too_small():
            _draw_chrome(p, app, ctx)
        try:
            if app.cursor:
                curses.curs_set(1)
                stdscr.move(min(app.cursor[0], p.h - 1), min(app.cursor[1], max(0, p.w - 1)))
            else:
                curses.curs_set(0)
        except curses.error:
            pass
        stdscr.refresh()
        stdscr.timeout(app.frame_ms)

        raw = _safe_get(stdscr)
        if raw is None:
            key = "IDLE"
        else:
            key = translate(raw)

        if key == "RESIZE":
            continue
        if key == "IDLE":
            try:
                app.tick()
            except Exception as exc:
                app.say(f"Tick error: {exc}", "error")
            continue
        if key == "F1":
            show_text(stdscr, ctx, "HELP — NOVA CONSOLE", HELP_TEXT)
            continue
        if key == "F2":
            if not ctx.touch:
                app.say("On-screen keyboard is disabled — enable it in System > Settings", "warn")
            else:
                text = keyboard_popup(
                    stdscr,
                    ctx.theme,
                    title="ON-SCREEN KEYBOARD",
                    multiline=app.multiline_keyboard,
                )
                if text:
                    app.on_keyboard(text)
            continue
        if key == "CTRL-Q":
            if app.can_exit() and confirm(stdscr, ctx, "QUIT NOVA", "Shut down the field console?"):
                raise QuitSignal()
            continue
        if key == "F10":
            if app.can_exit():
                break
            app.say("Resolve unsaved changes before leaving", "warn")
            continue
        if key == "MOUSE":
            try:
                _, mx, my, _, bstate = curses.getmouse()
            except curses.error:
                continue
            if not (bstate & (curses.BUTTON1_CLICKED | curses.BUTTON1_PRESSED | curses.BUTTON1_RELEASED)):
                continue
            if my == p.h - 1 and ctx.touch:
                text = keyboard_popup(
                    stdscr,
                    ctx.theme,
                    title="ON-SCREEN KEYBOARD",
                    multiline=app.multiline_keyboard,
                )
                if text:
                    app.on_keyboard(text)
                continue
            if app.handle_mouse(my, mx, bstate):
                continue
            continue

        try:
            keep = app.handle(key)
        except QuitSignal:
            raise
        except Exception as exc:
            app.say(f"{type(exc).__name__}: {exc}", "error")
            ctx.log("ERROR", f"{type(app).__name__} key {key!r}: {exc}")
            keep = True
        if not keep:
            break

    try:
        app.on_exit()
    except Exception:
        pass


# ------------------------------------------------------------------- dialogs
def prompt(
    stdscr,
    ctx: Context,
    title: str,
    label: str = "",
    value: str = "",
    secret: bool = False,
    hint: str = "",
    allow_empty: bool = True,
) -> str | None:
    """Modal single-line text prompt. Returns text or None when cancelled."""
    theme = ctx.theme or Theme(stdscr)
    stdscr.timeout(-1)
    buffer = list(value)
    pos = len(buffer)

    while True:
        p = Painter(stdscr, theme)
        stdscr.erase()
        if p.too_small():
            p.size_warning()
            stdscr.refresh()
            return None
        width = min(max(42, len(label) + 12), max(30, p.w - 2))
        height = 9
        y = max(1, (p.h - height) // 2)
        x = max(0, (p.w - width) // 2)
        p.box(y, x, height, width, title, theme.accent, theme.accent)
        p.put(y + 2, x + 2, label, theme.title, width - 4)
        field_width = max(4, width - 4)
        raw = ("*" * len(buffer)) if secret else "".join(buffer)
        start = max(0, pos - (field_width - 1))
        visible = raw[start : start + field_width]
        p.put(y + 4, x + 2, " " * field_width, theme.dim, field_width)
        p.put(y + 4, x + 2, visible, 0, field_width)
        p.hline(y + 5, x + 2, field_width, theme.dim)
        if hint:
            p.put(y + 6, x + 2, hint, theme.warn, width - 4)
        tail = "Enter accept · Esc cancel · F2 keyboard"
        if len(tail) < width - 4:
            p.put(y + height - 2, x + 2, tail, theme.dim, width - 4)
        cursor = (y + 4, x + 2 + min(pos - start, field_width - 1))
        try:
            curses.curs_set(1)
            stdscr.move(*cursor)
        except curses.error:
            pass
        stdscr.refresh()

        key = translate(_safe_get(stdscr))
        if key == "ENTER":
            text = "".join(buffer)
            if not allow_empty and not text.strip():
                continue
            return text
        if key in ("ESC", "F10"):
            return None
        if key in ("F2", "CTRL-K"):
            edited = keyboard_popup(
                stdscr,
                theme,
                title="ON-SCREEN KEYBOARD",
                initial="".join(buffer),
                multiline=False,
                mask=secret,
            )
            if edited is not None:
                buffer = list(edited)
                pos = len(buffer)
            continue
        if key == "MOUSE":
            try:
                _, mx, my, _, bstate = curses.getmouse()
            except curses.error:
                continue
            if bstate & (curses.BUTTON1_CLICKED | curses.BUTTON1_PRESSED) and x <= mx < x + width and y <= my < y + height:
                edited = keyboard_popup(
                    stdscr,
                    theme,
                    title="ON-SCREEN KEYBOARD",
                    initial="".join(buffer),
                    multiline=False,
                    mask=secret,
                )
                if edited is not None:
                    buffer = list(edited)
                    pos = len(buffer)
            continue
        if key == "BACKSPACE":
            if pos > 0:
                del buffer[pos - 1]
                pos -= 1
            continue
        if key == "DELETE":
            if pos < len(buffer):
                del buffer[pos]
            continue
        if key == "LEFT":
            pos = max(0, pos - 1)
            continue
        if key == "RIGHT":
            pos = min(len(buffer), pos + 1)
            continue
        if key == "HOME":
            pos = 0
            continue
        if key == "END":
            pos = len(buffer)
            continue
        if key == "CTRL-U":
            buffer.clear()
            pos = 0
            continue
        if is_printable(key):
            buffer.insert(pos, key)
            pos += 1
            continue


def confirm(stdscr, ctx: Context, title: str, question: str) -> bool:
    theme = ctx.theme or Theme(stdscr)
    stdscr.timeout(-1)
    choice = False
    width = min(max(44, len(question) + 8), max(30, (stdscr.getmaxyx()[1] if stdscr else 80) - 2))
    while True:
        p = Painter(stdscr, theme)
        stdscr.erase()
        if p.too_small():
            p.size_warning()
            stdscr.refresh()
            return False
        width = min(max(44, len(question) + 8), max(30, p.w - 2))
        height = 7
        y = max(1, (p.h - height) // 2)
        x = max(0, (p.w - width) // 2)
        p.box(y, x, height, width, title, theme.warn, theme.warn)
        p.put(y + 2, x + 2, question, theme.title, width - 4)
        yes = "[ YES ]" if choice else "  YES  "
        no = "[ NO ]" if not choice else "  NO  "
        p.put(y + 4, x + 2, yes, theme.sel if choice else theme.dim)
        p.put(y + 4, x + 2 + len(yes) + 3, no, theme.sel if not choice else theme.dim)
        p.put(y + height - 2, x + 2, "←/→ choose · Enter confirm · Y/N shortcut", theme.dim, width - 4)
        stdscr.refresh()
        key = translate(_safe_get(stdscr))
        if key in ("LEFT", "RIGHT", "TAB"):
            choice = not choice
        elif key == "ENTER":
            return choice
        elif key in ("y", "Y"):
            return True
        elif key in ("n", "N", "ESC", "F10"):
            return False


def choose(stdscr, ctx: Context, title: str, options: list[str], start: int = 0) -> int | None:
    theme = ctx.theme or Theme(stdscr)
    if not options:
        return None
    stdscr.timeout(-1)
    state = ListState(options, start)
    while True:
        p = Painter(stdscr, theme)
        stdscr.erase()
        if p.too_small():
            p.size_warning()
            stdscr.refresh()
            return None
        width = min(max(46, max((len(o) for o in options), default=10) + 14), p.w - 2)
        height = min(len(options) + 6, p.h - 4)
        y = max(1, (p.h - height) // 2)
        x = max(0, (p.w - width) // 2)
        p.box(y, x, height, width, title, theme.accent, theme.accent)
        draw_list(p, state, y + 2, height - 5, width - 2, lambda index, label: (label, ""), x=x + 1)
        p.put(y + height - 2, x + 2, "Enter select · Esc cancel", theme.dim, width - 4)
        stdscr.refresh()
        key = translate(_safe_get(stdscr))
        if key == "ENTER":
            return state.idx
        if key in ("ESC", "F10"):
            return None
        if key == "UP":
            state.move(-1)
        elif key == "DOWN":
            state.move(1)
        elif key == "PGUP":
            state.move(-6)
        elif key == "PGDN":
            state.move(6)
        elif key == "HOME":
            state.idx = 0
        elif key == "END":
            state.idx = len(options) - 1
        elif is_printable(key) and key.isdigit():
            index = int(key) - 1
            if 0 <= index < len(options):
                return index


def show_text(stdscr, ctx: Context, title: str, body: str, hint: str | None = None) -> None:
    viewer = TextViewApp(ctx, title, body, hint)
    run_app(stdscr, ctx, viewer)


# --------------------------------------------------------------------- lists
class ListState:
    """Scrollable selection state shared by list screens."""

    def __init__(self, items=None, index: int = 0) -> None:
        self.items = list(items or [])
        self.idx = min(max(0, index), max(0, len(self.items) - 1))
        self.top = 0

    def set_items(self, items) -> None:
        self.items = list(items)
        self.idx = min(self.idx, max(0, len(self.items) - 1))
        self.top = 0

    @property
    def current(self):
        if not self.items:
            return None
        return self.items[self.idx]

    def clamp(self) -> None:
        self.idx = max(0, min(self.idx, max(0, len(self.items) - 1)))

    def move(self, delta: int) -> None:
        if not self.items:
            return
        self.idx = max(0, min(self.idx + delta, len(self.items) - 1))

    def ensure(self, height: int) -> None:
        if height <= 0:
            self.top = 0
            return
        self.clamp()
        if self.idx < self.top:
            self.top = self.idx
        elif self.idx >= self.top + height:
            self.top = self.idx - height + 1
        self.top = max(0, min(self.top, max(0, len(self.items) - height)))


def draw_list(
    p: Painter,
    state: ListState,
    top: int,
    height: int,
    width: int,
    renderer,
    x: int = 1,
    empty: str = "Nothing here yet",
) -> None:
    """Draw a selection list. ``renderer(index, item) -> (label, detail)``."""
    theme = p.theme
    if not state.items:
        p.put(top, x + 1, empty, theme.dim, width - 2)
        return
    state.ensure(height)
    for offset in range(min(height, len(state.items) - state.top)):
        index = state.top + offset
        item = state.items[index]
        label, detail = renderer(index, item)
        row = top + offset
        selected = index == state.idx
        label = str(label)[: max(0, width - 2)]
        detail = str(detail or "")
        detail_x_min = x + 1 + len(label) + 2
        detail_room = x + width - 1 - detail_x_min
        if detail_room < 3:
            detail = ""
        else:
            detail = detail[:detail_room]
        if selected:
            p.fill(row, x, 1, width, theme.sel)
            p.put(row, x + 1, label, theme.sel, width - 2)
            if detail:
                room = width - 2 - len(label) - 1
                if room > 3:
                    p.put(row, x + width - 1 - len(detail), detail, theme.sel, len(detail))
        else:
            p.put(row, x + 1, label, 0, width - 2)
            if detail:
                room = width - 2 - len(label) - 1
                if room > 3:
                    p.put(row, x + width - 1 - len(detail), detail, theme.dim, len(detail))


# --------------------------------------------------------------------- apps
class TextViewApp(App):
    """Scrollable read-only text viewer used for help, run output and details."""

    def __init__(self, ctx: Context, title: str, body: str, hint: str | None = None) -> None:
        super().__init__(ctx)
        self.title = title
        self.body = body or ""
        self.hint = hint or "↑/↓ scroll   PgUp/PgDn page   F10 Back"
        self.scroll = 0
        self.total = 0

    def render(self, p: Painter) -> None:
        lines: list[str] = []
        width = max(12, p.w - 4)
        for raw in self.body.split("\n"):
            if not raw:
                lines.append("")
            elif len(raw) <= width:
                lines.append(raw)
            else:
                lines.extend(textwrap.wrap(raw, width=width, replace_whitespace=False, drop_whitespace=False) or [""])
        self.total = len(lines)
        self.scroll = max(0, min(self.scroll, max(0, self.total - p.content_h)))
        top = p.content_top
        for offset in range(min(p.content_h, self.total - self.scroll)):
            line = lines[self.scroll + offset]
            attr = p.theme.title if line.startswith("---") else 0
            if line.startswith("  ") and not attr:
                attr = 0
            p.put(top + offset, 2, line, attr, p.w - 3)
        if self.total > p.content_h:
            pct = int(100 * (self.scroll + p.content_h) / max(1, self.total))
            p.put(p.h - 2, max(0, p.w - 8), f"{min(100, pct):>3}%", p.theme.dim, 5)

    def handle(self, key: str) -> bool:
        step = max(1, (self.ctx.stdscr.getmaxyx()[0] - 4) if self.ctx.stdscr else 20)
        if key == "UP":
            self.scroll -= 1
        elif key == "DOWN":
            self.scroll += 1
        elif key == "PGUP":
            self.scroll -= step
        elif key == "PGDN":
            self.scroll += step
        elif key == "HOME":
            self.scroll = 0
        elif key == "END":
            self.scroll = max(0, self.total)
        elif key == "ESC":
            return False
        self.scroll = max(0, self.scroll)
        return True


class MenuItem:
    def __init__(self, label: str, detail: str = "", factory=None) -> None:
        self.label = label
        self.detail = detail
        self.factory = factory


class MenuApp(App):
    """A list of destinations with descriptions."""

    def __init__(self, ctx: Context, title: str, items: list[MenuItem], subtitle: str = "") -> None:
        super().__init__(ctx)
        self.title = title
        self.subtitle = subtitle
        self.state = ListState(items)
        self.hint = "↑/↓ move   Enter open   F10 Back"

    def render(self, p: Painter) -> None:
        p.box(p.content_top, 0, p.content_h, p.w, f" {self.title} ", p.theme.dim)
        top = p.content_top + 1
        if self.subtitle and p.content_h >= 14:
            p.put(top, 2, self.subtitle, p.theme.dim, p.w - 3)
            top += 2
        available = max(1, p.content_bottom - top + 1)
        current = self.state.current
        show_detail = bool(current and current.detail and available > 4)
        if show_detail:
            available -= 2
        draw_list(
            p,
            self.state,
            top,
            available,
            p.w - 2,
            lambda index, item: (f"{index + 1:>2}. {item.label}", item.detail),
            x=1,
        )
        if show_detail:
            p.put(p.content_bottom, 2, current.detail, p.theme.dim, max(0, p.w - 3))

    def handle(self, key: str) -> bool:
        if key == "UP":
            self.state.move(-1)
        elif key == "DOWN":
            self.state.move(1)
        elif key == "PGUP":
            self.state.move(-8)
        elif key == "PGDN":
            self.state.move(8)
        elif key == "HOME":
            self.state.idx = 0
        elif key == "END":
            self.state.idx = len(self.state.items) - 1
        elif key == "ENTER":
            item = self.state.current
            if item and item.factory:
                app = item.factory(self.ctx)
                if app is not None:
                    run_app(self.ctx.stdscr, self.ctx, app)
        elif is_printable(key) and key.isdigit():
            index = 9 if key == "0" else int(key) - 1
            if 0 <= index < len(self.state.items):
                self.state.idx = index
                item = self.state.items[index]
                if item.factory:
                    app = item.factory(self.ctx)
                    if app is not None:
                        run_app(self.ctx.stdscr, self.ctx, app)
        return True


class BootSplash(App):
    """Short animated boot sequence. Any key skips it."""

    title = "NOVA ROBOTICS // BOOT"
    hint = "Press any key to skip"
    frame_ms = 90

    LINES = [
        ("NOVA ROBOTICS FIELD CONSOLE", "ok"),
        (f"VERSION {config.VERSION} · OFFLINE BUILD", "dim"),
        ("CORE SYSTEMS ............ ONLINE", "dim"),
        (f"NOVA DATABASE ........... {config.RECORD_COUNT} SAINT RECORDS", "dim"),
        ("TELEMETRY UPLINK ........ LOCAL SIMULATION", "dim"),
        ("NETWORK ACCESS .......... DISABLED (OFFLINE)", "warn"),
    ]

    def __init__(self, ctx: Context, duration: float = 1.6) -> None:
        super().__init__(ctx)
        self.started = time.monotonic()
        self.duration = duration

    def tick(self) -> None:
        if time.monotonic() - self.started > self.duration:
            self.finished = True

    def handle(self, key: str) -> bool:
        self.finished = True
        return True

    def render(self, p: Painter) -> None:
        elapsed = time.monotonic() - self.started
        p.put(2, 2, "SAINT CONTROL", p.theme.accent, p.w - 3)
        for index, (line, kind) in enumerate(self.LINES):
            if elapsed < 0.12 * index:
                break
            attr = {
                "ok": p.theme.ok,
                "dim": p.theme.dim,
                "warn": p.theme.warn,
            }.get(kind, 0)
            p.put(5 + index, 2, line, attr, p.w - 3)
        filled = min(34, int(34 * elapsed / self.duration))
        p.put(5 + len(self.LINES) + 1, 2, "[" + "=" * filled + "." * (34 - filled) + "]", p.theme.accent)
        p.put(p.h - 3, 2, "JOHNNY 5 IS ALIVE", p.theme.dim, p.w - 3)


def _disable_flow_control() -> None:
    """Make sure Ctrl-S saves instead of freezing terminal output (XOFF)."""
    try:
        import termios

        fd = sys.stdin.fileno()
        attrs = termios.tcgetattr(fd)
        attrs[0] &= ~(termios.IXON | termios.IXOFF | termios.IXANY)
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
    except Exception:
        pass


def run_console(store, settings: config.Settings, path_map: dict, boot: bool = True) -> int:
    """Start the curses console and return an exit code."""
    ctx = Context(store=store, settings=settings, paths=path_map)

    def wrapped(stdscr):
        _disable_flow_control()
        stdscr.keypad(True)
        try:
            curses.mousemask(curses.ALL_MOUSE_EVENTS | curses.REPORT_MOUSE_POSITION)
            curses.mouseinterval(0)
        except curses.error:
            pass
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        ctx.theme = Theme(stdscr)
        ctx.stdscr = stdscr
        from .apps import HomeApp

        if boot:
            run_app(stdscr, ctx, BootSplash(ctx))
        run_app(stdscr, ctx, HomeApp(ctx))

    try:
        curses.wrapper(wrapped)
    except QuitSignal:
        pass
    except KeyboardInterrupt:
        pass
    finally:
        store.log("SYSTEM", "Console session ended")
    return 0
