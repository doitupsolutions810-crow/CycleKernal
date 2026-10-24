import unittest

from ns_fusion import (
    apply_fusion,
    fitness_channels,
    fuse_mood,
    neural_score,
    ns_fitness,
    promote_decision,
    summarize_fitness_channels,
    symbolic_score,
)


class FusionStressTests(unittest.TestCase):
    def test_every_apply_fusion_result_has_stress_and_companion_receipts(self):
        result = apply_fusion("neutral", {"Core": 0.6, "L5": 0.2, "L2": 0.04})
        self.assertEqual(result["stress_residual"], 0.0)
        self.assertEqual(result["stress_residual_normalized"], 0.0)
        self.assertEqual(result["descent_schema"], "great-scale.descent/v0.4.2")
        evidence = result["fitness_evidence"]
        self.assertEqual(evidence["schema"], "cyclekernel.fusion-evidence/v1")
        self.assertIn("symbolic_score", evidence)
        self.assertIn("neural_score", evidence)
        self.assertIn("signed_eta", evidence)
        self.assertIn("symbolic_neural_ratio", evidence)
        self.assertEqual(evidence["descent_source"], "default_zero")
        self.assertEqual(
            set(evidence["threshold_margins"]),
            {"promote", "demote", "convergent_label", "survival_label"},
        )

    def test_residual_is_normalized_and_changes_entropy(self):
        base = {"Core": 0.6, "L5": 0.2, "L2": 0.04}
        calm = apply_fusion("neutral", {**base, "stress_residual": 0.0})
        stressed = apply_fusion("neutral", {**base, "stress_residual": 7.0})
        self.assertEqual(stressed["stress_residual_normalized"], 1.0)
        self.assertAlmostEqual(stressed["neural_entropy_used"], 0.55)
        self.assertLess(stressed["ns_fitness"], calm["ns_fitness"])
        self.assertEqual(stressed["fitness_evidence"]["descent_source"], "provided")

    def test_out_of_scope_residual_fails_closed(self):
        with self.assertRaises(ValueError):
            apply_fusion("neutral", {"stress_residual": 8.9})

    def test_zero_stress_preserves_existing_entropy_semantics(self):
        expected = ns_fitness(core=0.6, entropy=0.2, coupling=0.04)
        result = apply_fusion("neutral", {"Core": 0.6, "L5": 0.2, "L2": 0.04})
        self.assertAlmostEqual(result["ns_fitness"], expected, places=4)

    def test_equal_geometric_mean_can_hide_different_channel_states(self):
        # sqrt(.9*.4) == sqrt(.6*.6): the scalar projection is not injective.
        unbalanced = summarize_fitness_channels(0.9, 0.4)
        balanced = summarize_fitness_channels(0.6, 0.6)
        self.assertAlmostEqual(unbalanced["ns_fitness"], balanced["ns_fitness"])
        self.assertAlmostEqual(unbalanced["ns_fitness"], 0.6)
        self.assertAlmostEqual(unbalanced["symbolic_neural_ratio"], 2.25)
        self.assertAlmostEqual(balanced["symbolic_neural_ratio"], 1.0)
        self.assertAlmostEqual(unbalanced["signed_eta"], 0.5)
        self.assertAlmostEqual(balanced["signed_eta"], 0.0)
        # The scalar-based decision is identical for identical mood, despite the
        # different channel geometry retained by the companion output.
        self.assertAlmostEqual(
            fuse_mood(unbalanced["ns_fitness"], "neutral"),
            fuse_mood(balanced["ns_fitness"], "neutral"),
        )

    def test_zero_neural_channel_has_explicit_undefined_ratio(self):
        state = summarize_fitness_channels(0.7, 0.0)
        self.assertFalse(state["ratio_defined"])
        self.assertIsNone(state["symbolic_neural_ratio"])
        self.assertEqual(state["ns_fitness"], 0.0)

    def test_explicit_symbolic_inputs_are_marked(self):
        belief = {"truth": 0.8, "deception": 0.2}
        resources = {"attention": 100, "compute": 30, "memory_nodes": 5}
        channels = fitness_channels(
            belief=belief, resources=resources, core=0.8, entropy=0.2, coupling=0.1
        )
        self.assertEqual(channels["belief_source"], "provided")
        self.assertEqual(channels["resource_source"], "provided")
        self.assertAlmostEqual(channels["symbolic_score"], symbolic_score(belief, resources))
        self.assertAlmostEqual(channels["neural_score"], neural_score(0.8, 0.2, 0.1))

    def test_promotion_and_demotion_threshold_semantics(self):
        self.assertEqual(promote_decision(0.62)["action"], "promote")
        self.assertEqual(promote_decision(0.6199)["action"], "hold")
        self.assertEqual(promote_decision(0.28, already_promoted=True)["action"], "hold")
        self.assertEqual(promote_decision(0.2799, already_promoted=True)["action"], "demote")

    def test_nonfinite_score_input_fails_closed(self):
        with self.assertRaises(ValueError):
            neural_score(float("nan"), 0.2, 0.1)


if __name__ == "__main__":
    unittest.main()
