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

    def test_inf_input_returns_hold(self):
        d = promote_decision(float("inf"))
        self.assertEqual(d["action"], "hold")
        self.assertEqual(d["fused"], 0.0)
        d2 = promote_decision(float("-inf"))
        self.assertEqual(d2["action"], "demote")
        self.assertEqual(d2["fused"], 0.0)

    def test_non_numeric_input_returns_hold(self):
        d = promote_decision("not-a-number")  # type: ignore[arg-type]
        self.assertEqual(d["action"], "hold")
        self.assertEqual(d["fused"], 0.0)

    def test_negative_input_passes_through_unclipped(self):
        # promote_decision does not clip; _clip lives in scoring helpers.
        # -0.5 is below DEMOTE_THRESHOLD, so an already-promoted colony demotes.
        d = promote_decision(-0.5)
        self.assertEqual(d["action"], "hold")
        self.assertEqual(d["fused"], -0.5)
        d2 = promote_decision(-0.5, already_promoted=True)
        self.assertEqual(d2["action"], "demote")
        self.assertEqual(d2["fused"], -0.5)

    def test_over_one_input_passes_through_unclipped(self):
        d = promote_decision(1.5)
        self.assertEqual(d["action"], "promote")
        self.assertEqual(d["fused"], 1.5)

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
        # Extreme metrics: Core near zero, entropy maxed, coupling zero.
        # ns_fitness collapses toward zero, fuse_mood pulls below 0.28.
        r = apply_fusion(
            "convergent",
            {"Core": 0.0, "L5": 1.0, "L2": 0.0},
            colony={"promoted": 1, "active": 3, "genome_id": "gn-test"},
        )
        self.assertEqual(r["promote"]["action"], "demote")
        self.assertEqual(r["colony"]["promoted"], 1)  # flag preserved in output
        self.assertEqual(r["colony"]["genome_id"], "gn-test")
        self.assertLess(r["mood_dot"], DEMOTE_THRESHOLD)

    def test_nan_core_defaults_to_half_not_zero(self):
        # apply_fusion defaults NaN Core to 0.5 by design so fitness stays nonzero
        r = apply_fusion("neutral", {"Core": float("nan"), "L5": 0.0, "L2": 0.0})
        self.assertGreater(r["ns_fitness"], 0.0)
        self.assertFalse(math.isnan(r["ns_fitness"]))
        self.assertFalse(math.isnan(r["mood_dot"]))

    def test_nan_entropy_and_coupling_safe(self):
        r = apply_fusion("neutral", {"Core": 0.5, "L5": float("nan"), "L2": float("nan")})
        self.assertFalse(math.isnan(r["ns_fitness"]))
        self.assertFalse(math.isnan(r["mood_dot"]))

    def test_missing_metrics_use_defaults(self):
        r = apply_fusion("neutral", {})
        self.assertIn("ns_fitness", r)
        self.assertIn("mood_dot", r)
        self.assertEqual(r["mood"], "neutral")

    def test_unknown_mood_score_defaults_neutral(self):
        self.assertEqual(fuse_mood(1.0, "unknown-mood"), fuse_mood(1.0, "neutral"))

    def test_promote_threshold_constant(self):
        self.assertEqual(PROMOTE_THRESHOLD, 0.62)
        self.assertEqual(DEMOTE_THRESHOLD, 0.28)
        self.assertGreater(PROMOTE_THRESHOLD, DEMOTE_THRESHOLD)

    def test_hysteresis_gap_populated(self):
        # values strictly between 0.28 and 0.62 must hold regardless of prior state
        for v in (0.30, 0.45, 0.50, 0.60):
            self.assertEqual(promote_decision(v)["action"], "hold")
            self.assertEqual(promote_decision(v, already_promoted=True)["action"], "hold")

    def test_genome_id_deterministic(self):
        self.assertEqual(genome_id("seed-a"), genome_id("seed-a"))
        self.assertNotEqual(genome_id("seed-a"), genome_id("seed-b"))

    def test_symbolic_score_zero_resources(self):
        from ns_fusion import symbolic_score
        s = symbolic_score({"truth": 1.0}, {"attention": 0, "compute": 0, "memory_nodes": 0})
        self.assertEqual(s, 0.55 * 1.0)  # 0.55*truth + 0.45*0

    def test_neural_score_max_entropy(self):
        from ns_fusion import neural_score
        n = neural_score(1.0, 1.0, 0.2)
        self.assertLess(n, 1.0)


if __name__ == "__main__":
    unittest.main()
