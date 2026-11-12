"""DXF persistence and optional ODA File Converter integration."""

from __future__ import annotations

from concurrent.futures import CancelledError
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from threading import Event


def find_oda_converter() -> str | None:
    """Find an ODA File Converter executable on PATH or common install paths."""
    executable_names = ("ODAFileConverter.exe", "ODAFileConverter")
    for name in executable_names:
        candidate = shutil.which(name)
        if candidate:
            return candidate
    roots = (
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "ODA",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "ODA",
    )
    for root in roots:
        if root.exists():
            matches = sorted(root.glob("*/ODAFileConverter.exe"), reverse=True)
            if matches:
                return str(matches[0])
    return None


def convert_dxf_to_dwg(
    dxf_path: str | Path,
    dwg_path: str | Path,
    cancel_event: Event | None = None,
) -> Path:
    """Convert DXF using ODA CLI; raise clear errors when conversion fails."""
    source, target = Path(dxf_path).resolve(), Path(dwg_path).resolve()
    converter = find_oda_converter()
    if converter is None:
        raise FileNotFoundError(
            "ODA File Converter was not found. Install it or select DXF output."
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="vectorbridge_oda_") as temporary:
        input_dir = Path(temporary) / "in"
        output_dir = Path(temporary) / "out"
        input_dir.mkdir()
        output_dir.mkdir()
        staged = input_dir / source.name
        shutil.copy2(source, staged)
        source_assets = source.parent / f"{source.stem}_assets"
        if source_assets.is_dir():
            shutil.copytree(source_assets, input_dir / source_assets.name)
        command = [
            converter,
            str(input_dir),
            str(output_dir),
            "ACAD2018",
            "DWG",
            "0",
            "1",
        ]
        environment = os.environ.copy()
        environment.pop("QT_QPA_PLATFORM", None)
        log_path = Path(temporary) / "oda.log"
        with log_path.open("w", encoding="utf-8", errors="replace") as log:
            process = subprocess.Popen(
                command,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
                env=environment,
            )
            deadline = time.monotonic() + 180
            while process.poll() is None:
                if cancel_event is not None and cancel_event.is_set():
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                    raise CancelledError()
                if time.monotonic() >= deadline:
                    process.kill()
                    process.wait()
                    raise subprocess.TimeoutExpired(command, timeout=180)
                time.sleep(0.1)

        output = log_path.read_text(encoding="utf-8", errors="replace").strip()
        generated = output_dir / staged.with_suffix(".dwg").name
        if process.returncode != 0 or not generated.is_file():
            raise RuntimeError(
                f"ODA conversion failed (exit {process.returncode}): "
                f"{output or 'output DWG was not created'}"
            )
        target_assets = target.parent / source_assets.name
        if source_assets.is_dir() and source_assets.resolve() != target_assets.resolve():
            shutil.copytree(
                source_assets, target_assets, dirs_exist_ok=True
            )
        shutil.move(str(generated), target)
    return target
