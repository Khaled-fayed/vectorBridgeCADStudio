import math
from concurrent.futures import CancelledError
import tempfile
from threading import Event, Thread
import unittest
from pathlib import Path
from unittest.mock import patch

import ezdxf
import fitz
from PyQt6.QtCore import Qt

from core.builder import ColorRule, build_dxf
from core.parser import parse_pdf
from ui.main_window import ConversionWorker, Job


class ConversionTests(unittest.TestCase):
    def test_pdf_raster_images_are_written_as_referenced_dxf_images(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "raster.pdf"
            target = root / "raster.dxf"
            pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 8, 4), True)
            pixmap.set_rect(pixmap.irect, (255, 0, 0, 128))
            image_data = pixmap.tobytes("png")
            document = fitz.open()
            page = document.new_page(width=200, height=100)
            page.insert_image(fitz.Rect(20, 30, 100, 70), stream=image_data)
            page.insert_image(fitz.Rect(110, 20, 150, 60), stream=image_data)
            page.set_rotation(90)
            document.save(source)
            document.close()

            parsed = parse_pdf(source)
            image_entities = [
                entity for entity in parsed.entities if entity.kind == "image"
            ]
            self.assertEqual(len(image_entities), 2)
            self.assertEqual(len(parsed.images), 1)

            build_dxf(parsed, target)
            result = ezdxf.readfile(target)
            cad_images = [
                entity for entity in result.modelspace()
                if entity.dxftype() == "IMAGE"
            ]
            self.assertEqual(len(cad_images), 2)
            definition = result.objects.query("IMAGEDEF").first
            image_file = target.parent / definition.dxf.filename.replace(
                "/", "\\"
            )
            self.assertTrue(image_file.is_file())
            extracted = fitz.Pixmap(str(image_file))
            self.assertEqual((extracted.width, extracted.height), (8, 4))
            self.assertTrue(extracted.alpha)

            expected_bottom_left = image_entities[0].points[2]
            self.assertAlmostEqual(
                cad_images[0].dxf.insert.x, expected_bottom_left[0], places=5
            )
            self.assertAlmostEqual(
                cad_images[0].dxf.insert.y, expected_bottom_left[1], places=5
            )
            self.assertEqual(result.units, ezdxf.units.MM)

    def test_native_pdf_text_is_exported_as_text_not_vector_geometry(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "native-text.pdf"
            target = Path(temporary) / "native-text.dxf"
            document = fitz.open()
            page = document.new_page()
            page.insert_text((50, 80), "Native text", fontsize=12)
            document.save(source)
            document.close()

            parsed = parse_pdf(source)
            self.assertEqual([entity.kind for entity in parsed.entities], ["text"])
            build_dxf(parsed, target)
            result = ezdxf.readfile(target)
            self.assertEqual(
                [entity.dxftype() for entity in result.modelspace()], ["TEXT"]
            )

    def test_ocg_layers_and_pdf_page_and_text_rotation_are_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "layers-rotation.pdf"
            target = root / "layers-rotation.dxf"
            document = fitz.open()
            page = document.new_page(width=400, height=300)
            wall_layer = document.add_ocg("A-Walls")
            text_layer = document.add_ocg("A-Labels")
            page.draw_line((20, 30), (120, 80), color=(0, 0, 0), oc=wall_layer)
            page.insert_text((200, 150), "Page rotated", rotate=90, oc=text_layer)
            page.set_rotation(90)

            second_page = document.new_page(width=400, height=300)
            second_page.insert_text((100, 100), "Vertical", rotate=90, oc=text_layer)
            document.save(source)
            document.close()

            parsed = parse_pdf(source)
            wall = next(entity for entity in parsed.entities if entity.layer == "A-Walls")
            self.assertAlmostEqual(wall.points[0][0], 270 * 25.4 / 72, places=4)
            self.assertAlmostEqual(wall.points[0][1], -20 * 25.4 / 72, places=4)
            texts = {entity.text: entity for entity in parsed.entities if entity.kind == "text"}
            self.assertEqual(texts["Page rotated"].layer, "A-Labels")
            self.assertAlmostEqual(texts["Page rotated"].rotation, 0, places=4)
            self.assertAlmostEqual(texts["Vertical"].rotation, 90, places=4)

            build_dxf(parsed, target)
            result = ezdxf.readfile(target)
            self.assertIn("A-Walls", result.layers)
            self.assertIn("A-Labels", result.layers)
            cad_text = next(
                entity
                for entity in result.modelspace()
                if entity.dxftype() == "TEXT" and entity.dxf.text == "Vertical"
            )
            self.assertAlmostEqual(cad_text.dxf.rotation, 90, places=4)

    def test_worker_abort_marks_pending_jobs_cancelled(self):
        worker = ConversionWorker(
            [
                Job(0, "first.pdf", ".dxf", ".", "first"),
                Job(1, "second.pdf", ".dxf", ".", "second"),
            ],
            [],
        )
        statuses: list[tuple[int, str]] = []
        finished: list[bool] = []
        worker.status.connect(lambda row, status: statuses.append((row, status)))
        worker.finished.connect(lambda: finished.append(True))
        worker.cancel()
        worker.run()
        self.assertEqual(statuses, [(0, "Cancelled"), (1, "Cancelled")])
        self.assertEqual(finished, [True])

    def test_worker_abort_interrupts_an_active_job(self):
        worker = ConversionWorker([Job(0, "active.pdf", ".dxf", ".", "active")], [])
        parse_started = Event()
        statuses: list[str] = []

        def record_status(_row: int, status: str) -> None:
            statuses.append(status)

        worker.status.connect(
            record_status, Qt.ConnectionType.DirectConnection
        )

        def wait_for_abort(_source, cancel_event):
            parse_started.set()
            self.assertTrue(cancel_event.wait(2))
            raise CancelledError()

        with patch("ui.main_window.parse_pdf", side_effect=wait_for_abort):
            thread = Thread(target=worker.run)
            thread.start()
            self.assertTrue(parse_started.wait(1))
            worker.cancel()
            thread.join(2)

        self.assertFalse(thread.is_alive())
        self.assertEqual(statuses, ["Processing", "Cancelled"])

    def test_open_circular_path_is_written_as_correctly_oriented_arc(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "arc.pdf"
            target = root / "arc.dxf"
            document = fitz.open()
            page = document.new_page(width=300, height=300)
            points = [
                (100 + 30 * math.cos(angle), 100 + 30 * math.sin(angle))
                for angle in (
                    math.pi / 2 - index * math.pi / 64 for index in range(33)
                )
            ]
            page.draw_polyline(points, color=(0, 0, 0), width=1)
            document.save(source)
            document.close()

            parsed = parse_pdf(source)
            arc = next(entity for entity in parsed.entities if entity.kind == "arc")
            build_dxf(parsed, target)
            result = ezdxf.readfile(target)
            cad_arc = next(entity for entity in result.modelspace() if entity.dxftype() == "ARC")
            self.assertAlmostEqual(cad_arc.dxf.start_angle, 270.0, places=2)
            self.assertLess(min(cad_arc.dxf.end_angle, 360 - cad_arc.dxf.end_angle), 0.02)
            self.assertAlmostEqual(cad_arc.dxf.radius, arc.radius, places=5)

    def test_coarse_polygon_is_not_promoted_to_circle(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "polygon.pdf"
            document = fitz.open()
            page = document.new_page(width=300, height=300)
            points = [
                (100 + 30 * math.cos(index * math.tau / 5),
                 100 + 30 * math.sin(index * math.tau / 5))
                for index in range(6)
            ]
            page.draw_polyline(points, color=(0, 0, 0), width=1)
            document.save(source)
            document.close()

            parsed = parse_pdf(source)
            self.assertNotIn("circle", {entity.kind for entity in parsed.entities})
            self.assertIn("polyline", {entity.kind for entity in parsed.entities})

    def test_pdf_vectors_text_hatch_and_color_mapping_round_trip(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "drawing.pdf"
            target = root / "drawing.dxf"
            document = fitz.open()
            page = document.new_page(width=300, height=300)
            page.draw_circle((100, 100), 30, color=(1, 0, 0), width=1)
            page.draw_rect((20, 20, 60, 60), color=(0, 0, 1), fill=(0, 1, 0))
            page.insert_text((80, 200), "CAD label", fontsize=12)
            document.save(source)
            document.close()

            parsed = parse_pdf(source)
            kinds = {entity.kind for entity in parsed.entities}
            self.assertIn("circle", kinds)
            self.assertIn("hatch", kinds)
            self.assertIn("text", kinds)
            build_dxf(
                parsed,
                target,
                [
                    ColorRule(rgb=(255, 0, 0), aci=1),
                    ColorRule(rgb=(0, 255, 0), true_color=(17, 34, 51)),
                ],
            )

            result = ezdxf.readfile(target)
            types = [entity.dxftype() for entity in result.modelspace()]
            self.assertIn("CIRCLE", types)
            self.assertIn("HATCH", types)
            self.assertIn("TEXT", types)
            self.assertEqual(result.units, ezdxf.units.MM)
            circle = next(entity for entity in result.modelspace() if entity.dxftype() == "CIRCLE")
            self.assertEqual(circle.dxf.color, 1)
            hatch = next(entity for entity in result.modelspace() if entity.dxftype() == "HATCH")
            self.assertEqual(hatch.dxf.true_color, 0x112233)


if __name__ == "__main__":
    unittest.main()
