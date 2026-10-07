"""Timeline interpolation. Mirrored in frontend/light-timeline-panel.js; keep both in sync."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

from homeassistant.util.color import color_temperature_to_rgb

DAY = 86400

EASINGS = {
    "linear": lambda t: t,
    "ease_in": lambda t: t * t,
    "ease_out": lambda t: 1 - (1 - t) ** 2,
    "ease_in_out": lambda t: 2 * t * t if t < 0.5 else 1 - (-2 * t + 2) ** 2 / 2,
    "sine": lambda t: (1 - math.cos(math.pi * t)) / 2,
    "step": lambda t: 0.0,
}

_LOG_K = 5.0


def _cie(p: float) -> float:
    lightness = p * 100
    return lightness / 903.3 if lightness <= 8 else ((lightness + 16) / 116) ** 3


def _cie_inv(o: float) -> float:
    return (o * 903.3 if o <= 8 / 903.3 else 116 * o ** (1 / 3) - 16) / 100


# Each curve maps perceived level -> light output (both 0..1), with its inverse.
CURVES = {
    "linear": (lambda p: p, lambda o: o),
    "square": (lambda p: p * p, math.sqrt),
    "cubic": (lambda p: p**3, lambda o: o ** (1 / 3)),
    "cie": (_cie, _cie_inv),
    "log": (
        lambda p: math.expm1(_LOG_K * p) / math.expm1(_LOG_K),
        lambda o: math.log1p(o * math.expm1(_LOG_K)) / _LOG_K,
    ),
}

Node = dict[str, Any]


@dataclass
class Target:
    """Light state at a moment in time."""

    brightness: float
    kelvin: int | None = None
    rgb: tuple[int, int, int] | None = None


def _segment(nodes: list[Node], t: float) -> tuple[Node, Node, float]:
    """Return start node, end node and progress (0..1) for time t. Wraps at midnight."""
    if len(nodes) == 1:
        return nodes[0], nodes[0], 0.0
    for a, b in zip(nodes, nodes[1:]):
        if a["t"] <= t < b["t"]:
            return a, b, (t - a["t"]) / (b["t"] - a["t"])
    a, b = nodes[-1], nodes[0]
    span = (b["t"] - a["t"]) % DAY or DAY
    return a, b, ((t - a["t"]) % DAY) / span


def _color(node: Node) -> tuple[str, Any] | None:
    mode = node.get("mode", "none")
    if mode == "ct":
        return ("ct", node["k"])
    if mode == "rgb":
        return ("rgb", tuple(node["rgb"]))
    return None


def _as_rgb(color: tuple[str, Any]) -> tuple[float, float, float]:
    return color[1] if color[0] == "rgb" else color_temperature_to_rgb(color[1])


def target_at(nodes: list[Node], t: float, fade_to_warm: bool = False) -> Target:
    """Interpolate the target state at seconds-of-day t (nodes sorted, non-empty)."""
    a, b, x = _segment(nodes, t)
    e = EASINGS.get(a.get("ease"), EASINGS["linear"])(x)
    curve, inverse = CURVES.get(a.get("curve"), CURVES["linear"])
    p0, p1 = inverse(a["b"] / 100), inverse(b["b"] / 100)
    target = Target(curve(p0 + (p1 - p0) * e) * 100)

    if fade_to_warm:
        target.kelvin = math.floor(1000 + 17 * target.brightness + 0.5)
        return target

    start = _color(a)
    if start is None:
        return target
    end = _color(b) or start
    if start[0] == end[0] == "ct":
        m0, m1 = 1e6 / start[1], 1e6 / end[1]
        target.kelvin = round(1e6 / (m0 + (m1 - m0) * e))
    else:
        c0, c1 = _as_rgb(start), _as_rgb(end)
        target.rgb = tuple(round(u + (v - u) * e) for u, v in zip(c0, c1))
    return target


def plan(
    nodes: list[Node], t: float, lookahead: float, fade_to_warm: bool = False
) -> tuple[Target, float]:
    """Return the state to send now and its transition time in seconds."""
    start, _, _ = _segment(nodes, t)
    if lookahead <= 0 or start.get("ease") == "step":
        return target_at(nodes, t, fade_to_warm), 0.0
    return target_at(nodes, (t + lookahead) % DAY, fade_to_warm), lookahead


def seconds_to_next_node(nodes: list[Node], t: float) -> float:
    """Seconds until the next node after t."""
    return min(((n["t"] - t) % DAY) or DAY for n in nodes)
