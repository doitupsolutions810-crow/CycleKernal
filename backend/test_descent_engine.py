import unittest

from descent_engine import (
    DescentEngine,
    entropy_with_stress,
    involution,
    involution_identity,
    normalized_stress_residual,
    stress_residual,
)


class DescentEngineTests(unittest.TestCase):
    def test_involution_identity_on_37_points(self):
        points = [9.0 * i / 36.0 for i in range(37)]
        self.assertTrue(all(involution_identity(x) for x in points))

    def test_nine_and_zero_share_circle_image(self):
        self.assertAlmostEqual(involution(0.0), 0.0)
        self.assertAlmostEqual(involution(9.0), 0.0)
        self.assertTrue(involution_identity(9.0))

    def test_residual_halves_each_tick_on_configured_orbit(self):
        engine = DescentEngine(start=1.0, k=0.5)
        first = engine.tick()["residual"]
        second = engine.tick()["residual"]
        third = engine.tick()["residual"]
        self.assertAlmostEqual(first, 3.5)
        self.assertAlmostEqual(second, first / 2.0)
        self.assertAlmostEqual(third, second / 2.0)

    def test_converges_to_fixed_point(self):
        engine = DescentEngine(start=1.0, k=0.5)
        for _ in range(40):
            engine.tick()
        self.assertAlmostEqual(engine.x, 4.5, places=6)
        self.assertTrue(engine.snapshot()["nearFixed"])

    def test_snapshot_schema_and_provenance(self):
        engine = DescentEngine()
        engine.tick()
        snap = engine.snapshot(running=True)
        self.assertEqual(snap["schema"], "great-scale.descent/v0.4.2")
        self.assertIn("scale.js@", snap["sourceVersion"])
        self.assertEqual(snap["t"], 1)
        self.assertTrue(snap["running"])
        self.assertEqual(snap["historyLen"], 1)
        self.assertIn("residualNormalized", snap)

    def test_history_is_bounded(self):
        engine = DescentEngine(max_history=3)
        for _ in range(5):
            engine.tick()
        self.assertEqual(engine.snapshot()["historyLen"], 3)
        self.assertEqual(engine.snapshot()["last"]["t"], 5)

    def test_residual_normalization_rejects_seam_scope_violation(self):
        self.assertEqual(normalized_stress_residual(7.0), 1.0)
        # The raw residual is not bounded by 7 near the continuous 0/9 seam.
        with self.assertRaises(ValueError):
            normalized_stress_residual(stress_residual(0.01))

    def test_contraction_factor_and_start_are_validated(self):
        with self.assertRaises(ValueError):
            DescentEngine(start=0.0)
        with self.assertRaises(ValueError):
            DescentEngine(k=1.0)

    def test_stress_enters_entropy_path_and_remains_bounded(self):
        self.assertAlmostEqual(entropy_with_stress(0.15, 0.0), 0.15)
        self.assertAlmostEqual(entropy_with_stress(0.15, 7.0), 0.50)
        self.assertEqual(entropy_with_stress(0.65, 7.0), 1.0)


if __name__ == "__main__":
    unittest.main()
