import unittest
from ns_fusion import (apply_fusion, find_promotion_collisions, fusion_evidence, fuse_mood, ns_components, ns_fitness, neural_score, promote_decision, colony_genome, symbolic_score)


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

    def test_equal_geometric_mean_preserves_distinct_channel_pairs(self):
        left = fusion_evidence(0.9, 0.4)
        right = fusion_evidence(0.6, 0.6)
        self.assertAlmostEqual(left["ns_fitness"], 0.6)
        self.assertAlmostEqual(right["ns_fitness"], 0.6)
        self.assertAlmostEqual(left["channel_gap"], 0.5)
        self.assertAlmostEqual(right["channel_gap"], 0.0)
        # The signed delta and scalar are sufficient to recover the ordered pair.
        sigma = left["ns_fitness"]
        delta = left["channel_delta"]
        total = (delta * delta + 4 * sigma * sigma) ** 0.5
        self.assertAlmostEqual((total + delta) / 2, 0.9)
        self.assertAlmostEqual((total - delta) / 2, 0.4)

    def test_four_channel_threshold_distances_are_emitted(self):
        evidence = fusion_evidence(0.9, 0.4)
        margins = evidence["threshold_distances"]
        self.assertEqual(
            set(margins),
            {"symbolic_to_promote", "symbolic_to_demote", "neural_to_promote", "neural_to_demote"},
        )
        self.assertAlmostEqual(margins["symbolic_to_promote"], 0.9 - 0.62)
        self.assertAlmostEqual(margins["neural_to_demote"], 0.4 - 0.28)

    def test_apply_fusion_uses_nested_belief_and_resources(self):
        belief = {"truth": 0.9}
        resources = {"attention": 120, "compute": 30, "memory_nodes": 6}
        metrics = {"Core": 0.8, "L5": 0.1, "L2": 0.1, "belief": belief, "resources": resources}
        result = apply_fusion("neutral", metrics)
        expected = fusion_evidence(
            symbolic_score(belief, resources),
            neural_score(0.8, 0.1, 0.1),
        )
        self.assertAlmostEqual(result["symbolic_score"], expected["symbolic_score"])
        self.assertAlmostEqual(result["neural_score"], expected["neural_score"])
        self.assertEqual(set(result["threshold_distances"]), set(expected["threshold_distances"]))
        self.assertEqual(result["channel_provenance"]["symbolic"]["source"], "belief+resources")
        self.assertTrue(result["channel_provenance"]["symbolic"]["complete"])

    def test_apply_fusion_does_not_suppress_demotion(self):
        result = apply_fusion(
            "survival",
            {
                "Core": 0.0,
                "L5": 1.0,
                "L2": 0.0,
                "belief": {"truth": 0.0},
                "resources": {"attention": 0, "compute": 0, "memory_nodes": 0},
            },
            colony={"promoted": 1},
        )
        self.assertEqual(result["promote"]["action"], "demote")

    def test_promotion_collision_finds_same_scalar_different_channels(self):
        sigma = 0.58
        fused = round(fuse_mood(sigma, "convergent"), 4)
        records = [
            {"event_id": "a", "action": "promote", "mood_dot": fused, "symbolic_score": 1.0, "neural_score": sigma * sigma},
            {"event_id": "b", "action": "promote", "mood_dot": fused, "symbolic_score": sigma, "neural_score": sigma},
        ]
        collisions = find_promotion_collisions(records)
        self.assertEqual(len(collisions), 1)
        self.assertGreater(collisions[0]["symbolic_delta"], 0.3)

    def test_genome_stable(self):
        self.assertEqual(colony_genome(["b", "a"]), colony_genome(["a", "b"]))
        self.assertTrue(colony_genome(["civ_0"]).startswith("gn-"))


if __name__ == "__main__":
    unittest.main()
