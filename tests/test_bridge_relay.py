import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "src" / "bridge"
sys.path.insert(0, str(BRIDGE))

from main import normalize_relay_metrics
from traits import map_metrics_to_traits


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

    def test_rejects_incomplete_payload(self):
        with self.assertRaisesRegex(ValueError, "U2 is required"):
            normalize_relay_metrics({"Core": 0.4, "L2": 0.03, "L5": 0.7})

    def test_rejects_nonfinite_and_out_of_range_metrics(self):
        with self.assertRaisesRegex(ValueError, "finite and in"):
            normalize_relay_metrics({"Core": float("nan"), "U2": 0.2, "L2": 0.03, "L5": 0.7})
        with self.assertRaisesRegex(ValueError, "finite and in"):
            normalize_relay_metrics({"Core": 0.4, "U2": 0.2, "L2": 1.1, "L5": 0.7})

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

    def test_mapped_state_retains_source_and_companion_channel(self):
        metrics = normalize_relay_metrics({"Core": 0.42, "U2": 0.31, "L2": 0.07, "L5": 0.65})
        state = map_metrics_to_traits(metrics, metric_source="relay")
        payload = state.to_dict()
        self.assertEqual(payload["metric_source"], "relay")
        self.assertTrue(payload["fusion_state_id"])
        self.assertEqual(payload["fitness_evidence"]["fusion_state_id"], payload["fusion_state_id"])
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
