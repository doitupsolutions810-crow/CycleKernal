import unittest

from ns_fusion import apply_fusion, ns_fitness


class FusionStressTests(unittest.TestCase):
    def test_every_apply_fusion_result_has_stress_receipt_fields(self):
        result = apply_fusion("neutral", {"Core": 0.6, "L5": 0.2, "L2": 0.04})
        self.assertIn("stress_residual", result)
        self.assertIn("stress_residual_normalized", result)
        self.assertIn("neural_entropy_used", result)
        self.assertEqual(result["stress_residual"], 0.0)
        self.assertEqual(result["stress_residual_normalized"], 0.0)
        self.assertEqual(result["descent_schema"], "great-scale.descent/v0.4.2")

    def test_residual_is_normalized_and_changes_entropy(self):
        base = {"Core": 0.6, "L5": 0.2, "L2": 0.04}
        calm = apply_fusion("neutral", {**base, "stress_residual": 0.0})
        stressed = apply_fusion("neutral", {**base, "stress_residual": 7.0})
        self.assertEqual(stressed["stress_residual_normalized"], 1.0)
        self.assertAlmostEqual(stressed["neural_entropy_used"], 0.55)
        self.assertLess(stressed["ns_fitness"], calm["ns_fitness"])

    def test_out_of_scope_residual_fails_closed(self):
        with self.assertRaises(ValueError):
            apply_fusion("neutral", {"stress_residual": 8.9})

    def test_zero_stress_preserves_existing_entropy_semantics(self):
        expected = ns_fitness(core=0.6, entropy=0.2, coupling=0.04)
        result = apply_fusion("neutral", {"Core": 0.6, "L5": 0.2, "L2": 0.04})
        self.assertAlmostEqual(result["ns_fitness"], expected, places=4)


if __name__ == "__main__":
    unittest.main()
