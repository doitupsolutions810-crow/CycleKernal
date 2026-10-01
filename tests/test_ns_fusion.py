import unittest
from ns_fusion import fuse_mood, ns_fitness, promote_decision, colony_genome


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


if __name__ == "__main__":
    unittest.main()
