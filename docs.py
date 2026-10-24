"""A small, testable text-document model.

The editor UI is only a view; all buffer operations live here so they can be
unit-tested without a terminal.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class Doc:
    title: str = "Untitled"
    lines: list[str] = field(default_factory=lambda: [""])
    cy: int = 0
    cx: int = 0
    modified: bool = False
    goal_x: int | None = None

    # ------------------------------------------------------------------ setup
    @classmethod
    def from_text(cls, text: str, title: str = "Untitled") -> "Doc":
        normalized = (text or "").replace("\r\n", "\n").replace("\r", "\n")
        lines = normalized.split("\n")
        return cls(title=title, lines=lines or [""])

    @property
    def text(self) -> str:
        return "\n".join(self.lines)

    def clamp(self) -> None:
        if not self.lines:
            self.lines = [""]
        self.cy = max(0, min(self.cy, len(self.lines) - 1))
        self.cx = max(0, min(self.cx, len(self.lines[self.cy])))

    def set_cursor(self, cy: int, cx: int) -> None:
        self.cy, self.cx = cy, cx
        self.goal_x = None
        self.clamp()

    # --------------------------------------------------------------- editing
    def insert(self, text: str) -> None:
        if not text:
            return
        parts = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        head = self.lines[self.cy][: self.cx]
        tail = self.lines[self.cy][self.cx :]
        if len(parts) == 1:
            self.lines[self.cy] = head + parts[0] + tail
            self.cx = len(head) + len(parts[0])
        else:
            replacement = [head + parts[0], *parts[1:-1], parts[-1] + tail]
            self.lines[self.cy : self.cy + 1] = replacement
            self.cy += len(parts) - 1
            self.cx = len(parts[-1])
        self.modified = True
        self.goal_x = None

    def newline(self, indent: str = "") -> None:
        self.insert("\n" + indent if indent else "\n")

    def backspace(self) -> None:
        if self.cx > 0:
            line = self.lines[self.cy]
            self.lines[self.cy] = line[: self.cx - 1] + line[self.cx :]
            self.cx -= 1
        elif self.cy > 0:
            previous = self.lines[self.cy - 1]
            current = self.lines[self.cy]
            self.lines[self.cy - 1] = previous + current
            del self.lines[self.cy]
            self.cy -= 1
            self.cx = len(previous)
        else:
            return
        self.modified = True
        self.goal_x = None

    def delete(self) -> None:
        line = self.lines[self.cy]
        if self.cx < len(line):
            self.lines[self.cy] = line[: self.cx] + line[self.cx + 1 :]
        elif self.cy < len(self.lines) - 1:
            self.lines[self.cy] = line + self.lines[self.cy + 1]
            del self.lines[self.cy + 1]
        else:
            return
        self.modified = True
        self.goal_x = None

    def delete_line(self) -> None:
        if len(self.lines) == 1:
            self.lines = [""]
        else:
            del self.lines[self.cy]
        self.cx = 0
        self.modified = True

    # -------------------------------------------------------------- movement
    def move(self, dy: int = 0, dx: int = 0) -> None:
        if dy:
            target = self.cy + dy
            target = max(0, min(target, len(self.lines) - 1))
            if target != self.cy:
                if self.goal_x is None:
                    self.goal_x = self.cx
                self.cy = target
                self.cx = min(self.goal_x, len(self.lines[self.cy]))
        if dx:
            self.cx += dx
            self.goal_x = None
            self.clamp()

    def home(self) -> None:
        self.cx = 0
        self.goal_x = None

    def end(self) -> None:
        self.cx = len(self.lines[self.cy])
        self.goal_x = None

    def goto(self, line_number: int) -> None:
        self.cy = max(0, min(line_number - 1, len(self.lines) - 1))
        self.cx = 0
        self.goal_x = None

    # ---------------------------------------------------------------- search
    def _compiled(self, pattern: str, regex: bool):
        if regex:
            try:
                return re.compile(pattern, re.IGNORECASE)
            except re.error as exc:
                raise ValueError(f"Bad pattern: {exc}") from exc
        return re.compile(re.escape(pattern), re.IGNORECASE)

    def find(self, pattern: str, regex: bool = False, wrap: bool = True):
        """Return ``(line, start, end)`` of the next match after the cursor."""
        if not pattern:
            return None
        rx = self._compiled(pattern, regex)
        order = list(range(self.cy, len(self.lines)))
        if wrap:
            order += list(range(0, self.cy))
        for cy in order:
            start_at = self.cx if cy == self.cy else 0
            if start_at > len(self.lines[cy]):
                start_at = len(self.lines[cy])
            match = rx.search(self.lines[cy], start_at)
            if match:
                return cy, match.start(), match.end()
        return None

    def find_and_select(self, pattern: str, regex: bool = False, wrap: bool = True):
        hit = self.find(pattern, regex=regex, wrap=wrap)
        if hit:
            self.set_cursor(hit[0], hit[1])
            return hit
        return None

    def replace_all(self, pattern: str, replacement: str, regex: bool = False) -> int:
        if not pattern:
            return 0
        if regex:
            compiled = self._compiled(pattern, True)
        else:
            compiled = re.compile(re.escape(pattern), re.IGNORECASE)
        total = 0
        for index, line in enumerate(self.lines):
            new_line, count = compiled.subn(lambda _m: replacement, line)
            if count:
                self.lines[index] = new_line
                total += count
        if total:
            self.modified = True
            self.clamp()
        return total

    # ----------------------------------------------------------------- stats
    def words(self) -> int:
        return sum(len(line.split()) for line in self.lines)

    def stats(self) -> dict:
        text = self.text
        chars = len(text)
        chars_no_space = len(re.sub(r"\s", "", text))
        paragraphs = len([b for b in re.split(r"\n\s*\n", text) if b.strip()])
        words = self.words()
        return {
            "lines": len(self.lines),
            "words": words,
            "chars": chars,
            "chars_no_space": chars_no_space,
            "paragraphs": paragraphs,
            "reading_minutes": max(1, round(words / 220)) if words else 0,
        }

    def indent_of(self, line_index: int | None = None) -> str:
        line = self.lines[self.cy if line_index is None else line_index]
        return line[: len(line) - len(line.lstrip(" \t"))]


def safe_filename(name: str, default: str = "untitled", extension: str = ".txt") -> str:
    """Turn a title into a portable filename."""
    stem = re.sub(r"[^A-Za-z0-9 ._-]+", "", name or "").strip().strip(".")
    stem = re.sub(r"\s+", "_", stem)[:80] or default
    if extension and not stem.lower().endswith(extension):
        stem += extension
    return stem
