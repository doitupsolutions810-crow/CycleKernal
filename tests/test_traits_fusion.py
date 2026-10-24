import unittest
from traits import map_metrics_to_traits


class TraitBridgeFusionEvidenceTests(unittest.TestCase):
    def test_loopmem_bridge_serializes_companion_channels(self):
        state = map_metrics_to_traits({"Core": 0.5, "L2": 0.03, "L5": 0.4, "U2": 0.5})
        payload = state.to_dict()
        for key in (
            "symbolic_score", "neural_score", "channel_delta", "channel_gap",
            "threshold_distances", "mood_threshold_distances", "fusion_evidence",
            "channel_provenance",
        ):
            self.assertIn(key, payload)
        # This synthetic heartbeat has no truth/resource inputs, so its symbolic
        # channel must be visibly marked defaulted rather than look like live data.
        self.assertEqual(payload["channel_provenance"]["symbolic"]["source"], "defaulted_inputs")
        self.assertFalse(payload["channel_provenance"]["symbolic"]["complete"])
        self.assertTrue(payload["channel_provenance"]["neural"]["complete"])

    def test_real_symbolic_inputs_are_marked_complete(self):
        state = map_metrics_to_traits({
            "Core": 0.8, "L2": 0.1, "L5": 0.2, "U2": 0.5,
            "belief": {"truth": 0.8},
            "resources": {"attention": 120, "compute": 30, "memory_nodes": 6},
        })
        payload = state.to_dict()
        self.assertEqual(payload["channel_provenance"]["symbolic"]["source"], "belief+resources")
        self.assertTrue(payload["channel_provenance"]["symbolic"]["complete"])


if __name__ == "__main__":
    unittest.main()
