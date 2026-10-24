import unittest

from ns_fusion import (
    apply_fusion,
    build_fusion_identity_state,
    fitness_state_id,
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
        self.assertEqual(result["fusion_state_id"], evidence["fusion_state_id"])
        self.assertTrue(result["genome_id"].startswith("gn-"))
        self.assertTrue(result["fusion_state_id"].startswith("fs-"))
        self.assertEqual(len(result["fusion_state_id"]), 67)
        self.assertEqual(evidence["mood_input"], "neutral")
        self.assertEqual(evidence["mood_output"], "neutral")
        self.assertFalse(evidence["mood_label_projected"])
        self.assertEqual(evidence["genome_state_schema"], result["genome_state_schema"])
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

    def test_identical_scalar_can_have_distinct_state_fingerprints(self):
        # sqrt(.9*.4) == sqrt(.6*.6) = .6; mood fusion also sees .565
        # for both under the same neutral mood. The companion state ID must
        # still distinguish the two underlying channel pairs.
        left = summarize_fitness_channels(0.9, 0.4)
        right = summarize_fitness_channels(0.6, 0.6)
        fused = fuse_mood(0.6, "neutral")
        common = {
            "mood_input": "neutral",
            "mood_output": "neutral",
            "core": 0.5,
            "base_entropy": 0.5,
            "neural_entropy_used": 0.5,
            "coupling": 0.0,
            "belief": {"truth": 0.5},
            "resources": {"attention": 50, "compute": 20, "memory_nodes": 1},
            "stress_residual": 0.0,
            "descent_source": "default_zero",
            "metric_source": "unknown",
        }
        left_state = build_fusion_identity_state(**common, channels=left, fused=fused)
        right_state = build_fusion_identity_state(**common, channels=right, fused=fused)
        self.assertAlmostEqual(left["ns_fitness"], right["ns_fitness"])
        self.assertAlmostEqual(fuse_mood(left["ns_fitness"], "neutral"), fused)
        self.assertAlmostEqual(fuse_mood(right["ns_fitness"], "neutral"), fused)
        self.assertNotEqual(fitness_state_id(left_state), fitness_state_id(right_state))
        self.assertEqual(fitness_state_id(left_state), fitness_state_id(left_state))

    def test_source_change_changes_full_fingerprint_without_changing_legacy_score(self):
        channels = summarize_fitness_channels(0.6, 0.6)
        common = {
            "mood_input": "neutral",
            "mood_output": "neutral",
            "channels": channels,
            "fused": fuse_mood(channels["ns_fitness"], "neutral"),
            "core": 0.6,
            "base_entropy": 0.4,
            "neural_entropy_used": 0.4,
            "coupling": 0.02,
            "belief": {"truth": 0.6},
            "resources": {"attention": 90, "compute": 20, "memory_nodes": 2},
            "stress_residual": 0.0,
            "descent_source": "default_zero",
        }
        relay = build_fusion_identity_state(**common, metric_source="relay")
        synthetic = build_fusion_identity_state(**common, metric_source="synthetic")
        self.assertEqual(relay["ns_fitness"], synthetic["ns_fitness"])
        self.assertNotEqual(fitness_state_id(relay), fitness_state_id(synthetic))

    def test_mood_threshold_projection_is_an_explicit_companion_event(self):
        high = apply_fusion(
            "neutral",
            {
                "Core": 1.0, "L5": 0.0, "L2": 0.2,
                "belief": {"truth": 1.0},
                "resources": {"attention": 150, "compute": 40, "memory_nodes": 8},
            },
        )
        self.assertEqual(high["mood"], "convergent")
        self.assertTrue(high["fitness_evidence"]["mood_label_projected"])
        self.assertEqual(high["fitness_evidence"]["label_projection_threshold"], "convergent_label")
        low = apply_fusion(
            "neutral",
            {
                "Core": 0.0, "L5": 1.0, "L2": 0.0,
                "belief": {"truth": 0.0},
                "resources": {"attention": 0, "compute": 0, "memory_nodes": 0},
            },
        )
        self.assertEqual(low["mood"], "survival")
        self.assertTrue(low["fitness_evidence"]["mood_label_projected"])
        self.assertEqual(low["fitness_evidence"]["label_projection_threshold"], "survival_label")

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


    def test_fusion_state_witness_recomputes_fingerprint(self):
        result = apply_fusion("neutral", {"Core": 0.6, "L5": 0.2, "L2": 0.04})
        evidence = result["fitness_evidence"]
        witness = evidence["fusion_state_witness"]
        self.assertIsInstance(witness, dict)
        self.assertEqual(fitness_state_id(witness), result["fusion_state_id"])
        self.assertEqual(evidence["fusion_state_id"], result["fusion_state_id"])

    def test_invalid_symbolic_inputs_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "belief must be a mapping"):
            fitness_channels(belief=[], resources={"attention": 50}, core=0.5, entropy=0.2, coupling=0.1)
        with self.assertRaisesRegex(ValueError, "resources must be a mapping"):
            fitness_channels(belief={"truth": 0.5}, resources=[], core=0.5, entropy=0.2, coupling=0.1)
        with self.assertRaisesRegex(ValueError, "belief must be a mapping"):
            apply_fusion("neutral", {"Core": 0.5, "belief": []})
        with self.assertRaisesRegex(ValueError, "belief.truth must be finite and in"):
            fitness_channels(
                belief={"truth": 1.01},
                resources={"attention": 50, "compute": 20, "memory_nodes": 1},
                core=0.5, entropy=0.2, coupling=0.1,
            )
        with self.assertRaisesRegex(ValueError, "belief.deception must be finite and in"):
            fitness_channels(
                belief={"truth": 0.5, "deception": float("nan")},
                resources={"attention": 50, "compute": 20, "memory_nodes": 1},
                core=0.5, entropy=0.2, coupling=0.1,
            )
        with self.assertRaisesRegex(ValueError, "resources.attention must be finite and nonnegative"):
            fitness_channels(
                belief={"truth": 0.5},
                resources={"attention": -1, "compute": 20, "memory_nodes": 1},
                core=0.5, entropy=0.2, coupling=0.1,
            )
        with self.assertRaisesRegex(ValueError, "resources.compute must be finite and nonnegative"):
            fitness_channels(
                belief={"truth": 0.5},
                resources={"attention": 50, "compute": float("inf"), "memory_nodes": 1},
                core=0.5, entropy=0.2, coupling=0.1,
            )
        with self.assertRaisesRegex(ValueError, "resources.memory_nodes must be finite and nonnegative"):
            fitness_channels(
                belief={"truth": 0.5},
                resources={"attention": 50, "compute": 20, "memory_nodes": -0.1},
                core=0.5, entropy=0.2, coupling=0.1,
            )

    def test_nonfinite_score_input_fails_closed(self):
        with self.assertRaises(ValueError):
            neural_score(float("nan"), 0.2, 0.1)


if __name__ == "__main__":
    unittest.main()
