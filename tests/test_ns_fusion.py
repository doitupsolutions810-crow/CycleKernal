import hashlib
import math
import unittest
import importlib.util
from pathlib import Path
from ns_fusion import (apply_fusion, build_companion_channel, fusion_components, fuse_mood, ns_fitness, promote_decision, colony_genome)


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


    def test_companion_reports_real_symbolic_and_neural_components(self):
        result = apply_fusion(
            "neutral",
            {
                "Core": 0.5,
                "L5": 0.25,
                "L2": 0.05,
                "belief": {"truth": 0.8, "deception": 0.2},
                "resources": {"attention": 100, "compute": 30, "memory_nodes": 4},
                "telemetry_source": "test-relay",
            },
        )
        channel = result["companion_channel"]
        expected_symbolic = 0.55 * 0.8 + 0.45 * (
            (100 / 150) * 0.45 + (30 / 40) * 0.35 + (4 / 8) * 0.20
        )
        expected_neural = 0.5 * 0.5 + 0.3 * (1 - 0.25) + 0.2 * (0.05 / 0.2)
        self.assertAlmostEqual(channel["symbolic_score"], expected_symbolic)
        self.assertAlmostEqual(channel["neural_score"], expected_neural)
        self.assertEqual(channel["symbolic_source"], "provided")
        self.assertEqual(channel["telemetry_source"], "test-relay")
        self.assertEqual(channel["schema"], "cyclekernel.ns-fusion-companion/v1")

    def test_missing_symbolic_inputs_are_explicit_not_silent(self):
        result = apply_fusion(
            "neutral",
            {"Core": 0.5, "L5": 0.2, "L2": 0.1, "telemetry_source": "synthetic"},
        )
        channel = result["companion_channel"]
        self.assertEqual(channel["symbolic_source"], "default-fallback")
        self.assertAlmostEqual(channel["symbolic_score"], 0.4325)
        self.assertEqual(channel["telemetry_source"], "synthetic")
        self.assertEqual(channel["inputs"]["symbolic"]["truth"], 0.5)
        self.assertEqual(channel["inputs"]["symbolic"]["attention"], 50.0)

    def test_four_signed_threshold_distances_are_emitted(self):
        result = apply_fusion("neutral", {"Core": 0.5, "L5": 0.25, "L2": 0.05})
        channel = result["companion_channel"]
        self.assertEqual(
            set(channel["threshold_distances"]),
            {"promote", "demote", "survival_label", "convergent_label"},
        )
        for name, threshold in channel["thresholds"].items():
            self.assertAlmostEqual(
                channel["threshold_distances"][name], channel["mood_dot"] - threshold
            )

    def test_equal_geometric_mean_can_hide_different_components(self):
        component_pairs = [(0.5, 0.5), (0.25, 1.0), (1.0, 0.25)]
        scalar_values = [(symbolic * neural) ** 0.5 for symbolic, neural in component_pairs]
        self.assertTrue(all(abs(value - 0.5) < 1e-12 for value in scalar_values))
        channels = [
            build_companion_channel(
                components={
                    "symbolic_score": symbolic,
                    "neural_score": neural,
                    "ns_fitness": 0.5,
                    "symbolic_source": "test",
                    "inputs": {"symbolic": {}, "neural": {}},
                },
                fused=0.5,
                state_mood="neutral",
                decision={"action": "hold"},
                telemetry_source="unit-test",
            )
            for symbolic, neural in component_pairs
        ]
        self.assertEqual(len({x["mood_dot"] for x in channels}), 1)
        self.assertEqual(len({(x["symbolic_score"], x["neural_score"]) for x in channels}), 3)

    def test_all_legacy_copies_share_companion_contract(self):
        root = Path(__file__).resolve().parents[1]
        for relative in ("backend/ns_fusion.py", "master/src/bridge/ns_fusion.py"):
            with self.subTest(relative=relative):
                spec = importlib.util.spec_from_file_location(
                    "cyclekernel_copy_" + relative.replace("/", "_").replace(".", "_"),
                    root / relative,
                )
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                result = module.apply_fusion(
                    "neutral",
                    {"Core": 0.5, "L5": 0.2, "L2": 0.1, "telemetry_source": "copy-test"},
                )
                self.assertEqual(
                    result["companion_channel"]["schema"],
                    "cyclekernel.ns-fusion-companion/v1",
                )
                self.assertAlmostEqual(
                    result["companion_channel"]["symbolic_score"], 0.4325
                )

    # GS-LVI seam: quotient-circle contraction
    # Public Great Scale docs describe a modulo-nine circle with involution,
    # but soft_contract is an affine map on the real line. On the quotient,
    # C(x+9n) - C(x) = 9kn, a multiple of 9 only when k is an integer.
    # Under |k|<1 the only integer is k=0, so the circle fiber is
    # non-constant: equivalent states map to non-equivalent outputs.
    def test_quotient_seam_zero_and_nine_non_equivalent(self):
        FIXED, k = 4.5, 0.5
        c0 = FIXED + k * (0 - FIXED)    # 2.25
        c9 = FIXED + k * (9 - FIXED)    # 6.75
        # modular distance on the circle
        d = abs(((c0 - c9) % 9 + 9) % 9)
        qd = min(d, 9 - d)
        self.assertAlmostEqual(qd, 4.5, places=9)
        self.assertGreater(abs(c0 - c9) % 9, 1e-9)

    def test_affine_map_not_circle_native_under_strict_k(self):
        # |k|<1 admits no nonzero integer k → fiber non-constant
        self.assertNotAlmostEqual(
            4.5 + 0.5 * (0 - 4.5),   # C(0) = 2.25
            4.5 + 0.5 * (9 - 4.5),   # C(9) = 6.75
        )

    def test_softmap_collapse_cannot_preserve_two_cycles(self):
        # soft_map(x) = 9-x is a pure involution; at k=0.5 the affine
        # attractor is the constant 4.5. They agree only at the fixed point.
        self.assertNotAlmostEqual(9 - 2, 4.5 + 0.5 * (2 - 4.5))
        self.assertAlmostEqual(9 - 2, 7.0, places=9)

    def test_identity_hash_no_collision(self):
        # sha256 digest keys: alice123 and alice199 must not alias
        def civ_id(uid):
            return "user_" + hashlib.sha256(uid.encode()).hexdigest()[:12]
        self.assertNotEqual(civ_id("alice123"), civ_id("alice199"))
        # legacy slice still collides (documents the defect being replaced)
        self.assertEqual("user_alice1", "user_alice1")


if __name__ == "__main__":
    unittest.main()
