"""Offline unit converter used by the daily-programs suite."""

from __future__ import annotations

CATEGORIES: dict[str, dict[str, float]] = {
    "Length": {
        "meters": 1.0,
        "kilometers": 1000.0,
        "centimeters": 0.01,
        "millimeters": 0.001,
        "miles": 1609.344,
        "yards": 0.9144,
        "feet": 0.3048,
        "inches": 0.0254,
        "nautical miles": 1852.0,
    },
    "Mass": {
        "kilograms": 1.0,
        "grams": 0.001,
        "milligrams": 1e-06,
        "tonnes": 1000.0,
        "pounds": 0.45359237,
        "ounces": 0.028349523125,
        "stones": 6.35029318,
    },
    "Data": {
        "bytes": 1.0,
        "bits": 0.125,
        "kilobytes": 1024.0,
        "megabytes": 1024.0 ** 2,
        "gigabytes": 1024.0 ** 3,
        "terabytes": 1024.0 ** 4,
        "kibibytes": 1024.0,
        "mebibytes": 1024.0 ** 2,
    },
    "Speed": {
        "meters/second": 1.0,
        "kilometers/hour": 1 / 3.6,
        "miles/hour": 0.44704,
        "knots": 0.514444,
        "feet/second": 0.3048,
    },
    "Time": {
        "seconds": 1.0,
        "minutes": 60.0,
        "hours": 3600.0,
        "days": 86400.0,
        "weeks": 604800.0,
        "years (365d)": 31536000.0,
    },
    "Energy": {
        "joules": 1.0,
        "kilojoules": 1000.0,
        "calories": 4.184,
        "kilocalories": 4184.0,
        "watt hours": 3600.0,
        "kilowatt hours": 3.6e06,
    },
    "Pressure": {
        "pascals": 1.0,
        "kilopascals": 1000.0,
        "bar": 100000.0,
        "atmospheres": 101325.0,
        "psi": 6894.757293168,
    },
    "Temperature": {
        "celsius": 1.0,
        "fahrenheit": 1.0,
        "kelvin": 1.0,
    },
}


class ConversionError(ValueError):
    """Raised when a conversion cannot be performed."""


def categories() -> list[str]:
    return list(CATEGORIES)


def units(category: str) -> list[str]:
    try:
        return list(CATEGORIES[category])
    except KeyError as exc:
        raise ConversionError(f"Unknown category: {category}") from exc


def _to_celsius(category: str, unit: str, value: float) -> float:
    if unit == "celsius":
        return value
    if unit == "fahrenheit":
        return (value - 32.0) * 5.0 / 9.0
    if unit == "kelvin":
        return value - 273.15
    raise ConversionError(f"Unknown temperature unit: {unit}")


def _from_celsius(unit: str, celsius: float) -> float:
    if unit == "celsius":
        return celsius
    if unit == "fahrenheit":
        return celsius * 9.0 / 5.0 + 32.0
    if unit == "kelvin":
        return celsius + 273.15
    raise ConversionError(f"Unknown temperature unit: {unit}")


def convert(category: str, value: float, from_unit: str, to_unit: str) -> float:
    """Convert ``value`` between two units in ``category``."""
    if category not in CATEGORIES:
        raise ConversionError(f"Unknown category: {category}")
    table = CATEGORIES[category]
    if from_unit not in table:
        raise ConversionError(f"Unknown unit: {from_unit}")
    if to_unit not in table:
        raise ConversionError(f"Unknown unit: {to_unit}")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ConversionError("Value must be a number") from exc

    if category == "Temperature":
        celsius = _to_celsius(category, from_unit, number)
        if to_unit == "kelvin" and celsius < -273.15:
            raise ConversionError("Below absolute zero")
        return _from_celsius(to_unit, celsius)

    return number * table[from_unit] / table[to_unit]


def parse_value(text: str) -> float:
    cleaned = (text or "").strip().replace(",", "")
    if not cleaned:
        raise ConversionError("Enter a value")
    try:
        return float(cleaned)
    except ValueError as exc:
        raise ConversionError("Not a number") from exc


def format_value(value: float) -> str:
    if value == 0:
        return "0"
    magnitude = abs(value)
    if magnitude >= 1e12 or magnitude < 1e-6:
        return f"{value:.6e}"
    text = f"{value:,.6f}".rstrip("0").rstrip(".")
    return text or "0"
