"""Extract vector paths, text, and fills from vector PDFs with PyMuPDF."""

from __future__ import annotations

from dataclasses import dataclass, field
from concurrent.futures import CancelledError
import hashlib
import math
from pathlib import Path
from threading import Event
from typing import Any

import fitz

from .transformer import Point, fit_circle, sample_cubic_bezier

PDF_POINT_TO_MM = 25.4 / 72.0
CURVE_TOLERANCE_MM = 0.01


@dataclass(frozen=True)
class Entity:
    kind: str
    points: tuple[Point, ...] = ()
    layer: str = "0"
    stroke: tuple[float, float, float] | None = None
    fill: tuple[float, float, float] | None = None
    width: float = 0.0
    text: str = ""
    text_height: float = 2.5
    radius: float = 0.0
    start_angle: float = 0.0
    end_angle: float = 0.0
    rotation: float = 0.0
    image_key: str = ""
    closed: bool = False


@dataclass
class ParsedDocument:
    entities: list[Entity] = field(default_factory=list)
    page_count: int = 0
    warnings: list[str] = field(default_factory=list)
    images: dict[str, "RasterImage"] = field(default_factory=dict)


@dataclass(frozen=True)
class RasterImage:
    """PNG raster payload referenced by one or more DXF IMAGE entities."""

    key: str
    data: bytes
    width: int
    height: int


def _rotated_point(point: Point, rotation: fitz.Matrix) -> Point:
    transformed = fitz.Point(*point) * rotation
    return transformed.x, transformed.y


def _point(value: Any, page_offset_mm: float, rotation: fitz.Matrix) -> Point:
    x, y = _rotated_point((value.x, value.y), rotation)
    return x * PDF_POINT_TO_MM, -y * PDF_POINT_TO_MM - page_offset_mm


def _image_asset(block: dict[str, Any]) -> RasterImage:
    image_data = block.get("image")
    if not isinstance(image_data, bytes) or not image_data:
        raise ValueError("PDF raster image has no extractable image data")
    pixmap = fitz.Pixmap(image_data)
    mask_data = block.get("mask")
    if isinstance(mask_data, bytes) and mask_data:
        pixmap = fitz.Pixmap(pixmap, fitz.Pixmap(mask_data))
    data = pixmap.tobytes("png")
    return RasterImage(
        key=hashlib.sha256(data).hexdigest(),
        data=data,
        width=pixmap.width,
        height=pixmap.height,
    )


def _image_points(
    transform: tuple[float, float, float, float, float, float],
    page_offset_mm: float,
    rotation: fitz.Matrix,
) -> tuple[Point, Point, Point]:
    a, b, c, d, e, f = transform

    def convert(point: Point) -> Point:
        rotated_x, rotated_y = _rotated_point(point, rotation)
        return (
            rotated_x * PDF_POINT_TO_MM,
            -rotated_y * PDF_POINT_TO_MM - page_offset_mm,
        )

    return convert((e, f)), convert((a + e, b + f)), convert((c + e, d + f))


def _text_trace_for_span(
    span: dict[str, Any], traces: list[dict[str, Any]]
) -> dict[str, Any] | None:
    origin = span.get("origin")
    if not origin:
        return None
    best: dict[str, Any] | None = None
    best_distance = float("inf")
    span_size = float(span.get("size", 0.0))
    for trace in traces:
        characters = trace.get("chars", ())
        if not characters or abs(float(trace.get("size", 0.0)) - span_size) > 1.0:
            continue
        distance = math.dist(origin, characters[0][2])
        if distance < best_distance:
            best, best_distance = trace, distance
    return best if best_distance <= 1.0 else None


def _text_rotation(direction: tuple[float, float], rotation: fitz.Matrix) -> float:
    dx, dy = direction
    rotated_x = rotation.a * dx + rotation.c * dy
    rotated_y = rotation.b * dx + rotation.d * dy
    return math.degrees(math.atan2(-rotated_y, rotated_x)) % 360.0


def _color(value: Any) -> tuple[float, float, float] | None:
    if value is None or len(value) < 3:
        return None
    return (
        max(0.0, min(1.0, float(value[0]))),
        max(0.0, min(1.0, float(value[1]))),
        max(0.0, min(1.0, float(value[2]))),
    )


def _path_contours(items: list[tuple[Any, ...]]) -> list[tuple[list[Point], bool]]:
    contours: list[tuple[list[Point], bool]] = []
    points: list[Point] = []

    def finish(closed: bool = False) -> None:
        nonlocal points
        if len(points) >= 2:
            contours.append((points, closed))
        points = []

    for item in items:
        kind = item[0]
        if kind == "l":
            start, end = item[1], item[2]
            start_point = (start.x, start.y)
            if points and math.dist(points[-1], start_point) > 1e-4:
                finish()
            if not points:
                points.append(start_point)
            points.append((end.x, end.y))
        elif kind == "c":
            start, control1, control2, end = item[1:]
            start_point = (start.x, start.y)
            if points and math.dist(points[-1], start_point) > 1e-4:
                finish()
            sampled = sample_cubic_bezier(
                (start.x, start.y),
                (control1.x, control1.y),
                (control2.x, control2.y),
                (end.x, end.y),
            )
            points.extend(sampled if not points else sampled[1:])
        elif kind == "re":
            finish()
            rect = item[1]
            contours.append(
                (
                    [
                        (rect.x0, rect.y0),
                        (rect.x1, rect.y0),
                        (rect.x1, rect.y1),
                        (rect.x0, rect.y1),
                    ],
                    True,
                )
            )
        elif kind == "qu":
            finish()
            quad = item[1]
            contours.append(
                (
                    [
                        (quad.ul.x, quad.ul.y),
                        (quad.ur.x, quad.ur.y),
                        (quad.lr.x, quad.lr.y),
                        (quad.ll.x, quad.ll.y),
                    ],
                    True,
                )
            )
    finish()
    return contours


def _transform_points(
    points: list[Point], offset: float, rotation: fitz.Matrix
) -> tuple[Point, ...]:
    transformed = (_rotated_point(point, rotation) for point in points)
    return tuple(
        (x * PDF_POINT_TO_MM, -y * PDF_POINT_TO_MM - offset)
        for x, y in transformed
    )


def _add_path(
    result: ParsedDocument,
    drawing: dict[str, Any],
    page_offset_mm: float,
    rotation: fitz.Matrix,
) -> None:
    items = drawing.get("items", [])
    if not items:
        return
    layer = str(drawing.get("layer") or "0").strip() or "0"
    stroke, fill = _color(drawing.get("color")), _color(drawing.get("fill"))
    width = max(0.0, float(drawing.get("width") or 0.0)) * PDF_POINT_TO_MM

    for raw_points, explicit_closed in _path_contours(items):
        if len(raw_points) >= 2:
            closed = (
                explicit_closed
                or bool(drawing.get("closePath"))
                or math.dist(raw_points[0], raw_points[-1]) <= 0.05
            )
            fit_points_mm: list[Point] = []
            for index, point in enumerate(raw_points):
                rotated_point = _rotated_point(point, rotation)
                fit_points_mm.append(
                    (rotated_point[0] * PDF_POINT_TO_MM, rotated_point[1] * PDF_POINT_TO_MM)
                )
                if index + 1 < len(raw_points):
                    next_point = _rotated_point(raw_points[index + 1], rotation)
                    fit_points_mm.append(
                        (
                            (rotated_point[0] + next_point[0]) * PDF_POINT_TO_MM / 2,
                            (rotated_point[1] + next_point[1]) * PDF_POINT_TO_MM / 2,
                        )
                    )
            fit = fit_circle(fit_points_mm, CURVE_TOLERANCE_MM) if len(raw_points) >= 5 else None
            if fit is not None:
                center = (
                    fit.center[0],
                    -fit.center[1] - page_offset_mm,
                )
                if closed:
                    result.entities.append(
                        Entity("circle", layer=layer, stroke=stroke, fill=fill, width=width,
                               points=(center,), radius=fit.radius, closed=True)
                    )
                else:
                    start_angle = -fit.start_angle
                    end_angle = -fit.end_angle
                    if end_angle < start_angle:
                        start_angle, end_angle = end_angle, start_angle
                    result.entities.append(
                        Entity(
                            "arc", layer=layer, stroke=stroke, fill=fill, width=width,
                            points=(center,), radius=fit.radius,
                            start_angle=start_angle, end_angle=end_angle,
                        )
                    )
            else:
                result.entities.append(
                    Entity(
                        "polyline",
                        _transform_points(raw_points, page_offset_mm, rotation),
                        layer,
                        stroke,
                        fill,
                        width,
                        closed=closed,
                    )
                )

        if fill is not None and len(raw_points) >= 3:
            if math.dist(raw_points[0], raw_points[-1]) > 0.05:
                raw_points.append(raw_points[0])
            result.entities.append(
                Entity(
                    "hatch",
                    _transform_points(raw_points, page_offset_mm, rotation),
                    layer,
                    stroke,
                    fill,
                    width,
                    closed=True,
                )
            )


def parse_pdf(
    pdf_path: str | Path, cancel_event: Event | None = None
) -> ParsedDocument:
    """Parse vector paths, searchable text and raster placements into metric coordinates."""
    path = Path(pdf_path)
    if not path.is_file():
        raise FileNotFoundError(f"PDF file does not exist: {path}")

    parsed = ParsedDocument()
    try:
        with fitz.open(path) as document:
            if document.is_encrypted and document.needs_pass:
                raise ValueError(f"PDF is password-protected: {path.name}")
            parsed.page_count = document.page_count
            page_offset_mm = 0.0
            for page_number, page in enumerate(document):
                try:
                    if cancel_event is not None and cancel_event.is_set():
                        raise CancelledError()
                    rotation = page.rotation_matrix
                    for drawing in page.get_drawings():
                        if cancel_event is not None and cancel_event.is_set():
                            raise CancelledError()
                        _add_path(parsed, drawing, page_offset_mm, rotation)
                    image_info = {
                        entry["number"]: entry
                        for entry in page.get_image_info(xrefs=True)
                    }
                    text_traces = page.get_texttrace()
                    text_data = page.get_text("dict")
                    for block in text_data.get("blocks", []):
                        if cancel_event is not None and cancel_event.is_set():
                            raise CancelledError()
                        if block.get("type") == 1:
                            try:
                                asset = _image_asset(block)
                                parsed.images.setdefault(asset.key, asset)
                                info = image_info.get(block.get("number"), {})
                                transform = info.get("transform") or block.get("transform")
                                if transform is None:
                                    raise ValueError(
                                        "PDF raster image has no placement transform"
                                    )
                                parsed.entities.append(
                                    Entity(
                                        "image",
                                        points=_image_points(
                                            transform, page_offset_mm, rotation
                                        ),
                                        layer="0",
                                        image_key=asset.key,
                                    )
                                )
                            except Exception as exc:
                                parsed.warnings.append(
                                    f"Page {page_number + 1} image: {exc}"
                                )
                            continue
                        if block.get("type") != 0:
                            continue
                        for line in block.get("lines", []):
                            for span in line.get("spans", []):
                                if cancel_event is not None and cancel_event.is_set():
                                    raise CancelledError()
                                text = str(span.get("text", ""))
                                if not text.strip():
                                    continue
                                origin = span.get("origin")
                                if not origin:
                                    continue
                                trace = _text_trace_for_span(span, text_traces)
                                direction = (
                                    trace.get("dir")
                                    if trace is not None
                                    else line.get("dir", (1.0, 0.0))
                                )
                                point = fitz.Point(origin[0], origin[1])
                                parsed.entities.append(
                                    Entity(
                                        "text",
                                        points=(_point(point, page_offset_mm, rotation),),
                                        layer=(
                                            str(trace.get("layer") or "0")
                                            if trace is not None
                                            else "0"
                                        ),
                                        text=text,
                                        text_height=max(0.1, float(span.get("size", 2.5)) * PDF_POINT_TO_MM),
                                        rotation=_text_rotation(direction, rotation),
                                    )
                                )
                except CancelledError:
                    raise
                except Exception as exc:
                    parsed.warnings.append(f"Page {page_number + 1}: {exc}")
                page_offset_mm += float(page.rect.height) * PDF_POINT_TO_MM + 10.0
    except (fitz.FileDataError, fitz.EmptyFileError) as exc:
        raise ValueError(f"Unable to read PDF '{path.name}': {exc}") from exc
    if not parsed.entities:
        parsed.warnings.append(
            "No vector paths or searchable text found; raster content is not reconstructed."
        )
    return parsed
