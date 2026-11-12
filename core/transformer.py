"""Geometry fitting helpers for PDF paths."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Sequence


Point = tuple[float, float]


@dataclass(frozen=True)
class CircleFit:
    center: Point
    radius: float
    max_error: float
    start_angle: float
    end_angle: float
    closed: bool


def fit_circle(points: Sequence[Point], tolerance: float) -> CircleFit | None:
    """Fit a circle to ordered points, returning only fits within tolerance."""
    if len(points) < 5:
        return None

    mean_x = sum(point[0] for point in points) / len(points)
    mean_y = sum(point[1] for point in points) / len(points)
    xx = xy = yy = xz = yz = 0.0
    for x, y in points:
        dx, dy = x - mean_x, y - mean_y
        z = dx * dx + dy * dy
        xx += dx * dx
        xy += dx * dy
        yy += dy * dy
        xz += dx * z
        yz += dy * z

    determinant = xx * yy - xy * xy
    if abs(determinant) < 1e-12:
        return None
    rhs_x, rhs_y = xz / 2.0, yz / 2.0
    offset_x = (rhs_x * yy - rhs_y * xy) / determinant
    offset_y = (rhs_y * xx - rhs_x * xy) / determinant
    center = mean_x + offset_x, mean_y + offset_y
    radius = sum(math.hypot(x - center[0], y - center[1]) for x, y in points) / len(points)
    max_error = max(abs(math.hypot(x - center[0], y - center[1]) - radius) for x, y in points)
    if radius <= 0 or max_error > tolerance:
        return None

    angles = [math.atan2(y - center[1], x - center[0]) % (2 * math.pi) for x, y in points]
    unwrapped = [angles[0]]
    for angle in angles[1:]:
        previous = unwrapped[-1]
        while angle - previous > math.pi:
            angle -= 2 * math.pi
        while angle - previous < -math.pi:
            angle += 2 * math.pi
        unwrapped.append(angle)
    return CircleFit(
        center=center,
        radius=radius,
        max_error=max_error,
        start_angle=math.degrees(unwrapped[0]),
        end_angle=math.degrees(unwrapped[-1]),
        closed=math.dist(points[0], points[-1]) <= tolerance,
    )


def sample_cubic_bezier(
    start: Point,
    control1: Point,
    control2: Point,
    end: Point,
    steps: int = 16,
) -> list[Point]:
    """Approximate a cubic Bézier segment with evenly spaced parameter samples."""
    if steps < 2:
        raise ValueError("steps must be at least 2")
    result: list[Point] = []
    for index in range(steps + 1):
        t = index / steps
        inverse = 1.0 - t
        result.append(
            (
                inverse**3 * start[0]
                + 3 * inverse**2 * t * control1[0]
                + 3 * inverse * t**2 * control2[0]
                + t**3 * end[0],
                inverse**3 * start[1]
                + 3 * inverse**2 * t * control1[1]
                + 3 * inverse * t**2 * control2[1]
                + t**3 * end[1],
            )
        )
    return result
