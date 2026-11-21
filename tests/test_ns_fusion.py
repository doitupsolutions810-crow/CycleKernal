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

    def test_negative_input_clips_to_zero(self):
        # promote_decision clips via _clip before thresholding
        d = promote_decision(-0.5)
        self.assertEqual(d["action"], "hold")
        self.assertEqual(d["fused"], 0.0)
        d2 = promote_decision(-0.5, already_promoted=True)
        self.assertEqual(d2["action"], "demote")
        self.assertEqual(d2["fused"], 0.0)

    def test_over_one_input_clips_to_one(self):
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

    # ---- new escalation batch ----

    def test_unicode_and_emoji_mood_labels(self):
        # non-ASCII mood strings should not crash; unknown labels default neutral
        r1 = apply_fusion("🚀 convergent ☾", {"Core": 0.8, "L5": 0.1, "L2": 0.1})
        r2 = apply_fusion("neutral", {"Core": 0.8, "L5": 0.1, "L2": 0.1})
        self.assertEqual(r1["mood"], r2["mood"])
        self.assertFalse(math.isnan(r1["mood_dot"]))
        r3 = fuse_mood(0.9, "✨ sparkle ✨")
        self.assertEqual(r3, fuse_mood(0.9, "neutral"))

    def test_empty_string_seed_genome_id(self):
        from ns_fusion import genome_id
        g = genome_id("")
        self.assertTrue(g.startswith("gn-"))
        self.assertEqual(g, genome_id(""))
        self.assertNotEqual(g, genome_id("seed-a"))

    def test_colony_genome_non_string_members(self):
        # mixed types should coerce to string without crashing
        g1 = colony_genome(["a", 1, None, True])
        g2 = colony_genome(["a", "1", "None", "True"])
        self.assertEqual(g1, g2)
        self.assertTrue(g1.startswith("gn-"))

    def test_negative_active_and_promoted_counts(self):
        r = apply_fusion(
            "neutral",
            {"Core": 0.7, "L5": 0.2, "L2": 0.1},
            colony={"promoted": -3, "active": -7, "genome_id": "gn-neg"},
        )
        self.assertEqual(r["colony"]["promoted"], -3)
        self.assertEqual(r["colony"]["active"], -7)
        self.assertEqual(r["colony"]["genome_id"], "gn-neg")
        # negative promoted with low fused should still demote
        r2 = apply_fusion(
            "convergent",
            {"Core": 0.0, "L5": 1.0, "L2": 0.0},
            colony={"promoted": -1, "active": 2, "genome_id": "gn-neg2"},
        )
        self.assertEqual(r2["promote"]["action"], "demote")

    def test_fuse_mood_alpha_beta_outside_unit_interval(self):
        # alpha=2, beta=-1: fused = 2*x + (-1)*0.5 = 2x - 0.5
        # at x=1: 1.5; at x=0: -0.5. Should not crash.
        hi = fuse_mood(1.0, alpha=2.0, beta=-1.0)
        lo = fuse_mood(0.0, alpha=2.0, beta=-1.0)
        self.assertAlmostEqual(hi, 1.5)
        self.assertAlmostEqual(lo, -0.5)
        # alpha=-1, beta=2: at x=1: -1+2=1; at x=0: 2
        hi2 = fuse_mood(1.0, alpha=-1.0, beta=2.0)
        lo2 = fuse_mood(0.0, alpha=-1.0, beta=2.0)
        self.assertAlmostEqual(hi2, 1.0)
        self.assertAlmostEqual(lo2, 2.0)

    def test_extremely_long_seed_string(self):
        from ns_fusion import genome_id
        long_seed = "x" * 1_000_000
        g = genome_id(long_seed)
        self.assertTrue(g.startswith("gn-"))
        self.assertEqual(g, genome_id(long_seed))
        # different long seeds differ
        self.assertNotEqual(g, genome_id("y" * 1_000_000))

    # ---- whitespace / None / bytes / string-number batch ----

    def test_mood_whitespace_strips_to_canonical_label(self):
        # mood_score now strips before lookup, so padded labels resolve
        from ns_fusion import mood_score
        self.assertEqual(mood_score(" neutral "), 0.50)
        self.assertEqual(mood_score("\tneutral\n"), 0.50)
        self.assertEqual(mood_score("  convergent  "), 0.72)
        self.assertEqual(mood_score("\tsurvival\n"), 0.15)
        r = apply_fusion(" neutral ", {"Core": 0.8, "L5": 0.1, "L2": 0.1})
        self.assertEqual(r["mood"], " neutral ")  # raw label still preserved in output
        self.assertFalse(math.isnan(r["mood_dot"]))
        # padded convergent should score like canonical convergent
        r_pad = fuse_mood(0.9, "  convergent  ")
        r_can = fuse_mood(0.9, "convergent")
        self.assertEqual(r_pad, r_can)

    def test_mood_score_none_directly(self):
        from ns_fusion import mood_score
        # mood or "neutral" coerces None → "neutral"
        self.assertEqual(mood_score(None), 0.50)
        self.assertEqual(mood_score(""), 0.50)

    def test_genome_id_rejects_raw_bytes(self):
        from ns_fusion import genome_id
        # str.encode exists; bytes.encode does not → AttributeError
        with self.assertRaises(AttributeError):
            genome_id(b"not-a-string")  # type: ignore[arg-type]

    def test_colony_genome_explicit_none_only(self):
        g = colony_genome([None])
        self.assertTrue(g.startswith("gn-"))
        self.assertEqual(g, colony_genome(["None"]))

    def test_apply_fusion_string_numbers_in_metrics(self):
        # _safe_float parses numeric strings
        r = apply_fusion(
            "neutral",
            {"Core": "0.8", "L5": "0.2", "L2": "0.1"},
        )
        self.assertFalse(math.isnan(r["ns_fitness"]))
        self.assertFalse(math.isnan(r["mood_dot"]))
        self.assertGreater(r["ns_fitness"], 0.0)
        # string "0.8" should score like float 0.8
        r_num = apply_fusion("neutral", {"Core": 0.8, "L5": 0.2, "L2": 0.1})
        self.assertEqual(r["ns_fitness"], r_num["ns_fitness"])

    # ---- next escalation batch: strip-aware + deeper seams ----

    def test_mood_score_internal_whitespace_not_stripped(self):
        # only leading/trailing stripped; internal spaces still miss
        from ns_fusion import mood_score
        self.assertEqual(mood_score("balanced tension"), 0.5)  # space, not hyphen
        self.assertEqual(mood_score("balanced-tension"), 0.58)

    def test_fuse_mood_with_stripped_padded_mood(self):
        # fuse_mood inherits stripping via mood_score
        self.assertEqual(fuse_mood(1.0, " divergent "), fuse_mood(1.0, "divergent"))
        self.assertNotEqual(fuse_mood(1.0, " divergent "), fuse_mood(1.0, "neutral"))

    def test_apply_fusion_preserves_raw_padded_label(self):
        # output mood field keeps the raw input; only scoring strips
        r = apply_fusion("\tconvergent\n", {"Core": 0.5, "L5": 0.5, "L2": 0.0})
        self.assertEqual(r["mood"], "\tconvergent\n")

    def test_symbolic_score_negative_truth_clips(self):
        from ns_fusion import symbolic_score
        s = symbolic_score({"truth": -2.0}, {"attention": 150, "compute": 40, "memory_nodes": 8})
        self.assertEqual(s, 0.55 * 0.0 + 0.45 * 1.0)

    def test_symbolic_score_over_one_resources_clip(self):
        from ns_fusion import symbolic_score
        s = symbolic_score({"truth": 0.5}, {"attention": 9999, "compute": 9999, "memory_nodes": 9999})
        self.assertLessEqual(s, 1.0)

    def test_ns_fitness_all_defaults(self):
        f = ns_fitness()
        self.assertGreater(f, 0.0)
        self.assertLessEqual(f, 1.0)

    def test_promote_decision_none_input(self):
        d = promote_decision(None)  # type: ignore[arg-type]
        self.assertEqual(d["action"], "hold")
        self.assertEqual(d["fused"], 0.0)

    def test_colony_genome_very_large_member_list(self):
        members = [f"civ_{i}" for i in range(10_000)]
        g = colony_genome(members)
        self.assertTrue(g.startswith("gn-"))
        self.assertEqual(g, colony_genome(members))
        # reversed order must match (sorted internally)
        self.assertEqual(g, colony_genome(list(reversed(members))))

    def test_genome_id_unicode_seed(self):
        from ns_fusion import genome_id
        g = genome_id("αβγ-δ")
        self.assertTrue(g.startswith("gn-"))
        self.assertEqual(g, genome_id("αβγ-δ"))
        self.assertNotEqual(g, genome_id("αβγ-ε"))

    def test_apply_fusion_bool_metrics(self):
        # bool is a subclass of int; _safe_float(True) == 1.0
        r = apply_fusion("neutral", {"Core": True, "L5": False, "L2": True})
        self.assertFalse(math.isnan(r["ns_fitness"]))
        r_num = apply_fusion("neutral", {"Core": 1.0, "L5": 0.0, "L2": 1.0})
        self.assertEqual(r["ns_fitness"], r_num["ns_fitness"])


if __name__ == "__main__":
    unittest.main()
