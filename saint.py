"""Simulated remote access to SAINT units.

This is a *simulation*: there is no socket, no network and no real robot. It
replays the film's fiction — uplink handshake, unit telemetry, directives and a
security trace if you stay connected too long. All writes go to the local
SQLite database so the console remains fully offline.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from . import config
from .store import Store

DIRECTIVES = [
    ("status", "Print full telemetry for the linked unit"),
    ("scan", "Sweep the sector and count nearby chassis"),
    ("move <location>", "Drive the unit to a new location"),
    ("diagnose", "Run a self-test and report faults"),
    ("recharge", "Top the unit's power cell to 100%"),
    ("patch <version>", "Upload a firmware patch"),
    ("broadcast <message>", "Send a message to every online unit"),
    ("shutdown", "Place the unit in standby"),
    ("revive", "Bring a standby/offline unit back online"),
    ("dance", "Request a morale performance"),
    ("selfdestruct YES", "Fiction-only emergency action"),
    ("trace", "Show the security trace level"),
    ("disconnect", "Close the uplink"),
    ("help", "List directives"),
]


@dataclass
class SaintResult:
    text: str
    kind: str = "info"  # info | ok | warn | error
    kicked: bool = False
    trace: int = 0


def link_quality(unit_id: int) -> tuple[int, int]:
    """Deterministic fake signal: (bars 1-4, latency in ms)."""
    latency = 18 + (int(unit_id) * 37) % 190
    if latency < 60:
        bars = 4
    elif latency < 115:
        bars = 3
    elif latency < 165:
        bars = 2
    else:
        bars = 1
    return bars, latency


def battery_bar(percent: int, width: int = 16) -> str:
    percent = max(0, min(100, int(percent)))
    filled = round(width * percent / 100)
    return "#" * filled + "-" * (width - filled)


class SaintNetwork:
    """The simulated uplink used by the SAINT Remote Access screen."""

    def __init__(self, store: Store, access_code: str | None = None, seed: int | None = None) -> None:
        self.store = store
        self.access_code = access_code or config.DEFAULT_ACCESS_CODE
        self.seed = int(seed if seed is not None else config.DEFAULT_SETTINGS["sim_seed"])
        self.rng = random.Random(self.seed)
        self.authenticated = False
        self.unit: dict | None = None
        self.trace = 0
        self.failures = 0
        self.locked = False
        self.directives = 0
        self.messages: list[str] = []

    # ------------------------------------------------------------------ auth
    def authenticate(self, code: str) -> SaintResult:
        if self.locked:
            return SaintResult(
                "SECURITY LOCKOUT — too many bad codes. Close the uplink and restart the console.",
                "error",
            )
        if (code or "").strip().upper() == str(self.access_code).strip().upper():
            self.authenticated = True
            self.failures = 0
            self._remember("UPLINK AUTHENTICATED — Nova Robotics field credentials accepted")
            return SaintResult("Credentials accepted. Select a chassis to link.", "ok")
        self.failures += 1
        remaining = 3 - self.failures
        if remaining <= 0:
            self.locked = True
            self.authenticated = False
            self._remember("SECURITY LOCKOUT after 3 failed access attempts")
            return SaintResult("SECURITY LOCKOUT — uplink sealed for this session.", "error")
        return SaintResult(f"Access denied. {remaining} attempt(s) before lockout.", "error")

    # --------------------------------------------------------------- linking
    def scan(self) -> list[dict]:
        units = self.store.list_units()
        for unit in units:
            bars, latency = link_quality(unit["id"])
            unit["bars"] = bars
            unit["latency"] = latency
        return units

    def connect(self, key: str | int) -> SaintResult:
        if not self.authenticated:
            return SaintResult("Access denied — authenticate before linking.", "error")
        unit = self.store.get_unit(key)
        if not unit:
            return SaintResult(f"No such chassis: {key}", "error")
        self.unit = unit
        self.trace = 0
        self.directives = 0
        self._remember(f"UPLINK ESTABLISHED -> {unit['callsign']} ({unit['model']})")
        return SaintResult(
            f"Uplink established with {unit['callsign']}.\n"
            f"{unit['model']} · {unit['status']} · battery {unit['battery']}%\n"
            "Type 'help' for directives, 'disconnect' to release the chassis.",
            "ok",
        )

    def disconnect(self, reason: str = "Operator released the uplink") -> SaintResult:
        if not self.unit:
            return SaintResult("No chassis linked.", "warn")
        callsign = self.unit["callsign"]
        self._remember(f"UPLINK CLOSED <- {callsign} ({reason})")
        self.unit = None
        self.trace = 0
        return SaintResult(f"Uplink to {callsign} closed.", "info")

    # ------------------------------------------------------------- telemetry
    def telemetry(self) -> str:
        if not self.unit:
            return "No chassis linked."
        unit = self.store.get_unit(self.unit["id"]) or self.unit
        self.unit = unit
        bars, latency = link_quality(unit["id"])
        return "\n".join(
            [
                f"CALLSIGN : {unit['callsign']}",
                f"MODEL    : {unit['model']}",
                f"STATUS   : {unit['status']}",
                f"LOCATION : {unit['location']}",
                f"BATTERY  : [{battery_bar(unit['battery'])}] {unit['battery']}%",
                f"FIRMWARE : {unit['firmware']}",
                f"CLEARANCE: {unit['clearance']}",
                f"LINK     : {'#' * bars}{'-' * (4 - bars)}  {latency} ms",
                f"TRACE    : [{battery_bar(self.trace, 20)}] {self.trace}%",
            ]
        )

    # ------------------------------------------------------------- directives
    def command(self, line: str) -> SaintResult:
        text = (line or "").strip()
        if not self.unit:
            return SaintResult("No chassis linked. Select a unit first.", "warn")
        if not text:
            return SaintResult("", "info")

        self.directives += 1
        call = text.split()[0].lower()
        argument = text[len(call) :].strip()
        unit = self.store.get_unit(self.unit["id"]) or self.unit

        if call in ("disconnect", "exit", "quit", "release"):
            return self.disconnect()

        if call in ("help", "?"):
            body = "\n".join(f"  {name:<20} {desc}" for name, desc in DIRECTIVES)
            return SaintResult("AVAILABLE DIRECTIVES\n" + body, "info")

        if call == "trace":
            self._remember("Trace level queried")
            return SaintResult(
                f"Security trace at {self.trace}%. "
                + ("Cut the link soon." if self.trace >= 70 else "Uplink still clean."),
                "warn" if self.trace >= 70 else "info",
            )

        # Directives that touch the database.
        if call == "status":
            self._remember(f"Telemetry requested from {unit['callsign']}")
            return SaintResult(self.telemetry(), "info")

        if call == "scan":
            contacts = [u for u in self.scan() if u["status"] == "online"]
            self._remember(f"Sector sweep: {len(contacts)} online contacts")
            nearest = min(contacts, key=lambda u: link_quality(u["id"])[1]) if contacts else None
            text_out = f"Sector sweep complete — {len(contacts)} online chassis detected."
            if nearest:
                text_out += (
                    f"\nStrongest return: {nearest['callsign']} at {nearest['location']}"
                    f" ({link_quality(nearest['id'])[1]} ms)."
                )
            return self._with_trace(SaintResult(text_out, "ok"), 1)

        if call == "diagnose":
            faults = self.rng.choice(
                [
                    "hydraulic pressure nominal",
                    "manipulator servo drift 0.4%",
                    "left tread tension low",
                    "power cell balanced",
                    "gyro calibration within tolerance",
                ]
            )
            self._remember(f"Diagnostics on {unit['callsign']}: {faults}")
            return self._with_trace(
                SaintResult(f"Self-test complete.\n  > {faults}\n  > no critical faults", "ok"), 1
            )

        if call == "move":
            if not argument:
                return SaintResult("Usage: move <location>", "warn")
            self.store.update_unit(unit["id"], location=argument[:80])
            self._remember(f"{unit['callsign']} drove to {argument}")
            return self._with_trace(
                SaintResult(f"{unit['callsign']} acknowledged. Now at: {argument}", "ok"), 3
            )

        if call == "recharge":
            self.store.update_unit(unit["id"], battery=100)
            self._remember(f"{unit['callsign']} recharged to 100%")
            return self._with_trace(SaintResult("Power cell at 100%. Charge cycle complete.", "ok"), 2)

        if call == "patch":
            if not argument:
                return SaintResult("Usage: patch <version>", "warn")
            self.store.update_unit(unit["id"], firmware=argument[:40])
            self._remember(f"Firmware {argument} pushed to {unit['callsign']}")
            return self._with_trace(
                SaintResult(f"Firmware {argument} uploaded. Unit rebooted cleanly.", "ok"), 2
            )

        if call == "broadcast":
            if not argument:
                return SaintResult("Usage: broadcast <message>", "warn")
            online = [u for u in self.scan() if u["status"] == "online"]
            self._remember(f"Broadcast to {len(online)} units: {argument}")
            return self._with_trace(
                SaintResult(f"Message relayed to {len(online)} online units.", "ok"), 1
            )

        if call == "shutdown":
            self.store.update_unit(unit["id"], status="standby")
            self._remember(f"{unit['callsign']} placed in standby")
            return self._with_trace(
                SaintResult(f"{unit['callsign']} is entering standby. Link will remain open.", "warn"), 4
            )

        if call == "revive":
            self.store.update_unit(unit["id"], status="online")
            self._remember(f"{unit['callsign']} brought online")
            return self._with_trace(SaintResult(f"{unit['callsign']} is online and awaiting orders.", "ok"), 2)

        if call == "dance":
            self._remember(f"Morale performance requested from {unit['callsign']}")
            return self._with_trace(
                SaintResult(
                    f"{unit['callsign']} plays a jaunty tune and shuffles its treads.\n"
                    '"Need more input!"',
                    "ok",
                ),
                1,
            )

        if call == "selfdestruct":
            if argument.strip().upper() != "YES":
                return SaintResult(
                    "Self-destruct sequence is fiction-only here. Re-issue as: selfdestruct YES",
                    "warn",
                )
            self.store.update_unit(unit["id"], status="offline", notes="Decommissioned via demo self-destruct.")
            self._remember(f"DEMO SELF-DESTRUCT on {unit['callsign']} (simulation only)")
            result = SaintResult(
                "SIMULATION ONLY — no hardware affected.\n"
                f"{unit['callsign']} marked offline and logged for decommissioning.",
                "warn",
            )
            result.kicked = True
            self.unit = None
            self.trace = 0
            return result

        self._remember(f"Unknown directive: {text}")
        return SaintResult(f"Unknown directive '{call}'. Type 'help'.", "warn")

    # ---------------------------------------------------------------- tracing
    def _with_trace(self, result: SaintResult, amount: int) -> SaintResult:
        self.trace = min(100, self.trace + amount + self.rng.randint(0, 2))
        result.trace = self.trace
        if self.trace >= 100:
            result.kicked = True
            result.text += "\n\n!! SECURITY TRACE COMPLETE — UPLINK FORCIBLY TERMINATED !!"
            self._remember("Security trace completed; uplink terminated by Nova Security")
            self.unit = None
            self.trace = 0
        elif self.trace >= 70:
            result.text += f"\n\n[warning] security trace at {self.trace}%"
        return result

    def _remember(self, message: str) -> None:
        self.messages.append(message)
        self.messages = self.messages[-400:]
        try:
            self.store.log("SAINT", message)
        except Exception:
            pass
