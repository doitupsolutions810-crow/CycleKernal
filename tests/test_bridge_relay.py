import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "bridge"))

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
        metrics = normalize_relay_metrics(
            '{"Core":0.4,"U2":0.2,"L2":0.03,"L5":0.7}'
        )
        self.assertEqual(metrics["Core"], 0.4)

    def test_rejects_incomplete_payload(self):
        with self.assertRaisesRegex(ValueError, "U2 is required"):
            normalize_relay_metrics({"Core": 0.4, "L2": 0.03, "L5": 0.7})

    def test_rejects_nonfinite_and_out_of_range_metrics(self):
        with self.assertRaisesRegex(ValueError, "finite and in"):
            normalize_relay_metrics({"Core": float("nan"), "U2": 0.2, "L2": 0.03, "L5": 0.7})
        with self.assertRaisesRegex(ValueError, "finite and in"):
            normalize_relay_metrics({"Core": 0.4, "U2": 0.2, "L2": 1.1, "L5": 0.7})

    def test_mapped_state_retains_source_and_companion_channel(self):
        metrics = normalize_relay_metrics({"Core": 0.42, "U2": 0.31, "L2": 0.07, "L5": 0.65})
        state = map_metrics_to_traits(metrics, metric_source="relay")
        payload = state.to_dict()
        self.assertEqual(payload["metric_source"], "relay")
        self.assertIn("symbolic_score", payload["fitness_evidence"])
        self.assertIn("neural_score", payload["fitness_evidence"])
        self.assertIn("signed_eta", payload["fitness_evidence"])
        self.assertIn("symbolic_neural_ratio", payload["fitness_evidence"])


if __name__ == "__main__":
    unittest.main()
