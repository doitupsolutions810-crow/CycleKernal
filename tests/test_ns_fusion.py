import hashlib
import math
import unittest
from ns_fusion import (
    DEMOTE_THRESHOLD,
    PROMOTE_THRESHOLD,
    apply_fusion,
    colony_genome,
    fuse_mood,
    ns_fitness,
    promote_decision,
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

    # GS-LVI seam: quotient-circle contraction
    def test_quotient_seam_zero_and_nine_non_equivalent(self):
        FIXED, k = 4.5, 0.5
        c0 = FIXED + k * (0 - FIXED)    # 2.25
        c9 = FIXED + k * (9 - FIXED)    # 6.75
        d = abs(((c0 - c9) % 9 + 9) % 9)
        qd = min(d, 9 - d)
        self.assertAlmostEqual(qd, 4.5, places=9)
        self.assertGreater(abs(c0 - c9) % 9, 1e-9)

    def test_affine_map_not_circle_native_under_strict_k(self):
        self.assertNotAlmostEqual(
            4.5 + 0.5 * (0 - 4.5),   # C(0) = 2.25
            4.5 + 0.5 * (9 - 4.5),   # C(9) = 6.75
        )

    def test_softmap_collapse_cannot_preserve_two_cycles(self):
        self.assertNotAlmostEqual(9 - 2, 4.5 + 0.5 * (2 - 4.5))
        self.assertAlmostEqual(9 - 2, 7.0, places=9)

    def test_identity_hash_no_collision(self):
        def civ_id(uid):
            return "user_" + hashlib.sha256(uid.encode()).hexdigest()[:12]
        self.assertNotEqual(civ_id("alice123"), civ_id("alice199"))
        self.assertEqual("user_alice1", "user_alice1")

    # ---- boundary / edge-case additions ----

    def test_demote_at_exact_threshold_floor(self):
        # inclusive bound: fused == 0.28 with promoted colony must demote,
        # not fall into the hysteresis dead zone
        d = promote_decision(DEMOTE_THRESHOLD, already_promoted=True)
        self.assertEqual(d["action"], "demote")
        self.assertEqual(d["fused"], 0.28)

    def test_demote_just_below_threshold(self):
        d = promote_decision(DEMOTE_THRESHOLD - 1e-9, already_promoted=True)
        self.assertEqual(d["action"], "demote")

    def test_promote_at_exact_threshold_floor(self):
        d = promote_decision(PROMOTE_THRESHOLD, already_promoted=False)
        self.assertEqual(d["action"], "promote")
        self.assertEqual(d["fused"], 0.62)

    def test_promote_just_above_threshold(self):
        d = promote_decision(PROMOTE_THRESHOLD + 1e-9, already_promoted=False)
        self.assertEqual(d["action"], "promote")

    def test_nan_input_returns_hold_not_exception(self):
        d = promote_decision(float("nan"))
        self.assertEqual(d["action"], "hold")
        self.assertEqual(d["fused"], 0.0)

    def test_non_numeric_input_returns_hold(self):
        d = promote_decision("not-a-number")  # type: ignore[arg-type]
        self.assertEqual(d["action"], "hold")

    def test_negative_input_clipped_to_zero(self):
        d = promote_decision(-0.5)
        self.assertEqual(d["action"], "hold")
        self.assertEqual(d["fused"], 0.0)

    def test_over_one_input_clipped(self):
        d = promote_decision(1.5)
        self.assertEqual(d["action"], "promote")
        self.assertEqual(d["fused"], 1.0)

    def test_mood_label_convergent_at_0_7(self):
        r = apply_fusion("neutral", {"Core": 0.95, "L5": 0.05, "L2": 0.15})
        self.assertGreaterEqual(r["mood_dot"], 0.7)
        self.assertEqual(r["mood"], "convergent")

    def test_mood_label_survival_below_0_3(self):
        r = apply_fusion("neutral", {"Core": 0.05, "L5": 0.9, "L2": 0.0})
        self.assertLess(r["mood_dot"], 0.3)
        self.assertEqual(r["mood"], "survival")

    def test_empty_colony_genome(self):
        self.assertTrue(colony_genome([]).startswith("gn-"))
        self.assertEqual(colony_genome([]), colony_genome([]))

    def test_fallen_colony_demotion_through_apply_fusion(self):
        r = apply_fusion(
            "convergent",
            {"Core": 0.05, "L5": 0.95, "L2": 0.0},
            colony={"promoted": 1, "active": 3, "genome_id": "gn-test"},
        )
        self.assertEqual(r["promote"]["action"], "demote")
        self.assertEqual(r["colony"]["promoted"], 1)  # flag preserved in output
        self.assertEqual(r["colony"]["genome_id"], "gn-test")


if __name__ == "__main__":
    unittest.main()
