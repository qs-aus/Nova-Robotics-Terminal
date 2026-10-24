"""Offline, sandboxed arithmetic evaluator for the Nova calculator.

Uses ``ast`` instead of ``eval`` so only arithmetic, comparisons and a small set
of math helpers are reachable. No names, no attribute access, no imports.
"""

from __future__ import annotations

import ast
import math

MAX_EXPONENT = 512
MAX_RESULT_DIGITS = 4000


class CalcError(ValueError):
    """Raised for anything the calculator refuses to compute."""


FUNCTIONS = {
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "sqrt": math.sqrt,
    "cbrt": lambda x: math.copysign(abs(x) ** (1 / 3), x),
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "asin": math.asin,
    "acos": math.acos,
    "atan": math.atan,
    "log": math.log10,
    "ln": math.log,
    "exp": math.exp,
    "floor": math.floor,
    "ceil": math.ceil,
    "fact": math.factorial,
    "degrees": math.degrees,
    "radians": math.radians,
    "hypot": math.hypot,
}

CONSTANTS = {"pi": math.pi, "e": math.e, "tau": math.tau, "inf": math.inf}


def _check_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CalcError("Only numbers are supported")
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        raise CalcError("Result is not a finite number")
    return value


def _eval(node):
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant):
        return _check_number(node.value)
    if isinstance(node, ast.Name):
        key = node.id.lower()
        if key in CONSTANTS:
            return CONSTANTS[key]
        raise CalcError(f"Unknown name: {node.id}")
    if isinstance(node, ast.UnaryOp):
        value = _eval(node.operand)
        if isinstance(node.op, ast.UAdd):
            return value
        if isinstance(node.op, ast.USub):
            return -value
        raise CalcError("Unsupported unary operator")
    if isinstance(node, ast.BinOp):
        left = _eval(node.left)
        right = _eval(node.right)
        op = node.op
        try:
            if isinstance(op, ast.Add):
                return _check_magnitude(left + right)
            if isinstance(op, ast.Sub):
                return _check_magnitude(left - right)
            if isinstance(op, ast.Mult):
                return _check_magnitude(left * right)
            if isinstance(op, ast.Div):
                if right == 0:
                    raise CalcError("Division by zero")
                return left / right
            if isinstance(op, ast.FloorDiv):
                if right == 0:
                    raise CalcError("Division by zero")
                return left // right
            if isinstance(op, ast.Mod):
                if right == 0:
                    raise CalcError("Division by zero")
                return left % right
            if isinstance(op, ast.Pow):
                if abs(right) > MAX_EXPONENT and abs(left) > 1:
                    raise CalcError("Exponent too large")
                if abs(left) > 1 and right > 64:
                    raise CalcError("Result too large")
                return _check_magnitude(left ** right)
        except OverflowError as exc:
            raise CalcError("Overflow") from exc
        raise CalcError("Unsupported operator")
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise CalcError("Unsupported function call")
        name = node.func.id.lower()
        func = FUNCTIONS.get(name)
        if func is None:
            raise CalcError(f"Unknown function: {node.func.id}")
        if node.keywords:
            raise CalcError("Keyword arguments are not supported")
        args = [_eval(arg) for arg in node.args]
        if name == "fact":
            if len(args) != 1 or args[0] < 0 or args[0] > 1000 or int(args[0]) != args[0]:
                raise CalcError("fact() wants a whole number from 0 to 1000")
            args = [int(args[0])]
        try:
            return _check_magnitude(func(*args))
        except CalcError:
            raise
        except (ValueError, TypeError, OverflowError) as exc:
            raise CalcError(str(exc) or "Bad arguments") from exc
    raise CalcError("Unsupported expression")


def _check_magnitude(value):
    _check_number(value)
    if isinstance(value, int) and value.bit_length() > MAX_RESULT_DIGITS * 3.33:
        raise CalcError("Result is too large to display")
    if isinstance(value, float) and abs(value) > 1e300:
        raise CalcError("Result is too large to display")
    return value


def evaluate(expression: str):
    """Evaluate ``expression`` and return a number, or raise :class:`CalcError`."""
    text = (expression or "").strip()
    if not text:
        raise CalcError("Empty expression")
    if len(text) > 400:
        raise CalcError("Expression too long")
    if "__" in text:
        raise CalcError("Unsupported expression")
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError as exc:
        raise CalcError(f"Syntax error: {exc.msg}") from exc
    result = _eval(tree)
    return result


def format_number(value) -> str:
    """Human friendly number formatting for display."""
    if isinstance(value, int):
        return str(value)
    if float(value).is_integer() and abs(value) < 1e16:
        return str(int(value))
    if value != 0 and (abs(value) >= 1e16 or abs(value) < 1e-6):
        return f"{value:.10g}"
    text = f"{value:.10f}".rstrip("0").rstrip(".")
    return text or "0"
