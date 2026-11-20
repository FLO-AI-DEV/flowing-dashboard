"""Safe arithmetic for the assistant: numbers, + - * / % **, brackets, and round / abs / min / max / sum.

Gemini never does the maths itself; it asks for calculate("...") and gets the exact result back.
"""
from __future__ import annotations

import ast
import math
import operator
import re

_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.Mod: operator.mod, ast.Pow: operator.pow, ast.FloorDiv: operator.floordiv}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNCS = {"round": round, "abs": abs, "min": min, "max": max, "sum": lambda *a: sum(a)}


class CalcError(ValueError):
    pass


def _clean(expr: str) -> str:
    s = str(expr).replace("₹", "").replace("×", "*").replace("÷", "/").replace("−", "-")
    s = re.sub(r"(?<=\d),(?=\d)", "", s)                      # 1,23,456 -> 123456
    s = re.sub(r"(\d+(?:\.\d+)?)\s*(cr|crore)\b", r"(\1*10000000)", s, flags=re.I)
    s = re.sub(r"(\d+(?:\.\d+)?)\s*(l|lakh|lac)\b", r"(\1*100000)", s, flags=re.I)
    s = re.sub(r"(\d+(?:\.\d+)?)\s*%", r"(\1/100)", s)
    return s


def _eval(node):
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
        a, b = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(b) > 10:
            raise CalcError("exponent too large")
        return _BIN[type(node.op)](a, b)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_eval(node.operand))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS and not node.keywords:
        return _FUNCS[node.func.id](*[_eval(a) for a in node.args])
    raise CalcError("only numbers, + - * / % ** ( ) and round/abs/min/max/sum are allowed")


def calculate(expression: str) -> float:
    s = _clean(expression)
    if len(s) > 300:
        raise CalcError("expression too long")
    try:
        tree = ast.parse(s, mode="eval")
    except SyntaxError as e:
        raise CalcError(f"could not read the expression: {expression!r}") from e
    try:
        v = _eval(tree)
    except ZeroDivisionError as e:
        raise CalcError("division by zero") from e
    if not isinstance(v, (int, float)) or not math.isfinite(v):
        raise CalcError("result is not a number")
    return float(v)
