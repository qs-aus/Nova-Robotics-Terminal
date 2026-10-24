"""Translate raw curses input into stable, testable key names."""

from __future__ import annotations

import curses

NAMES = {
    curses.KEY_UP: "UP",
    curses.KEY_DOWN: "DOWN",
    curses.KEY_LEFT: "LEFT",
    curses.KEY_RIGHT: "RIGHT",
    curses.KEY_HOME: "HOME",
    curses.KEY_END: "END",
    curses.KEY_NPAGE: "PGDN",
    curses.KEY_PPAGE: "PGUP",
    curses.KEY_DC: "DELETE",
    curses.KEY_IC: "INSERT",
    curses.KEY_BACKSPACE: "BACKSPACE",
    curses.KEY_ENTER: "ENTER",
    curses.KEY_MOUSE: "MOUSE",
    curses.KEY_RESIZE: "RESIZE",
    curses.KEY_BTAB: "BTAB",
}
for _number in range(1, 13):
    NAMES[curses.KEY_F0 + _number] = f"F{_number}"


def translate(ch) -> str:
    """Map a ``get_wch`` result to a printable name or the character itself."""
    if ch is None:
        return "IDLE"
    if isinstance(ch, int):
        return NAMES.get(ch, f"KEY{ch}")
    if ch in ("\n", "\r"):
        return "ENTER"
    if ch in ("\x7f", "\x08"):
        return "BACKSPACE"
    if ch == "\t":
        return "TAB"
    if ch == "\x1b":
        return "ESC"
    if len(ch) == 1 and ord(ch) < 32:
        return "CTRL-" + chr(ord(ch) + 64)
    return ch


def is_printable(key: str) -> bool:
    if len(key) != 1:
        return False
    return ord(key) >= 32 and key != "\x7f"
