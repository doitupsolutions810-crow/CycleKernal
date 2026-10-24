import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "src" / "bridge"
sys.path.insert(0, str(BRIDGE))

from main import normalize_relay_metrics
from traits import map_metrics_to_traits
from ns_fusion import fitness_state_id


class RelayProvenanceTests(unittest.TestCase):
    def test_normalizes_wrapped_relay_metric_payload(self):
        metrics = normalize_relay_metrics({
            "metrics": {"core": 0.42, "U2": 0.31, "coupling": 0.07, "entropy": 0.65}
        })
        self.assertEqual(metrics["Core"], 0.42)
        self.assertEqual(metrics["U2"], 0.31)
        self.assertEqual(metrics["L2"], 0.07)
        self.assertEqual(metrics["L5"], 0.65)
        self.assertEqual(metrics["coupling"], metrics["L2"])
        self.assertEqual(metrics["entropy"], metrics["L5"])

    def test_accepts_json_text(self):
        metrics = normalize_relay_metrics('{"Core":0.4,"U2":0.2,"L2":0.03,"L5":0.7}')
        self.assertEqual(metrics["Core"], 0.4)

    def test_rejects_duplicate_json_keys_before_object_construction(self):
        # JSON object construction is normally last-key-wins; relay ingestion
        # must reject this lossy parse before metrics reach scoring.
        with self.assertRaisesRegex(ValueError, "duplicate JSON object key: Core"):
            normalize_relay_metrics(
                '{"Core":0.4,"Core":0.8,"U2":0.2,"L2":0.03,"L5":0.7}'
            )
        with self.assertRaisesRegex(ValueError, "duplicate JSON object key: truth"):
            normalize_relay_metrics(
                '{"Core":0.4,"U2":0.2,"L2":0.03,"L5":0.7,'
                '"belief":{"truth":0.4,"truth":0.9}}'
            )

    def test_rejects_conflicting_or_invalid_metric_aliases(self):
        base = {"Core": 0.4, "U2": 0.2, "L2": 0.03, "L5": 0.7}
        with self.assertRaisesRegex(ValueError, "Core aliases disagree"):
            normalize_relay_metrics({**base, "core": 0.5})
        with self.assertRaisesRegex(ValueError, "L2 aliases disagree"):
            normalize_relay_metrics({**base, "coupling": 0.08})
        with self.assertRaisesRegex(ValueError, "alias core must be a JSON number"):
            normalize_relay_metrics({**base, "core": "0.4"})
        with self.assertRaisesRegex(ValueError, "alias entropy must be a JSON number"):
            normalize_relay_metrics({**base, "entropy": True})

        # Equal canonical/legacy values remain backward-compatible.
        accepted = normalize_relay_metrics({
            **base, "core": 0.4, "coupling": 0.03, "entropy": 0.7
        })
        self.assertEqual(accepted["Core"], 0.4)
        self.assertEqual(accepted["L2"], 0.03)
        self.assertEqual(accepted["L5"], 0.7)

    def test_rejects_incomplete_payload(self):
        with self.assertRaisesRegex(ValueError, "U2 is required"):
            normalize_relay_metrics({"Core": 0.4, "L2": 0.03, "L5": 0.7})

    def test_rejects_nonfinite_and_out_of_range_metrics(self):
        with self.assertRaisesRegex(ValueError, "finite and in"):
            normalize_relay_metrics({"Core": float("nan"), "U2": 0.2, "L2": 0.03, "L5": 0.7})
        with self.assertRaisesRegex(ValueError, "finite and in"):
            normalize_relay_metrics({"Core": 0.4, "U2": 0.2, "L2": 1.1, "L5": 0.7})

    def test_rejects_boolean_and_numeric_string_fields_before_normalization(self):
        base = {"Core": 0.4, "U2": 0.2, "L2": 0.03, "L5": 0.7}
        for invalid in (True, False, "0.5"):
            with self.subTest(field="Core", value=invalid):
                with self.assertRaisesRegex(ValueError, "relay metric Core must be a JSON number"):
                    normalize_relay_metrics({**base, "Core": invalid})
        for invalid in (True, "0.03"):
            with self.subTest(field="L2", value=invalid):
                with self.assertRaisesRegex(ValueError, "relay metric L2 must be a JSON number"):
                    normalize_relay_metrics({**base, "L2": invalid})
        residual_payload = {
            **base,
            "stress_residual": True,
            "descent_schema": "great-scale.descent/v0.4.2",
        }
        with self.assertRaisesRegex(ValueError, "relay stress_residual must be a JSON number"):
            normalize_relay_metrics(residual_payload)
        with self.assertRaisesRegex(ValueError, "relay metric Core must be finite"):
            normalize_relay_metrics({**base, "Core": 10 ** 10000})

    def test_numeric_type_admission_matches_both_bridge_parsers(self):
        root = Path(__file__).resolve().parents[1]
        bridge_dirs = (
            ("primary", root / "src" / "bridge"),
            ("master", root / "master" / "src" / "bridge"),
        )
        base = {"Core": 0.4, "U2": 0.2, "L2": 0.03, "L5": 0.7}
        module_names = ("traits", "ns_fusion", "descent_engine")
        for name, bridge_dir in bridge_dirs:
            with self.subTest(bridge=name):
                saved_modules = {key: sys.modules.pop(key, None) for key in module_names}
                sys.path.insert(0, str(bridge_dir))
                try:
                    spec = importlib.util.spec_from_file_location(
                        f"cyclekernel_{name}_relay_main", bridge_dir / "main.py"
                    )
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    for invalid in (True, False, "0.5"):
                        with self.subTest(bridge=name, value=invalid):
                            with self.assertRaisesRegex(ValueError, "relay metric Core must be a JSON number"):
                                module.normalize_relay_metrics({**base, "Core": invalid})
                    with self.assertRaisesRegex(ValueError, "Core aliases disagree"):
                        module.normalize_relay_metrics({**base, "core": 0.5})
                    with self.assertRaisesRegex(ValueError, "duplicate JSON object key: Core"):
                        module.normalize_relay_metrics(
                            '{"Core":0.4,"Core":0.8,"U2":0.2,"L2":0.03,"L5":0.7}'
                        )
                    with self.assertRaisesRegex(ValueError, "relay stress_residual must be a JSON number"):
                        module.normalize_relay_metrics({
                            **base,
                            "stress_residual": True,
                            "descent_schema": "great-scale.descent/v0.4.2",
                        })
                finally:
                    sys.path.pop(0)
                    for key in module_names:
                        sys.modules.pop(key, None)
                        if saved_modules[key] is not None:
                            sys.modules[key] = saved_modules[key]

    def test_preserves_optional_descent_and_symbolic_inputs(self):
        payload = {
            "Core": 0.4, "U2": 0.2, "L2": 0.03, "L5": 0.7,
            "stress_residual": 3.5,
            "descent_schema": "great-scale.descent/v0.4.2",
            "belief": {"truth": 0.8, "deception": 0.2},
            "resources": {"attention": 100, "compute": 30, "memory_nodes": 5},
        }
        metrics = normalize_relay_metrics(payload)
        self.assertEqual(metrics["stress_residual"], 3.5)
        self.assertEqual(metrics["descent_schema"], "great-scale.descent/v0.4.2")
        self.assertEqual(metrics["belief"]["truth"], 0.8)
        self.assertEqual(metrics["resources"]["compute"], 30)


    def test_rejects_explicit_null_symbolic_objects(self):
        base = {"Core": 0.4, "U2": 0.2, "L2": 0.03, "L5": 0.7}
        for field in ("belief", "resources"):
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValueError, f"relay {field} must be a JSON object"):
                    normalize_relay_metrics({**base, field: None})

    def test_rejects_out_of_domain_belief_and_resource_values(self):
        base = {"Core": 0.4, "U2": 0.2, "L2": 0.03, "L5": 0.7}
        with self.assertRaisesRegex(ValueError, "belief.truth must be finite and in"):
            normalize_relay_metrics({**base, "belief": {"truth": 1.01}})
        with self.assertRaisesRegex(ValueError, "belief.deception must be finite and in"):
            normalize_relay_metrics({**base, "belief": {"truth": 0.5, "deception": float("nan")}})
        with self.assertRaisesRegex(ValueError, "resources.attention must be finite and nonnegative"):
            normalize_relay_metrics({**base, "resources": {"attention": -1}})
        with self.assertRaisesRegex(ValueError, "resources.compute must be finite and nonnegative"):
            normalize_relay_metrics({**base, "resources": {"compute": float("inf")}})
        with self.assertRaisesRegex(ValueError, "resources.memory_nodes must be finite and nonnegative"):
            normalize_relay_metrics({**base, "resources": {"memory_nodes": -0.5}})

    def test_rejects_invalid_optional_descent_residual(self):
        with self.assertRaisesRegex(ValueError, "stress_residual must be finite and in"):
            normalize_relay_metrics({
                "Core": 0.4, "U2": 0.2, "L2": 0.03, "L5": 0.7,
                "stress_residual": 8.01,
                "descent_schema": "great-scale.descent/v0.4.2",
            })

    def test_rejects_unversioned_or_mismatched_residual(self):
        base = {"Core": 0.4, "U2": 0.2, "L2": 0.03, "L5": 0.7, "stress_residual": 3.5}
        with self.assertRaisesRegex(ValueError, "requires descent_schema"):
            normalize_relay_metrics(base)
        with self.assertRaisesRegex(ValueError, "unsupported relay descent_schema"):
            normalize_relay_metrics({**base, "descent_schema": "some-other-version"})


    def test_relay_preserves_explicit_empty_symbolic_objects(self):
        payload = normalize_relay_metrics({
            "Core": 0.4, "U2": 0.2, "L2": 0.03, "L5": 0.7,
            "belief": {}, "resources": {},
        })
        self.assertEqual(payload["belief"], {})
        self.assertEqual(payload["resources"], {})
        state = map_metrics_to_traits(payload, metric_source="relay").to_dict()
        evidence = state["fitness_evidence"]
        self.assertEqual(evidence["belief_source"], "provided")
        self.assertEqual(evidence["resource_source"], "provided")
        self.assertEqual(evidence["inputs"]["symbolic"]["attention"], 0.0)
        presence = evidence["inputs"]["symbolic"]["field_presence"]
        self.assertTrue(presence["belief_mapping"])
        self.assertFalse(presence["belief_truth"])
        self.assertTrue(presence["resources_mapping"])
        self.assertFalse(presence["resource_attention"])
        self.assertEqual(
            fitness_state_id(evidence["fusion_state_witness"]),
            state["fusion_state_id"],
        )

    def test_mapped_state_retains_source_and_companion_channel(self):
        metrics = normalize_relay_metrics({"Core": 0.42, "U2": 0.31, "L2": 0.07, "L5": 0.65})
        state = map_metrics_to_traits(metrics, metric_source="relay")
        payload = state.to_dict()
        self.assertEqual(payload["metric_source"], "relay")
        self.assertTrue(payload["promotion_decision_id"].startswith("pd-"))
        self.assertTrue(payload["fusion_state_id"])
        self.assertEqual(payload["fitness_evidence"]["fusion_state_id"], payload["fusion_state_id"])
        self.assertEqual(payload["fitness_evidence"]["promotion_decision_id"], payload["promotion_decision_id"])
        self.assertEqual(fitness_state_id(payload["fitness_evidence"]["fusion_state_witness"]), payload["fusion_state_id"])
        self.assertIn("symbolic_score", payload["fitness_evidence"])
        self.assertIn("neural_score", payload["fitness_evidence"])
        self.assertIn("signed_eta", payload["fitness_evidence"])
        self.assertIn("symbolic_neural_ratio", payload["fitness_evidence"])
        self.assertEqual(payload["fitness_evidence"]["descent_source"], "default_zero")

    def test_mapped_state_marks_relay_sourced_great_scale_residual(self):
        metrics = normalize_relay_metrics({
            "Core": 0.42, "U2": 0.31, "L2": 0.07, "L5": 0.65,
            "stress_residual": 3.5,
            "descent_schema": "great-scale.descent/v0.4.2",
        })
        payload = map_metrics_to_traits(metrics, metric_source="relay").to_dict()
        self.assertEqual(payload["fitness_evidence"]["descent_source"], "provided")
        self.assertEqual(payload["fitness_evidence"]["stress_residual"], 3.5)


if __name__ == "__main__":
    unittest.main()
