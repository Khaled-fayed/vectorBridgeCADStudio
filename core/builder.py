"""Build metric DXF drawings and apply layer/color mapping rules."""

from __future__ import annotations

from concurrent.futures import CancelledError
from dataclasses import dataclass
import math
from pathlib import Path
import re
import shutil
import tempfile
from threading import Event
from typing import Any

import ezdxf

from .parser import Entity, ParsedDocument, RasterImage


@dataclass(frozen=True)
class ColorRule:
    """Optional exact PDF-layer and/or RGB rule assigning a DXF color."""

    layer: str = ""
    rgb: tuple[int, int, int] | None = None
    aci: int | None = None
    true_color: tuple[int, int, int] | None = None


def _rgb_int(rgb: tuple[int, int, int]) -> int:
    red, green, blue = (max(0, min(255, int(channel))) for channel in rgb)
    return (red << 16) | (green << 8) | blue


def _safe_layer_name(name: str) -> str:
    safe = re.sub(r'[<>/\\":;?*|=,]', "_", name).strip()
    return (safe or "0")[:255]


def _entity_color(
    entity: Entity,
    rules: list[ColorRule],
    source_color: tuple[float, float, float] | None = None,
) -> dict[str, Any]:
    source = entity.stroke if source_color is None else source_color
    source_rgb = tuple(round(channel * 255) for channel in source) if source else None
    for rule in rules:
        if rule.layer and rule.layer.casefold() != entity.layer.casefold():
            continue
        if rule.rgb is not None and rule.rgb != source_rgb:
            continue
        if rule.aci is not None:
            return {"color": rule.aci}
        if rule.true_color is not None:
            return {"true_color": _rgb_int(rule.true_color)}
    if source_rgb is not None:
        return {"true_color": _rgb_int(source_rgb)}
    return {}


def _add_hatch(modelspace: Any, entity: Entity, rules: list[ColorRule]) -> None:
    hatch = modelspace.add_hatch(color=7)
    hatch.dxf.layer = _safe_layer_name(entity.layer)
    hatch.paths.add_polyline_path(entity.points, is_closed=True)
    color = _entity_color(entity, rules, source_color=entity.fill)
    if "color" in color:
        hatch.dxf.color = color["color"]
    elif "true_color" in color:
        hatch.dxf.true_color = color["true_color"]


def build_dxf(
    parsed: ParsedDocument,
    output_path: str | Path,
    color_rules: list[ColorRule] | None = None,
    cancel_event: Event | None = None,
) -> Path:
    """Write parsed geometry as AutoCAD 2018 DXF and return its path."""
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    rules = color_rules or []
    document = ezdxf.new("R2018", setup=True)
    document.units = ezdxf.units.MM
    modelspace = document.modelspace()
    asset_directory_name = f"{target.stem}_assets"
    image_definitions: dict[str, Any] = {}

    with tempfile.TemporaryDirectory(
        prefix=".vectorbridge-", dir=target.parent
    ) as temporary:
        temporary_path = Path(temporary)
        staged_assets = temporary_path / asset_directory_name

        for entity in parsed.entities:
            if cancel_event is not None and cancel_event.is_set():
                raise CancelledError()
            layer_name = _safe_layer_name(entity.layer)
            if layer_name not in document.layers:
                document.layers.new(layer_name)
            attributes = {"layer": layer_name, **_entity_color(entity, rules)}
            if entity.kind == "line" and len(entity.points) >= 2:
                modelspace.add_line(entity.points[0], entity.points[1], dxfattribs=attributes)
            elif entity.kind == "polyline" and len(entity.points) >= 2:
                modelspace.add_lwpolyline(
                    entity.points, close=entity.closed, dxfattribs=attributes
                )
            elif entity.kind == "circle":
                modelspace.add_circle(entity.points[0], entity.radius, dxfattribs=attributes)
            elif entity.kind == "arc":
                modelspace.add_arc(
                    entity.points[0],
                    entity.radius,
                    entity.start_angle % 360,
                    entity.end_angle % 360,
                    dxfattribs=attributes,
                )
            elif entity.kind == "hatch":
                _add_hatch(modelspace, entity, rules)
            elif entity.kind == "text":
                modelspace.add_text(
                    entity.text,
                    dxfattribs={
                        **attributes,
                        "height": entity.text_height,
                        "insert": entity.points[0],
                        "rotation": entity.rotation,
                    },
                )
            elif entity.kind == "image":
                asset = parsed.images.get(entity.image_key)
                if asset is None:
                    raise ValueError(
                        f"Image entity references missing raster asset: {entity.image_key}"
                    )
                if len(entity.points) != 3:
                    raise ValueError("Image placement requires top-left, top-right and bottom-left.")
                image_def = image_definitions.get(asset.key)
                filename = f"image_{asset.key[:20]}.png"
                if image_def is None:
                    staged_assets.mkdir(exist_ok=True)
                    (staged_assets / filename).write_bytes(asset.data)
                    image_def = document.add_image_def(
                        f"{asset_directory_name}/{filename}",
                        size_in_pixel=(asset.width, asset.height),
                        name=f"image_{asset.key[:20]}",
                    )
                    image_definitions[asset.key] = image_def

                top_left, top_right, bottom_left = entity.points
                u_pixel = (
                    (top_right[0] - top_left[0]) / asset.width,
                    (top_right[1] - top_left[1]) / asset.width,
                )
                v_pixel = (
                    (top_left[0] - bottom_left[0]) / asset.height,
                    (top_left[1] - bottom_left[1]) / asset.height,
                )
                width = (u_pixel[0] ** 2 + u_pixel[1] ** 2) ** 0.5 * asset.width
                height = (v_pixel[0] ** 2 + v_pixel[1] ** 2) ** 0.5 * asset.height
                rotation = math.degrees(math.atan2(u_pixel[1], u_pixel[0]))
                image = modelspace.add_image(
                    image_def,
                    insert=bottom_left,
                    size_in_units=(width, height),
                    rotation=rotation,
                    dxfattribs=attributes,
                )
                image.dxf.u_pixel = (u_pixel[0], u_pixel[1], 0.0)
                image.dxf.v_pixel = (v_pixel[0], v_pixel[1], 0.0)

        if cancel_event is not None and cancel_event.is_set():
            raise CancelledError()
        staged_dxf = temporary_path / target.name
        document.saveas(staged_dxf)
        if staged_assets.exists():
            if cancel_event is not None and cancel_event.is_set():
                raise CancelledError()
            shutil.copytree(
                staged_assets,
                target.parent / asset_directory_name,
                dirs_exist_ok=True,
            )
        if cancel_event is not None and cancel_event.is_set():
            raise CancelledError()
        staged_dxf.replace(target)
    return target
