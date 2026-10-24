"""Low-level terminal drawing helpers shared by every Nova screen."""

from __future__ import annotations

import curses
import sys
import time

MIN_WIDTH = 40
MIN_HEIGHT = 12

UNICODE_GLYPHS = {"h": "─", "v": "│", "tl": "┌", "tr": "┐", "bl": "└", "br": "┘", "dot": "·", "arrow": "▸"}
ASCII_GLYPHS = {"h": "-", "v": "|", "tl": "+", "tr": "+", "bl": "+", "br": "+", "dot": ".", "arrow": ">"}


def _unicode_ok() -> bool:
    encoding = (getattr(sys.stdout, "encoding", "") or "").lower()
    if "utf" not in encoding:
        return False
    try:
        "─│┌▸".encode(encoding)
    except (UnicodeEncodeError, LookupError):
        return False
    return True


UNICODE = _unicode_ok()
GLYPHS = dict(UNICODE_GLYPHS if UNICODE else ASCII_GLYPHS)


def ascii_mode() -> None:
    """Called if the terminal rejects box-drawing characters mid-session."""
    GLYPHS.clear()
    GLYPHS.update(ASCII_GLYPHS)


def clip(text: str, width: int) -> str:
    if width <= 0:
        return ""
    text = str(text).replace("\t", "    ").replace("\r", "").replace("\n", " ")
    return text[:width]


class Theme:
    """Curses colour pairs with a graceful monochrome fallback."""

    def __init__(self, win) -> None:
        self.colour = False
        try:
            if curses.has_colors():
                curses.start_color()
                try:
                    curses.use_default_colors()
                    background = -1
                except curses.error:
                    background = curses.COLOR_BLACK
                pairs = [
                    (1, curses.COLOR_CYAN),
                    (2, curses.COLOR_GREEN),
                    (3, curses.COLOR_YELLOW),
                    (4, curses.COLOR_RED),
                    (5, curses.COLOR_MAGENTA),
                    (6, curses.COLOR_BLUE),
                ]
                for index, colour in pairs:
                    curses.init_pair(index, colour, background)
                self.colour = True
        except curses.error:
            self.colour = False

        def pair(index: int, extra: int = 0) -> int:
            if not self.colour:
                return extra
            return curses.color_pair(index) | extra

        self.normal = 0
        self.accent = pair(1, curses.A_BOLD)
        self.ok = pair(2)
        self.warn = pair(3)
        self.error = pair(4, curses.A_BOLD)
        self.highlight = pair(5, curses.A_BOLD)
        self.dim = pair(6, curses.A_DIM)
        self.header = pair(1, curses.A_REVERSE | curses.A_BOLD)
        self.sel = pair(1, curses.A_REVERSE | curses.A_BOLD)
        self.title = curses.A_BOLD


class Painter:
    """Bounds-safe painting on a curses window."""

    def __init__(self, win, theme: Theme) -> None:
        self.win = win
        self.theme = theme
        try:
            self.h, self.w = win.getmaxyx()
        except curses.error:
            self.h, self.w = 24, 80
        self.content_top = 2

    # ---------------------------------------------------------------- basics
    def put(self, y: int, x: int, text, attr: int = 0, maxw: int | None = None) -> None:
        if y < 0 or x < 0 or y >= self.h or x >= self.w:
            return
        if maxw is None:
            maxw = self.w - x
        if maxw <= 0:
            return
        try:
            self.win.addstr(y, x, clip(text, maxw), attr)
        except UnicodeEncodeError:
            ascii_mode()
        except (curses.error, ValueError):
            pass

    def fill(self, y: int, x: int, height: int, width: int, attr: int = 0) -> None:
        if height <= 0 or width <= 0:
            return
        for row in range(height):
            self.put(y + row, x, " " * width, attr, width)

    def hline(self, y: int, x: int, width: int, attr: int = 0) -> None:
        self.put(y, x, GLYPHS["h"] * max(0, width), attr, width)

    def box(self, y: int, x: int, height: int, width: int, title: str = "", attr: int = 0, title_attr: int | None = None) -> None:
        if height < 2 or width < 2:
            return
        inner = width - 2
        self.put(y, x, GLYPHS["tl"] + GLYPHS["h"] * inner + GLYPHS["tr"], attr, width)
        for row in range(1, height - 1):
            self.put(y + row, x, GLYPHS["v"], attr, 1)
            self.put(y + row, x + width - 1, GLYPHS["v"], attr, 1)
        self.put(y + height - 1, x, GLYPHS["bl"] + GLYPHS["h"] * inner + GLYPHS["br"], attr, width)
        if title and inner >= 4:
            label = f" {clip(title, inner - 4)} "
            self.put(y, x + 2, label, title_attr if title_attr is not None else self.theme.title, inner - 2)

    def center(self, y: int, text: str, attr: int = 0) -> None:
        width = len(clip(text, max(0, self.w - 2)))
        self.put(y, max(0, (self.w - width) // 2), text, attr, max(0, self.w - 2))

    # ---------------------------------------------------------------- chrome
    def header(self, title: str, right: str = "") -> None:
        if self.h < 3:
            return
        self.fill(0, 0, 1, self.w, self.theme.header)
        self.put(0, 1, title, self.theme.header, self.w - 3)
        stamp = right or time.strftime("%H:%M:%S")
        if len(stamp) < self.w - 4:
            self.put(0, self.w - len(stamp) - 2, stamp, self.theme.header, len(stamp))

    @property
    def content_h(self) -> int:
        return max(1, self.h - 4)

    @property
    def content_bottom(self) -> int:
        """Last usable row inside the content box (the border sits below)."""
        return max(self.content_top, self.content_top + self.content_h - 2)

    def content_box(self, title: str = "") -> None:
        self.box(self.content_top, 0, self.content_h, self.w, title, self.theme.dim)

    def body(self, y_offset: int = 1) -> tuple[int, int, int]:
        """Return (x, top, width) of the inner body area."""
        return 1, self.content_top + y_offset, max(1, self.w - 2)

    def too_small(self) -> bool:
        return self.w < MIN_WIDTH or self.h < MIN_HEIGHT

    def size_warning(self) -> None:
        lines = [
            "Terminal too small for the Nova console.",
            f"Need at least {MIN_WIDTH} x {MIN_HEIGHT} cells.",
            f"Current size: {self.w} x {self.h}.",
            "",
            "Rotate the device or enlarge the terminal window.",
        ]
        for index, line in enumerate(lines):
            self.center(max(0, self.h // 2 - 2 + index), line, self.theme.warn)
