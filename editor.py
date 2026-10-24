"""Reusable line-based editor screen.

The word processor and Code Studio share this widget; all buffer operations
live in :mod:`nova.docs` so they can be tested without a terminal.
"""

from __future__ import annotations

import curses
import time

from . import ui
from .docs import Doc
from .keyboard import keyboard_popup
from .keys import is_printable


def _expand(line: str) -> str:
    return line.replace("\t", "    ")


def _display_col(line: str, column: int) -> int:
    return len(_expand(line[:column]))


class EditorApp(ui.App):
    """Full-screen editor with optional line numbers and run hooks."""

    multiline_keyboard = True

    def __init__(
        self,
        ctx,
        doc: Doc,
        name: str,
        save_fn,
        title: str = "EDITOR",
        line_numbers: bool = False,
        extras: dict | None = None,
    ) -> None:
        super().__init__(ctx)
        self.doc = doc
        self.name = name
        self.save_fn = save_fn
        self.title = title
        self.line_numbers = line_numbers
        self.extras = extras or {}
        self.top = 0
        self.left = 0
        self.last_find = ""
        self.notice = ""
        self.notice_kind = "info"
        self.notice_until = 0.0
        parts = ["Ctrl-S Save", "Ctrl-F Find", "F6 Replace", "Ctrl-G Goto", "Ctrl-W Stats"]
        parts += [label for label, _ in self.extras.values()]
        self.hint = "   ".join(parts) + "   F10 Back"
        self.frame_ms = 300

    # ------------------------------------------------------------------ meta
    def say(self, message: str, kind: str = "info") -> None:
        super().say(message, kind)
        self.notice = message
        self.notice_kind = kind
        self.notice_until = time.monotonic() + 4.0

    def _position_text(self) -> str:
        stats = self.doc.stats()
        flag = "MODIFIED" if self.doc.modified else "saved"
        return (
            f"Ln {self.doc.cy + 1}/{stats['lines']}  Col {self.doc.cx + 1}  "
            f"Words {stats['words']}  Chars {stats['chars']}  [{flag}]"
        )

    # ---------------------------------------------------------------- render
    def render(self, p) -> None:
        box_top = p.content_top
        p.box(box_top, 0, p.content_h, p.w, f" {self.name} ", p.theme.dim)
        inner_top = box_top + 1
        inner_h = max(1, p.content_h - 2)
        inner_x = 1
        width = max(1, p.w - 2)
        gutter = 0
        if self.line_numbers:
            gutter = len(str(len(self.doc.lines))) + 1
        text_width = max(8, width - gutter - 1)

        if self.doc.cy < self.top:
            self.top = self.doc.cy
        elif self.doc.cy >= self.top + inner_h:
            self.top = self.doc.cy - inner_h + 1
        self.top = max(0, min(self.top, max(0, len(self.doc.lines) - inner_h)))

        display_x = _display_col(self.doc.lines[self.doc.cy], self.doc.cx)
        if display_x < self.left:
            self.left = display_x
        elif display_x >= self.left + text_width:
            self.left = display_x - text_width + 1
        self.left = max(0, self.left)

        for row in range(min(inner_h, len(self.doc.lines) - self.top)):
            index = self.top + row
            if gutter:
                marker = "▸" if index == self.doc.cy else " "
                p.put(
                    inner_top + row,
                    inner_x,
                    f"{marker}{index + 1:>{gutter - 1}} ",
                    p.theme.title if index == self.doc.cy else p.theme.dim,
                    gutter + 1,
                )
            text = _expand(self.doc.lines[index])
            p.put(inner_top + row, inner_x + gutter, text[self.left : self.left + text_width], 0, text_width)

        cursor_y = inner_top + (self.doc.cy - self.top)
        cursor_x = inner_x + gutter + (display_x - self.left)
        self.cursor = (cursor_y, cursor_x)
        if time.monotonic() > self.notice_until:
            self.notice = ""
        self.status = self.notice or self._position_text()
        self.status_kind = self.notice_kind if self.notice else "info"

    # ------------------------------------------------------------------ save
    def save(self) -> bool:
        try:
            message = self.save_fn(self.doc)
        except Exception as exc:  # surface I/O problems inside the console
            self.say(f"Save failed: {exc}", "error")
            return False
        self.doc.modified = False
        self.say(message or f"Saved {self.name}", "ok")
        self.ctx.log("EDITOR", f"Saved {self.name}")
        return True

    def can_exit(self) -> bool:
        if not self.doc.modified:
            return True
        choice = ui.choose(
            self.ctx.stdscr,
            self.ctx,
            "UNSAVED CHANGES",
            ["Save and leave", "Discard changes", "Stay here"],
        )
        if choice == 0:
            return self.save()
        if choice == 1:
            return True
        return False

    # --------------------------------------------------------------- editing
    def handle(self, key: str) -> bool:
        doc = self.doc
        if key == "CTRL-S":
            self.save()
        elif key == "CTRL-F":
            self.find()
        elif key == "F6":
            self.replace()
        elif key == "CTRL-G":
            self.goto()
        elif key == "CTRL-W":
            self.stats()
        elif key == "CTRL-K":
            edited = keyboard_popup(self.ctx.stdscr, self.ctx.theme, "INSERT TEXT", multiline=True)
            if edited:
                doc.insert(edited)
        elif key in self.extras:
            _, callback = self.extras[key]
            callback(self)
        elif key == "ENTER":
            indent = ""
            if self.line_numbers:
                indent = doc.indent_of()
                if doc.lines[doc.cy].rstrip().endswith(":"):
                    indent += "    "
            doc.newline(indent)
        elif key == "TAB":
            doc.insert("    ")
        elif key == "BACKSPACE":
            doc.backspace()
        elif key == "DELETE":
            doc.delete()
        elif key == "UP":
            doc.move(-1, 0)
        elif key == "DOWN":
            doc.move(1, 0)
        elif key == "LEFT":
            if doc.cx > 0:
                doc.move(0, -1)
            elif doc.cy > 0:
                doc.move(-1, 0)
                doc.end()
        elif key == "RIGHT":
            if doc.cx < len(doc.lines[doc.cy]):
                doc.move(0, 1)
            elif doc.cy < len(doc.lines) - 1:
                doc.move(1, 0)
                doc.home()
        elif key == "HOME":
            doc.home()
        elif key == "END":
            doc.end()
        elif key == "PGUP":
            doc.move(-max(1, self._page_height()), 0)
        elif key == "PGDN":
            doc.move(max(1, self._page_height()), 0)
        elif key == "CTRL-D":
            doc.delete_line()
        elif is_printable(key):
            doc.insert(key)
        return True

    def _page_height(self) -> int:
        if self.ctx.stdscr is None:
            return 10
        return max(1, self.ctx.stdscr.getmaxyx()[0] - 8)

    def on_keyboard(self, text: str) -> None:
        self.doc.insert(text)
        self.say(f"Inserted {len(text)} characters", "ok")

    def handle_mouse(self, y: int, x: int, bstate: int) -> bool:
        if self.ctx.stdscr is None:
            return False
        if not (bstate & (curses.BUTTON1_CLICKED | curses.BUTTON1_PRESSED)):
            return False
        height, _width = self.ctx.stdscr.getmaxyx()
        inner_top = 3
        gutter = (len(str(len(self.doc.lines))) + 1) if self.line_numbers else 0
        if y < inner_top or y > height - 3 or x < 1:
            return False
        line_index = self.top + (y - inner_top)
        if 0 <= line_index < len(self.doc.lines):
            raw_col = max(0, x - 1 - gutter + self.left)
            self.doc.set_cursor(line_index, min(raw_col, len(self.doc.lines[line_index])))
            return True
        return False

    # --------------------------------------------------------------- helpers
    def find(self) -> None:
        pattern = ui.prompt(
            self.ctx.stdscr,
            self.ctx,
            "FIND",
            "Search for:",
            value=self.last_find,
            hint="Case-insensitive · wraps around",
        )
        if not pattern:
            return
        self.last_find = pattern
        hit = self.doc.find_and_select(pattern)
        if hit:
            self.say(f"Match at line {hit[0] + 1}", "ok")
        else:
            self.say(f"No match for '{pattern}'", "warn")

    def replace(self) -> None:
        pattern = ui.prompt(
            self.ctx.stdscr, self.ctx, "REPLACE", "Find:", value=self.last_find, hint="Plain text, case-insensitive"
        )
        if not pattern:
            return
        self.last_find = pattern
        replacement = ui.prompt(self.ctx.stdscr, self.ctx, "REPLACE", "Replace with:", value="")
        if replacement is None:
            return
        if not ui.confirm(self.ctx.stdscr, self.ctx, "REPLACE ALL", f"Replace every '{pattern}'?"):
            return
        count = self.doc.replace_all(pattern, replacement)
        self.say(f"Replaced {count} occurrence(s)" if count else "No matches found", "ok" if count else "warn")

    def goto(self) -> None:
        value = ui.prompt(self.ctx.stdscr, self.ctx, "GO TO LINE", f"Line (1-{len(self.doc.lines)}):")
        if not value:
            return
        try:
            line = int(value.strip())
        except ValueError:
            self.say("That is not a line number", "error")
            return
        self.doc.goto(line)
        self.say(f"Moved to line {self.doc.cy + 1}", "ok")

    def stats(self) -> None:
        stats = self.doc.stats()
        body = "\n".join(
            [
                f"Document : {self.name}",
                "",
                f"Lines      : {stats['lines']}",
                f"Words      : {stats['words']}",
                f"Characters : {stats['chars']} ({stats['chars_no_space']} without spaces)",
                f"Paragraphs : {stats['paragraphs']}",
                f"Read time  : about {stats['reading_minutes']} minute(s)",
                "",
                f"Cursor at line {self.doc.cy + 1}, column {self.doc.cx + 1}",
            ]
        )
        ui.show_text(self.ctx.stdscr, self.ctx, "DOCUMENT STATISTICS", body)
