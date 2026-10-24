"""Pop-up on-screen keyboard for touchscreens and mouse-driven terminals.

The overlay is fully usable three ways:

* tap/click keys (requires a terminal that forwards mouse events, which is what
  touch keyboards on tablets and 2-in-1 laptops send),
* arrow keys + Enter,
* or just type on a hardware keyboard while it is open.
"""

from __future__ import annotations

import curses

from .draw import Painter, Theme
from .keys import is_printable, translate

CHAR_ROWS = [
    "1234567890-=",
    "qwertyuiop[]\\",
    "asdfghjkl;'",
    "zxcvbnm,./",
    "!@#$%^&*()_+",
    '{}|:"<>?~`',
]

COMPACT = {
    "SHIFT": "SHFT",
    "SPACE": "SPC",
    "BKSP": "BS",
    "CLEAR": "CLR",
    "CANCEL": "ESC",
    "ENTER": "ENT",
    "NEWLINE": "NL",
}


def _control_labels(multiline: bool, compact: bool) -> list[tuple[str, tuple]]:
    labels = [("SHIFT", "SHIFT"), ("SPACE", "SPACE"), ("BKSP", "BKSP"), ("CLEAR", "CLEAR")]
    if multiline:
        labels.append(("NEWLINE", "NEWLINE"))
    labels.append(("CANCEL", "CANCEL"))
    labels.append(("ENTER", "ENTER"))
    if compact:
        labels = [(COMPACT.get(label, label), token) for label, token in labels]
    return [(label, ("special", token)) for label, token in labels]


def _row_count(height: int) -> int:
    if height >= 22:
        return 6
    if height >= 18:
        return 5
    if height >= 15:
        return 4
    return 3


class _Layout:
    """Computed geometry for one keyboard frame."""

    def __init__(self, width: int, height: int, multiline: bool) -> None:
        self.width = width
        self.height = height
        self.multiline = multiline
        self.too_small = width < 34 or height < 10
        if self.too_small:
            return

        self.cell = max(2, min(4, (width - 6) // 13))
        row_total = min(6, _row_count(height))
        self.grid_rows = [
            [(ch, ("char", ch)) for ch in CHAR_ROWS[index]]
            for index in range(row_total)
        ]
        self.rows = len(self.grid_rows)
        self.box_w = min(width - 2, max(36, 13 * self.cell + 6))
        self.x0 = max(0, (width - self.box_w) // 2)
        self.inner_w = self.box_w - 2
        self.grid_w = 13 * self.cell
        self.grid_x = self.x0 + 1 + max(0, (self.inner_w - self.grid_w) // 2)
        self.h = self.rows + 6
        self.y0 = max(0, height - self.h - 1)

        compact = self.inner_w < 46
        controls = _control_labels(multiline, compact)
        widths = [len(label) + 2 for label, _ in controls]
        gap = 1 if sum(widths) + gap_len(len(widths)) <= self.inner_w else 0
        total = sum(widths) + gap * (len(widths) - 1)
        if total > self.inner_w:
            compact = True
            controls = _control_labels(multiline, True)
            widths = [len(label) + 2 for label, _ in controls]
            gap = 0
            total = sum(widths)
        self.controls = controls
        self.control_widths = widths
        self.control_gap = gap
        self.control_x = self.x0 + 1 + max(0, (self.inner_w - total) // 2)
        self.control_y = self.y0 + 2 + self.rows

    # ------------------------------------------------------------- geometry
    def grid_rect(self, row: int, col: int) -> tuple[int, int, int]:
        return (
            self.y0 + 2 + row,
            self.grid_x + col * self.cell,
            self.cell,
        )

    def control_rects(self) -> list[tuple[int, int, int, tuple]]:
        if self.too_small:
            return []
        rects = []
        x = self.control_x
        for width, (_, token) in zip(self.control_widths, self.controls):
            rects.append((self.control_y, x, width, token))
            x += width + self.control_gap
        return rects


def gap_len(count: int) -> int:
    return max(0, count - 1)


def keyboard_popup(
    stdscr,
    theme: Theme,
    title: str = "ON-SCREEN KEYBOARD",
    initial: str = "",
    multiline: bool = False,
    mask: bool = False,
) -> str | None:
    """Show the pop-up keyboard. Returns the edited text, or None on cancel."""
    try:
        stdscr.timeout(-1)
    except curses.error:
        pass
    buffer = list(initial)
    shift = False
    focus = "grid"
    row = col = 0
    control_index = 0
    navigating = False

    while True:
        p = Painter(stdscr, theme)
        layout = _Layout(p.w, p.h, multiline)
        stdscr.erase()
        if layout.too_small:
            p.center(max(0, p.h // 2 - 1), "On-screen keyboard needs a bigger terminal", theme.warn)
            p.center(max(0, p.h // 2), "(at least 34 x 10 cells)", theme.dim)
            p.center(max(0, p.h // 2 + 2), "Esc closes", theme.dim)
            stdscr.refresh()
            key = translate(_safe_get(stdscr))
            if key in ("ESC", "F2", "ENTER"):
                return None
            continue

        p.box(layout.y0, layout.x0, layout.h, layout.box_w, title, theme.accent, theme.accent)
        text = "".join(buffer)
        visible = text.split("\n")[-1]
        if mask:
            visible = "*" * len(visible)
        room = layout.inner_w - 6
        if len(visible) > room:
            visible = "…" + visible[-(room - 1) :]
        prefix = f"> {visible}"
        p.put(layout.y0 + 1, layout.x0 + 2, prefix, theme.title, layout.inner_w - 2)
        cursor_x = layout.x0 + 2 + len(prefix)
        cursor_y = layout.y0 + 1
        indicator = "SHIFT" if shift else ""
        if multiline:
            indicator = (indicator + "  MULTILINE").strip()
        if mask:
            indicator = (indicator + "  MASKED").strip()
        p.put(layout.y0 + 1, layout.x0 + layout.inner_w - len(indicator), indicator, theme.warn, len(indicator))

        for r, cells in enumerate(layout.grid_rows):
            for c, (label, token) in enumerate(cells):
                y, x, width = layout.grid_rect(r, c)
                display = label.upper() if (shift and label.isalpha()) else label
                selected = focus == "grid" and r == row and c == col
                attr = theme.sel if selected else theme.dim
                p.put(y, x, display.center(width), attr, width)

        for index, (y, x, width, token) in enumerate(layout.control_rects()):
            label = layout.controls[index][0]
            selected = focus == "controls" and index == control_index
            special = token[1]
            if special in ("ENTER", "CANCEL"):
                attr = theme.sel if selected else (theme.ok if special == "ENTER" else theme.warn)
            else:
                attr = theme.sel if selected else theme.dim
            p.put(y, x, label.center(width), attr, width)

        hint = "Tap a key  ·  arrows + Enter  ·  Esc closes"
        p.put(layout.y0 + layout.h - 2, layout.x0 + 2, hint, theme.dim, layout.inner_w - 2)
        try:
            curses.curs_set(1)
            stdscr.move(min(cursor_y, p.h - 1), min(cursor_x, max(0, p.w - 1)))
        except curses.error:
            pass
        stdscr.refresh()

        key = translate(_safe_get(stdscr))

        if key == "MOUSE":
            hit = _mouse_hit(layout)
            if hit is not None:
                token = hit
                buffer, shift, outcome = _apply(token, buffer, shift)
                if outcome == "accept":
                    return "".join(buffer)
                if outcome == "cancel":
                    return None
            continue

        if key in ("ESC", "F2"):
            return None
        if key == "CTRL-Q":
            return None
        if key == "CTRL-U":
            buffer.clear()
            continue
        if key == "BACKSPACE":
            if buffer:
                buffer.pop()
            continue
        if key == "ENTER":
            if focus == "controls":
                token = layout.controls[control_index][1]
                buffer, shift, outcome = _apply(token, buffer, shift)
                if outcome == "accept":
                    return "".join(buffer)
                if outcome == "cancel":
                    return None
                continue
            if navigating:
                token = layout.grid_rows[row][col][1]
                buffer, shift, outcome = _apply(token, buffer, shift)
            else:
                return "".join(buffer)
            continue
        if key == "TAB":
            navigating = True
            focus = "controls" if focus == "grid" else "grid"
            continue
        if key in ("UP", "DOWN"):
            navigating = True
            if focus == "controls":
                if key == "UP":
                    focus = "grid"
                    row = layout.rows - 1
                continue
            if key == "UP":
                if row == 0:
                    focus = "controls"
                else:
                    row -= 1
                    col = min(col, len(layout.grid_rows[row]) - 1)
            else:
                if row >= layout.rows - 1:
                    focus = "controls"
                else:
                    row += 1
                    col = min(col, len(layout.grid_rows[row]) - 1)
            continue
        if key in ("LEFT", "RIGHT"):
            navigating = True
            if focus == "controls":
                step = -1 if key == "LEFT" else 1
                control_index = (control_index + step) % len(layout.controls)
            else:
                step = -1 if key == "LEFT" else 1
                col = (col + step) % len(layout.grid_rows[row])
            continue
        if key == "HOME":
            navigating = True
            if focus == "grid":
                col = 0
            else:
                control_index = 0
            continue
        if key == "END":
            navigating = True
            if focus == "grid":
                col = len(layout.grid_rows[row]) - 1
            else:
                control_index = len(layout.controls) - 1
            continue
        if is_printable(key):
            navigating = False
            typed = key.upper() if (shift and key.isalpha()) else key
            buffer.append(typed)
            continue


def _apply(token: tuple, buffer: list[str], shift: bool):
    kind, value = token
    if kind == "char":
        char = value.upper() if shift and value.isalpha() else value
        buffer.append(char)
        return buffer, shift, "insert"
    if value == "SHIFT":
        return buffer, not shift, "shift"
    if value == "SPACE":
        buffer.append(" ")
        return buffer, shift, "insert"
    if value == "BKSP":
        if buffer:
            buffer.pop()
        return buffer, shift, "insert"
    if value == "CLEAR":
        buffer.clear()
        return buffer, shift, "insert"
    if value == "NEWLINE":
        buffer.append("\n")
        return buffer, shift, "insert"
    if value == "ENTER":
        return buffer, shift, "accept"
    if value == "CANCEL":
        return buffer, shift, "cancel"
    return buffer, shift, "insert"


def _mouse_hit(layout: _Layout):
    try:
        _, mx, my, _, bstate = curses.getmouse()
    except curses.error:
        return None
    if not (bstate & (curses.BUTTON1_CLICKED | curses.BUTTON1_PRESSED)):
        return None
    for r, cells in enumerate(layout.grid_rows):
        for c, (_, token) in enumerate(cells):
            y, x, width = layout.grid_rect(r, c)
            if my == y and x <= mx < x + width:
                return token
    for y, x, width, token in layout.control_rects():
        if my == y and x <= mx < x + width:
            return token
    return None


def _safe_get(stdscr):
    try:
        return stdscr.get_wch()
    except curses.error:
        return None
