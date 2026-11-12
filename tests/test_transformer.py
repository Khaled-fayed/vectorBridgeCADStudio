import math
import unittest

from core.transformer import fit_circle, sample_cubic_bezier


class TransformerTests(unittest.TestCase):
    def test_fit_circle_recognizes_closed_circle(self):
        points = [
            (10 * math.cos(index * math.tau / 64), 10 * math.sin(index * math.tau / 64))
            for index in range(65)
        ]
        fit = fit_circle(points, 0.01)
        self.assertIsNotNone(fit)
        assert fit is not None
        self.assertTrue(fit.closed)
        self.assertAlmostEqual(fit.radius, 10.0, places=5)

    def test_fit_circle_rejects_non_circular_shape(self):
        fit = fit_circle([(0, 0), (1, 0), (2, 0), (2, 1), (0, 2)], 0.01)
        self.assertIsNone(fit)

    def test_bezier_samples_include_endpoints(self):
        points = sample_cubic_bezier((0, 0), (1, 0), (1, 1), (2, 1), steps=8)
        self.assertEqual(len(points), 9)
        self.assertEqual(points[0], (0, 0))
        self.assertEqual(points[-1], (2, 1))


if __name__ == "__main__":
    unittest.main()
