import unittest

from backend.ns_fusion import apply_fusion, promote_decision


class ApplyFusionTransitionTests(unittest.TestCase):
    def test_previously_promoted_low_score_is_demoted_through_wrapper(self):
        result = apply_fusion(
            "survival",
            {"Core": 0.0, "L5": 1.0, "L2": 0.0},
            colony={"promoted": 1},
        )
        self.assertLess(result["mood_dot"], 0.28)
        self.assertEqual(result["promote"]["action"], "demote")

    def test_unpromoted_high_score_is_promoted(self):
        result = apply_fusion(
            "convergent",
            {"Core": 1.0, "L5": 0.0, "L2": 0.2},
            colony={"promoted": 0},
        )
        self.assertGreaterEqual(result["mood_dot"], 0.62)
        self.assertEqual(result["promote"]["action"], "promote")

    def test_unpromoted_low_score_is_held(self):
        result = apply_fusion(
            "survival",
            {"Core": 0.0, "L5": 1.0, "L2": 0.0},
            colony={"promoted": 0},
        )
        self.assertLess(result["mood_dot"], 0.62)
        self.assertEqual(result["promote"]["action"], "hold")

    def test_demote_threshold_is_strict(self):
        self.assertEqual(
            promote_decision(0.28, already_promoted=True)["action"],
            "hold",
        )
        self.assertEqual(
            promote_decision(0.2799, already_promoted=True)["action"],
            "demote",
        )

    def test_promote_threshold_is_inclusive(self):
        self.assertEqual(
            promote_decision(0.62, already_promoted=False)["action"],
            "promote",
        )
        self.assertEqual(
            promote_decision(0.6199, already_promoted=False)["action"],
            "hold",
        )


if __name__ == "__main__":
    unittest.main()
