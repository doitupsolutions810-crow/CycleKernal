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
        r = apply_fusion(
            "convergent",
            {"Core": 0.0, "L5": 1.0, "L2": 0.0},
            colony={"promoted": 1, "active": 3, "genome_id": "gn-test"},
        )
        self.assertEqual(r["promote"]["action"], "demote")
        self.assertEqual(r["colony"]["promoted"], 1)
        self.assertEqual(r["colony"]["genome_id"], "gn-test")
        self.assertLess(r["mood_dot"], DEMOTE_THRESHOLD)

    def test_nan_core_defaults_to_half_not_zero(self):
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
        for v in (0.30, 0.45, 0.50, 0.60):
            self.assertEqual(promote_decision(v)["action"], "hold")
            self.assertEqual(promote_decision(v, already_promoted=True)["action"], "hold")

    def test_genome_id_deterministic(self):
        self.assertEqual(genome_id("seed-a"), genome_id("seed-a"))
        self.assertNotEqual(genome_id("seed-a"), genome_id("seed-b"))

    def test_symbolic_score_zero_resources(self):
        from ns_fusion import symbolic_score
        s = symbolic_score({"truth": 1.0}, {"attention": 0, "compute": 0, "memory_nodes": 0})
        self.assertEqual(s, 0.55 * 1.0)

    def test_neural_score_max_entropy(self):
        from ns_fusion import neural_score
        n = neural_score(1.0, 1.0, 0.2)
        self.assertLess(n, 1.0)

    # ---- new escalation batch ----

    def test_unicode_and_emoji_mood_labels(self):
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
        r2 = apply_fusion(
            "convergent",
            {"Core": 0.0, "L5": 1.0, "L2": 0.0},
            colony={"promoted": -1, "active": 2, "genome_id": "gn-neg2"},
        )
        self.assertEqual(r2["promote"]["action"], "demote")

    def test_fuse_mood_alpha_beta_outside_unit_interval(self):
        hi = fuse_mood(1.0, alpha=2.0, beta=-1.0)
        lo = fuse_mood(0.0, alpha=2.0, beta=-1.0)
        self.assertAlmostEqual(hi, 1.5)
        self.assertAlmostEqual(lo, -0.5)
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
        self.assertNotEqual(g, genome_id("y" * 1_000_000))

    # ---- whitespace / None / bytes / string-number batch ----

    def test_mood_whitespace_strips_to_canonical_label(self):
        from ns_fusion import mood_score
        self.assertEqual(mood_score(" neutral "), 0.50)
        self.assertEqual(mood_score("\tneutral\n"), 0.50)
        self.assertEqual(mood_score("  convergent  "), 0.72)
        self.assertEqual(mood_score("\tsurvival\n"), 0.15)
        r = apply_fusion(" neutral ", {"Core": 0.8, "L5": 0.1, "L2": 0.1})
        self.assertEqual(r["mood"], " neutral ")
        self.assertFalse(math.isnan(r["mood_dot"]))
        r_pad = fuse_mood(0.9, "  convergent  ")
        r_can = fuse_mood(0.9, "convergent")
        self.assertEqual(r_pad, r_can)

    def test_mood_score_none_directly(self):
        from ns_fusion import mood_score
        self.assertEqual(mood_score(None), 0.50)
        self.assertEqual(mood_score(""), 0.50)

    def test_genome_id_rejects_raw_bytes(self):
        from ns_fusion import genome_id
        with self.assertRaises(AttributeError):
            genome_id(b"not-a-string")  # type: ignore[arg-type]

    def test_colony_genome_explicit_none_only(self):
        g = colony_genome([None])
        self.assertTrue(g.startswith("gn-"))
        self.assertEqual(g, colony_genome(["None"]))

    def test_apply_fusion_string_numbers_in_metrics(self):
        r = apply_fusion(
            "neutral",
            {"Core": "0.8", "L5": "0.2", "L2": "0.1"},
        )
        self.assertFalse(math.isnan(r["ns_fitness"]))
        self.assertFalse(math.isnan(r["mood_dot"]))
        self.assertGreater(r["ns_fitness"], 0.0)
        r_num = apply_fusion("neutral", {"Core": 0.8, "L5": 0.2, "L2": 0.1})
        self.assertEqual(r["ns_fitness"], r_num["ns_fitness"])

    # ---- next escalation batch: strip-aware + deeper seams ----

    def test_mood_score_internal_whitespace_not_stripped(self):
        from ns_fusion import mood_score
        self.assertEqual(mood_score("balanced tension"), 0.5)
        self.assertEqual(mood_score("balanced-tension"), 0.58)

    def test_fuse_mood_with_stripped_padded_mood(self):
        self.assertEqual(fuse_mood(1.0, " divergent "), fuse_mood(1.0, "divergent"))
        self.assertNotEqual(fuse_mood(1.0, " divergent "), fuse_mood(1.0, "neutral"))

    def test_apply_fusion_preserves_raw_padded_label(self):
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
        self.assertEqual(g, colony_genome(list(reversed(members))))

    def test_genome_id_unicode_seed(self):
        from ns_fusion import genome_id
        g = genome_id("αβγ-δ")
        self.assertTrue(g.startswith("gn-"))
        self.assertEqual(g, genome_id("αβγ-δ"))
        self.assertNotEqual(g, genome_id("αβγ-ε"))

    def test_apply_fusion_bool_metrics(self):
        r = apply_fusion("neutral", {"Core": True, "L5": False, "L2": True})
        self.assertFalse(math.isnan(r["ns_fitness"]))
        r_num = apply_fusion("neutral", {"Core": 1.0, "L5": 0.0, "L2": 1.0})
        self.assertEqual(r["ns_fitness"], r_num["ns_fitness"])

    # ---- escalation batch: empty metrics, unknown keys, whitespace seed,
    # mixed genome types, numeric-string mood, non-string fuse_mood,
    # non-numeric promote string, zero-zero counts, near-float-max ----

    def test_apply_fusion_empty_metrics_dict(self):
        r = apply_fusion("neutral", {})
        self.assertIn("ns_fitness", r)
        self.assertIn("mood_dot", r)
        self.assertEqual(r["mood"], "neutral")
        self.assertFalse(math.isnan(r["ns_fitness"]))

    def test_apply_fusion_unknown_extra_keys_in_metrics(self):
        r = apply_fusion(
            "neutral",
            {"Core": 0.8, "L5": 0.1, "L2": 0.1, "mystery": 999, "foo": "bar"},
        )
        self.assertFalse(math.isnan(r["ns_fitness"]))
        self.assertFalse(math.isnan(r["mood_dot"]))
        r_base = apply_fusion("neutral", {"Core": 0.8, "L5": 0.1, "L2": 0.1})
        self.assertEqual(r["ns_fitness"], r_base["ns_fitness"])

    def test_genome_id_whitespace_only_seed(self):
        from ns_fusion import genome_id
        g = genome_id("   ")
        self.assertTrue(g.startswith("gn-"))
        self.assertEqual(g, genome_id("   "))
        self.assertNotEqual(g, genome_id(""))

    def test_colony_genome_mixed_string_and_non_string(self):
        g1 = colony_genome(["x", 42, 3.14, False])
        g2 = colony_genome(["x", "42", "3.14", "False"])
        self.assertEqual(g1, g2)
        self.assertTrue(g1.startswith("gn-"))

    def test_mood_score_numeric_string(self):
        from ns_fusion import mood_score
        self.assertEqual(mood_score("0.72"), 0.5)
        self.assertEqual(mood_score("0.15"), 0.5)

    def test_fuse_mood_non_string_mood(self):
        self.assertEqual(fuse_mood(0.9, 123), fuse_mood(0.9, "neutral"))  # type: ignore[arg-type]
        self.assertEqual(fuse_mood(0.9, None), fuse_mood(0.9, "neutral"))  # type: ignore[arg-type]

    def test_promote_decision_non_numeric_string(self):
        d = promote_decision("0.9")  # type: ignore[arg-type]
        self.assertEqual(d["action"], "promote")
        self.assertEqual(d["fused"], 0.9)

    def test_apply_fusion_zero_zero_counts(self):
        r = apply_fusion(
            "neutral",
            {"Core": 0.5, "L5": 0.0, "L2": 0.0},
            colony={"promoted": 0, "active": 0, "held": 0, "dormant": 0},
        )
        self.assertEqual(r["colony"]["active"], 0)
        self.assertEqual(r["colony"]["promoted"], 0)
        self.assertFalse(math.isnan(r["ns_fitness"]))

    def test_apply_fusion_metrics_near_float_max(self):
        r = apply_fusion(
            "neutral",
            {"Core": 1.7e308, "L5": 1.7e308, "L2": 1.7e308},
        )
        self.assertFalse(math.isnan(r["ns_fitness"]))
        self.assertFalse(math.isnan(r["mood_dot"]))
        self.assertLessEqual(r["ns_fitness"], 1.0)
        self.assertLessEqual(r["mood_dot"], 1.0)

    # ---- deeper seams: empty-string metrics, type-coercion landmines, bool quirks ----

    def test_apply_fusion_core_empty_string(self):
        # _safe_float("") → ValueError → default 0.5
        r = apply_fusion("neutral", {"Core": "", "L5": 0.0, "L2": 0.0})
        self.assertFalse(math.isnan(r["ns_fitness"]))
        r_num = apply_fusion("neutral", {"Core": 0.5, "L5": 0.0, "L2": 0.0})
        self.assertEqual(r["ns_fitness"], r_num["ns_fitness"])

    def test_apply_fusion_l5_empty_string(self):
        r = apply_fusion("neutral", {"Core": 0.5, "L5": "", "L2": 0.0})
        self.assertFalse(math.isnan(r["ns_fitness"]))

    def test_apply_fusion_core_as_list(self):
        # _safe_float([0.5]) → TypeError → default 0.5
        r = apply_fusion("neutral", {"Core": [0.5], "L5": 0.0, "L2": 0.0})
        self.assertFalse(math.isnan(r["ns_fitness"]))
        r_num = apply_fusion("neutral", {"Core": 0.5, "L5": 0.0, "L2": 0.0})
        self.assertEqual(r["ns_fitness"], r_num["ns_fitness"])

    def test_colony_promoted_string_zero_bool_quirk(self):
        # bool("0") is True in Python — string "0" falsely signals promoted
        r = apply_fusion(
            "convergent",
            {"Core": 0.0, "L5": 1.0, "L2": 0.0},
            colony={"promoted": "0", "active": 2, "genome_id": "gn-str0"},
        )
        # promoted="0" → bool("0") is True → already_promoted=True → demote
        self.assertEqual(r["promote"]["action"], "demote")

    def test_colony_active_string_float_raises(self):
        # int("3.5") raises ValueError — unhandled crash path
        with self.assertRaises(ValueError):
            apply_fusion(
                "neutral",
                {"Core": 0.5, "L5": 0.0, "L2": 0.0},
                colony={"promoted": 0, "active": "3.5", "genome_id": "gn-sf"},
            )

    def test_colony_active_float_silent_truncation(self):
        # int(3.7) == 3, no warning
        r = apply_fusion(
            "neutral",
            {"Core": 0.5, "L5": 0.0, "L2": 0.0},
            colony={"promoted": 0, "active": 3.7, "genome_id": "gn-ft"},
        )
        self.assertEqual(r["colony"]["active"], 3)

    def test_ns_fitness_belief_empty_dict_falls_back_to_defaults(self):
        # empty dict is falsy → `belief or defaults` uses defaults
        f1 = ns_fitness(belief={})
        f2 = ns_fitness()
        self.assertEqual(f1, f2)

    def test_ns_fitness_resources_empty_dict_falls_back_to_defaults(self):
        f1 = ns_fitness(resources={})
        f2 = ns_fitness()
        self.assertEqual(f1, f2)

    def test_neural_score_negative_coupling_clips_to_zero(self):
        from ns_fusion import neural_score
        n = neural_score(0.8, 0.1, -1.0)
        n_zero = neural_score(0.8, 0.1, 0.0)
        self.assertEqual(n, n_zero)

    def test_neural_score_coupling_far_above_threshold(self):
        from ns_fusion import neural_score
        n = neural_score(0.8, 0.1, 10.0)
        self.assertLessEqual(n, 1.0)

    def test_genome_id_null_byte_in_seed(self):
        from ns_fusion import genome_id
        g = genome_id("a\x00b")
        self.assertTrue(g.startswith("gn-"))
        self.assertEqual(g, genome_id("a\x00b"))
        self.assertNotEqual(g, genome_id("ab"))

    def test_colony_genome_duplicate_members(self):
        g1 = colony_genome(["a", "a", "b"])
        g2 = colony_genome(["a", "b"])
        # duplicates are not deduplicated before sorting — different blob
        self.assertNotEqual(g1, g2)

    def test_apply_fusion_empty_state_mood(self):
        r = apply_fusion("", {"Core": 0.5, "L5": 0.0, "L2": 0.0})
        self.assertEqual(r["mood"], "")
        self.assertFalse(math.isnan(r["mood_dot"]))

    def test_apply_fusion_none_state_mood(self):
        r = apply_fusion(None, {"Core": 0.5, "L5": 0.0, "L2": 0.0})  # type: ignore[arg-type]
        self.assertFalse(math.isnan(r["mood_dot"]))

    def test_promote_decision_boolean_true(self):
        d = promote_decision(True)  # type: ignore[arg-type]
        self.assertEqual(d["action"], "promote")
        self.assertEqual(d["fused"], 1.0)

    def test_negative_zero_normalizes_to_positive_zero(self):
        d = promote_decision(-0.0)
        self.assertEqual(d["fused"], 0.0)
        self.assertFalse(math.copysign(1.0, d["fused"]) < 0)

    def test_apply_fusion_generates_genome_id_when_colony_lacks_one(self):
        r = apply_fusion("neutral", {"Core": 0.5, "L5": 0.0, "L2": 0.0}, colony={})
        self.assertTrue(r["genome_id"].startswith("gn-"))
        self.assertEqual(r["colony"]["genome_id"], "")

    def test_colony_genome_round_trip_member_order(self):
        members = ["z", "m", "a", "q"]
        g = colony_genome(members)
        self.assertEqual(g, colony_genome(list(reversed(members))))
        self.assertNotEqual(g, colony_genome(["a", "m", "q", "z", "a"]))

    def test_apply_fusion_promoted_string_nonzero(self):
        # bool("1") is True — string "1" correctly signals promoted
        r = apply_fusion(
            "convergent",
            {"Core": 0.0, "L5": 1.0, "L2": 0.0},
            colony={"promoted": "1", "active": 2, "genome_id": "gn-str1"},
        )
        self.assertEqual(r["promote"]["action"], "demote")

    def test_apply_fusion_held_float_truncation(self):
        r = apply_fusion(
            "neutral",
            {"Core": 0.5, "L5": 0.0, "L2": 0.0},
            colony={"promoted": 0, "active": 0, "held": 2.9, "dormant": 0.1},
        )
        self.assertEqual(r["colony"]["held"], 2)
        self.assertEqual(r["colony"]["dormant"], 0)

    def test_fuse_mood_ns_fit_as_string(self):
        # _safe_float parses "0.8" → 0.8
        self.assertEqual(fuse_mood("0.8", "neutral"), fuse_mood(0.8, "neutral"))  # type: ignore[arg-type]

    def test_fuse_mood_ns_fit_none(self):
        # _safe_float(None) → 0.0
        self.assertEqual(fuse_mood(None, "neutral"), fuse_mood(0.0, "neutral"))  # type: ignore[arg-type]

    def test_symbolic_score_belief_missing_truth_key(self):
        from ns_fusion import symbolic_score
        s = symbolic_score({"deception": 0.2}, {"attention": 50, "compute": 20, "memory_nodes": 1})
        # truth defaults to 0.5
        self.assertEqual(s, symbolic_score({"truth": 0.5}, {"attention": 50, "compute": 20, "memory_nodes": 1}))

    def test_symbolic_score_resources_missing_keys(self):
        from ns_fusion import symbolic_score
        s = symbolic_score({"truth": 0.8}, {})
        self.assertEqual(s, symbolic_score({"truth": 0.8}, {"attention": 0, "compute": 0, "memory_nodes": 0}))

    def test_apply_fusion_metrics_nested_dict_value(self):
        # nested structures should be ignored safely via _safe_float default
        r = apply_fusion("neutral", {"Core": {"v": 0.5}, "L5": 0.0, "L2": 0.0})
        self.assertFalse(math.isnan(r["ns_fitness"]))
        r_num = apply_fusion("neutral", {"Core": 0.5, "L5": 0.0, "L2": 0.0})
        self.assertEqual(r["ns_fitness"], r_num["ns_fitness"])

    def test_apply_fusion_label_unchanged_when_already_convergent(self):
        # fused >= 0.7 but state_mood is already "convergent" → no rewrite
        r = apply_fusion("convergent", {"Core": 0.95, "L5": 0.05, "L2": 0.15})
        self.assertEqual(r["mood"], "convergent")

    def test_apply_fusion_label_unchanged_when_already_survival(self):
        # fused < 0.3 but state_mood is already "survival" → no rewrite
        r = apply_fusion("survival", {"Core": 0.05, "L5": 0.9, "L2": 0.0})
        self.assertEqual(r["mood"], "survival")

    def test_genome_id_similar_seeds_no_collision(self):
        from ns_fusion import genome_id
        seeds = [f"seed-{i}" for i in range(100)]
        ids = [genome_id(s) for s in seeds]
        self.assertEqual(len(ids), len(set(ids)))

    def test_apply_fusion_idempotent(self):
        r1 = apply_fusion("neutral", {"Core": 0.6, "L5": 0.3, "L2": 0.1}, colony={"promoted": 1, "active": 4})
        r2 = apply_fusion("neutral", {"Core": 0.6, "L5": 0.3, "L2": 0.1}, colony={"promoted": 1, "active": 4})
        self.assertEqual(r1, r2)

    def test_promote_decision_at_both_boundaries_simultaneously_impossible(self):
        # PROMOTE (0.62) > DEMOTE (0.28) — no value satisfies both
        self.assertGreater(PROMOTE_THRESHOLD, DEMOTE_THRESHOLD)
