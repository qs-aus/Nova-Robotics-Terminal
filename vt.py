"""A tiny VT100 screen emulator plus a pty harness for the Nova console.

Used by the UI smoke tests so assertions can look at the *rendered screen*
instead of raw escape-sequence soup.
"""

from __future__ import annotations

import codecs
import fcntl
import os
import pty
import re
import select
import struct
import subprocess
import sys
import tempfile
import termios
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

KEYS = {
    "up": b"\x1bOA",
    "down": b"\x1bOB",
    "right": b"\x1bOC",
    "left": b"\x1bOD",
    "home": b"\x1bOH",
    "end": b"\x1bOF",
    "pgup": b"\x1b[5~",
    "pgdn": b"\x1b[6~",
    "enter": b"\r",
    "esc": b"\x1b",
    "tab": b"\t",
    "space": b" ",
    "backspace": b"\x7f",
    "delete": b"\x1b[3~",
    "f1": b"\x1bOP",
    "f2": b"\x1bOQ",
    "f4": b"\x1bOS",
    "f6": b"\x1b[17~",
    "f7": b"\x1b[18~",
    "f8": b"\x1b[19~",
    "f9": b"\x1b[20~",
    "f10": b"\x1b[21~",
    "ctrl-s": b"\x13",
    "ctrl-q": b"\x11",
    "ctrl-f": b"\x06",
    "ctrl-g": b"\x07",
    "ctrl-k": b"\x0b",
    "ctrl-l": b"\x0c",
    "ctrl-u": b"\x15",
    "ctrl-w": b"\x17",
    "ctrl-b": b"\x02",
}


class VirtualTerminal:
    """Enough of a VT100 for curses output: CUP, ED, EL, SGR and friends."""

    def __init__(self, rows: int = 30, cols: int = 100) -> None:
        self.rows = rows
        self.cols = cols
        self.grid = [[" "] * cols for _ in range(rows)]
        self.y = 0
        self.x = 0
        self.saved = (0, 0)
        self.scroll_top = 0
        self.scroll_bottom = rows - 1
        self.pending = ""
        self.decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self.mouse_sgr = False

    # ------------------------------------------------------------------ feed
    def feed(self, data: bytes) -> None:
        self._parse(self.decoder.decode(data))

    def _parse(self, text: str) -> None:
        buffer = self.pending + text
        index = 0
        while index < len(buffer):
            char = buffer[index]
            if char == "\x1b":
                consumed = self._escape(buffer, index)
                if consumed == 0:
                    break
                index += consumed
                continue
            self._put_char(char)
            index += 1
        self.pending = buffer[index:]

    def _escape(self, text: str, index: int) -> int:
        if index + 1 >= len(text):
            return 0
        kind = text[index + 1]
        if kind == "[":
            end = index + 2
            while end < len(text) and not ("\x40" <= text[end] <= "\x7e"):
                end += 1
            if end >= len(text):
                return 0
            self._csi(text[index + 2 : end], text[end])
            return end - index + 1
        if kind == "]":
            end = text.find("\x07", index + 2)
            if end < 0:
                return 0
            return end - index + 1
        if kind in "()*+-./":
            if index + 2 >= len(text):
                return 0
            return 3
        if kind == "7":
            self.saved = (self.y, self.x)
            return 2
        if kind == "8":
            self.y, self.x = self.saved
            return 2
        if kind == "M":
            self._scroll_up(0)
            return 2
        return 2

    def _csi(self, param_text: str, final: str) -> None:
        private = param_text.startswith("?")
        cleaned = param_text.lstrip("?<>=")
        parts = re.split(r"[;:]", cleaned) if cleaned else []
        params = []
        for part in parts:
            try:
                params.append(int(part) if part else 0)
            except ValueError:
                params.append(0)

        def param(index: int, default: int = 1) -> int:
            if index < len(params) and params[index]:
                return params[index]
            return default

        if final in ("H", "f"):
            self.y = max(0, min(self.rows - 1, param(0) - 1))
            self.x = max(0, min(self.cols - 1, param(1) - 1))
        elif final == "A":
            self.y = max(0, self.y - param(0))
        elif final == "B":
            self.y = min(self.rows - 1, self.y + param(0))
        elif final == "C":
            self.x = min(self.cols - 1, self.x + param(0))
        elif final == "D":
            self.x = max(0, self.x - param(0))
        elif final == "E":
            self.y = min(self.rows - 1, self.y + param(0))
            self.x = 0
        elif final == "F":
            self.y = max(0, self.y - param(0))
            self.x = 0
        elif final == "G":
            self.x = max(0, min(self.cols - 1, param(0) - 1))
        elif final == "d":
            self.y = max(0, min(self.rows - 1, param(0) - 1))
        elif final == "J":
            mode = params[0] if params else 0
            if mode == 0:
                self._clear_to_end()
            elif mode == 1:
                for row in range(0, self.y):
                    self.grid[row] = [" "] * self.cols
                self._clear_line(0, self.x, self.cols)
            else:
                self.grid = [[" "] * self.cols for _ in range(self.rows)]
        elif final == "K":
            mode = params[0] if params else 0
            if mode == 0:
                self._clear_line(self.y, self.x, self.cols)
            elif mode == 1:
                self._clear_line(self.y, 0, self.x + 1)
            else:
                self._clear_line(self.y, 0, self.cols)
        elif final == "X":
            for col in range(self.x, min(self.cols, self.x + param(0))):
                self.grid[self.y][col] = " "
        elif final == "@":
            count = param(0)
            row = self.grid[self.y]
            for _ in range(count):
                row.insert(self.x, " ")
                row.pop()
        elif final == "P":
            row = self.grid[self.y]
            for _ in range(param(0)):
                if self.x < len(row):
                    del row[self.x]
                    row.append(" ")
        elif final == "L":
            self._insert_lines(param(0))
        elif final == "M":
            self._delete_lines(param(0))
        elif final == "S":
            for _ in range(param(0)):
                self._scroll_up(0)
        elif final == "T":
            for _ in range(param(0)):
                self._scroll_down(0)
        elif final == "r":
            top = param(0) - 1
            bottom = param(1, self.rows) - 1
            if 0 <= top < bottom < self.rows:
                self.scroll_top, self.scroll_bottom = top, bottom
                self.y, self.x = 0, 0
        elif final in ("h", "l"):
            if private and 1006 in params and final == "h":
                self.mouse_sgr = True
            if private and 1049 in params:
                self.grid = [[" "] * self.cols for _ in range(self.rows)]
                self.y = self.x = 0
        # SGR, cursor visibility, mouse modes and others are irrelevant here.

    # ------------------------------------------------------------- primitives
    def _put_char(self, char: str) -> None:
        if char == "\n":
            self.y += 1
            if self.y > self.scroll_bottom:
                self._scroll_up(0)
                self.y = self.scroll_bottom
            return
        if char == "\r":
            self.x = 0
            return
        if char == "\b":
            self.x = max(0, self.x - 1)
            return
        if char == "\t":
            self.x = min(self.cols - 1, (self.x // 8 + 1) * 8)
            return
        if char in ("\x00", "\x07", "\x0e", "\x0f"):
            return
        if self.x >= self.cols:
            self.x = 0
            self.y += 1
            if self.y > self.scroll_bottom:
                self._scroll_up(0)
                self.y = self.scroll_bottom
        if 0 <= self.y < self.rows and 0 <= self.x < self.cols:
            self.grid[self.y][self.x] = char
        self.x += 1

    def _clear_line(self, row: int, start: int, end: int) -> None:
        for col in range(max(0, start), min(self.cols, end)):
            self.grid[row][col] = " "

    def _clear_to_end(self) -> None:
        self._clear_line(self.y, self.x, self.cols)
        for row in range(self.y + 1, self.rows):
            self.grid[row] = [" "] * self.cols

    def _scroll_up(self, count: int) -> None:
        for _ in range(max(1, count)):
            del self.grid[self.scroll_top]
            self.grid.insert(self.scroll_bottom, [" "] * self.cols)

    def _scroll_down(self, count: int) -> None:
        for _ in range(max(1, count)):
            del self.grid[self.scroll_bottom]
            self.grid.insert(self.scroll_top, [" "] * self.cols)

    def _insert_lines(self, count: int) -> None:
        for _ in range(max(1, count)):
            del self.grid[self.scroll_bottom]
            self.grid.insert(self.y, [" "] * self.cols)

    def _delete_lines(self, count: int) -> None:
        for _ in range(max(1, count)):
            del self.grid[self.y]
            self.grid.insert(self.scroll_bottom, [" "] * self.cols)

    # ------------------------------------------------------------------ view
    def text(self) -> str:
        return "\n".join("".join(row).rstrip() for row in self.grid)

    def line(self, row: int) -> str:
        return "".join(self.grid[row]).rstrip()

    def contains(self, needle: str) -> bool:
        return needle.lower() in self.text().lower()

    def find(self, needle: str) -> tuple[int, int] | None:
        needle = needle.lower()
        for row, line in enumerate(self.grid):
            col = "".join(line).lower().find(needle)
            if col >= 0:
                return row, col
        return None


class ConsoleSession:
    """Run nova.py inside a pty and drive it with terminal input."""

    def __init__(self, rows: int = 30, cols: int = 100, args: tuple[str, ...] = ("--no-boot",), home: str | None = None) -> None:
        self.rows = rows
        self.cols = cols
        self.home = home or tempfile.mkdtemp(prefix="nova_test_")
        self.master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        env = dict(
            os.environ,
            TERM="xterm-256color",
            LANG="C.UTF-8",
            NOVA_HOME=self.home,
            PYTHONIOENCODING="utf-8",
        )
        self.proc = subprocess.Popen(
            [sys.executable, "-X", "utf8", str(ROOT / "nova.py"), *args],
            stdin=slave,
            stdout=slave,
            stderr=slave,
            cwd=str(ROOT),
            env=env,
            close_fds=True,
        )
        os.close(slave)
        self.terminal = VirtualTerminal(rows, cols)
        self.raw = b""
        self.last_output = ""

    # ------------------------------------------------------------------- io
    def read(self, seconds: float = 0.35) -> str:
        deadline = time.time() + seconds
        chunks = []
        while time.time() < deadline:
            ready, _, _ = select.select([self.master], [], [], 0.05)
            if not ready:
                continue
            try:
                chunk = os.read(self.master, 65536)
            except OSError:
                break
            if not chunk:
                break
            chunks.append(chunk)
            self.raw += chunk
            self.terminal.feed(chunk)
        self.last_output = b"".join(chunks).decode("utf-8", "replace")
        return self.last_output

    def send(self, data: bytes, seconds: float = 0.35) -> str:
        os.write(self.master, data)
        return self.read(seconds)

    def key(self, name: str, seconds: float = 0.35) -> str:
        return self.send(KEYS[name], seconds)

    def type_text(self, text: str, seconds: float = 0.35) -> str:
        return self.send(text.encode("utf-8"), seconds)

    def wait_for(self, needle: str, timeout: float = 8.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            self.read(0.15)
            if self.terminal.contains(needle):
                return True
        return False

    def screen(self) -> str:
        return self.terminal.text()

    def click(self, x: int, y: int) -> str:
        if self.terminal.mouse_sgr:
            payload = f"\x1b[<0;{x + 1};{y + 1}M\x1b[<0;{x + 1};{y + 1}m"
            return self.send(payload.encode(), 0.4)
        # Classic X10 encoding (button 1 press then release).
        return self.send(b"\x1b[M" + bytes([32, 32 + x, 32 + y]) + b"\x1b[M" + bytes([35, 32 + x, 32 + y]), 0.4)

    def close(self) -> int:
        if self.proc.poll() is None:
            try:
                os.write(self.master, b"\x11")
                self.read(0.2)
                os.write(self.master, b"y")
                self.read(0.3)
            except OSError:
                pass
        try:
            code = self.proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.proc.terminate()
            code = self.proc.wait(timeout=2)
        try:
            os.close(self.master)
        except OSError:
            pass
        return code
