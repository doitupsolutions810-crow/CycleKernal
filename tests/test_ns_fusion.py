import unittest

from backend.ns_fusion import (
    apply_fusion,
    colony_genome,
    fitness_channels,
    fuse_mood,
    neural_score,
    ns_fitness,
    promote_decision,
    summarize_fitness_channels,
    symbolic_score,
)


class FusionTests(unittest.TestCase):
    def test_geometric_mean_requires_both_sides(self):
        weak = ns_fitness(
            belief={"truth": 0.1},
            resources={"attention": 0, "compute": 0, "memory_nodes": 0},
            core=0.9,
            entropy=0.1,
            coupling=0.1,
        )
        strong = ns_fitness(
            belief={"truth": 0.9},
            resources={"attention": 120, "compute": 30, "memory_nodes": 6},
            core=0.8,
            entropy=0.1,
            coupling=0.1,
        )
        self.assertLess(weak, strong)
        self.assertGreaterEqual(strong, 0.62)

    def test_mood_dot_weights(self):
        fused = fuse_mood(1.0, "neutral")
        self.assertAlmostEqual(fused, 0.65 * 1.0 + 0.35 * 0.50)

    def test_promote_gate(self):
        self.assertEqual(promote_decision(0.70)["action"], "promote")
        self.assertEqual(promote_decision(0.40)["action"], "hold")
        self.assertEqual(promote_decision(0.20, already_promoted=True)["action"], "demote")

    def test_genome_stable(self):
        self.assertEqual(colony_genome(["b", "a"]), colony_genome(["a", "b"]))
        self.assertTrue(colony_genome(["civ_0"]).startswith("gn-"))

    def test_equal_geometric_mean_can_hide_different_channel_states(self):
        # sqrt(.9*.4) == sqrt(.6*.6), so ns_fitness alone cannot identify the pair.
        left = summarize_fitness_channels(0.9, 0.4)
        balanced = summarize_fitness_channels(0.6, 0.6)
        self.assertAlmostEqual(left["ns_fitness"], balanced["ns_fitness"])
        self.assertAlmostEqual(left["ns_fitness"], 0.6)
        self.assertAlmostEqual(left["symbolic_neural_ratio"], 2.25)
        self.assertAlmostEqual(balanced["symbolic_neural_ratio"], 1.0)
        self.assertAlmostEqual(left["signed_eta"], 0.5)
        self.assertAlmostEqual(balanced["signed_eta"], 0.0)

    def test_zero_neural_channel_is_explicit_not_infinite(self):
        state = summarize_fitness_channels(0.7, 0.0)
        self.assertFalse(state["ratio_defined"])
        self.assertIsNone(state["symbolic_neural_ratio"])
        self.assertAlmostEqual(state["ns_fitness"], 0.0)

    def test_apply_fusion_emits_all_four_decision_margins(self):
        result = apply_fusion("neutral", {"Core": 0.5, "L5": 0.4, "L2": 0.1})
        evidence = result["fitness_evidence"]
        expected = {"promote", "demote", "convergent_label", "survival_label"}
        self.assertEqual(set(evidence["threshold_distances"]), expected)
        self.assertEqual(set(evidence["threshold_margins"]), expected)
        self.assertEqual(evidence["schema"], "cyclekernel.fusion-evidence/v1")
        self.assertEqual(evidence["belief_source"], "default")
        self.assertEqual(evidence["resource_source"], "default")
        self.assertTrue(all(value >= 0 for value in evidence["threshold_distances"].values()))

    def test_apply_fusion_marks_explicit_symbolic_inputs(self):
        belief = {"truth": 0.8, "deception": 0.2}
        resources = {"attention": 100, "compute": 30, "memory_nodes": 5}
        result = apply_fusion(
            "convergent",
            {
                "Core": 0.8,
                "L5": 0.2,
                "L2": 0.1,
                "belief": belief,
                "resources": resources,
            },
        )
        evidence = result["fitness_evidence"]
        self.assertEqual(evidence["belief_source"], "provided")
        self.assertEqual(evidence["resource_source"], "provided")
        self.assertAlmostEqual(evidence["symbolic_score"], symbolic_score(belief, resources), places=6)
        self.assertAlmostEqual(evidence["neural_score"], neural_score(0.8, 0.2, 0.1), places=6)


if __name__ == "__main__":
    unittest.main()
