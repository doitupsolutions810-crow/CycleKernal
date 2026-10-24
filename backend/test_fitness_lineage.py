import unittest

from simulation_core import Universe


class FitnessLineageTests(unittest.TestCase):
    def test_every_fusion_event_carries_companion_channel_evidence(self):
        universe = Universe("lineage-test")
        civ = universe.add_civilization("test-civ")
        universe.simulate_cycle()
        evidence = civ["fitness_evidence"]
        self.assertEqual(evidence["schema"], "cyclekernel.fusion-evidence/v1")
        self.assertIn("symbolic_score", evidence)
        self.assertIn("neural_score", evidence)
        self.assertIn("signed_eta", evidence)
        self.assertIn("symbolic_neural_ratio", evidence)
        self.assertEqual(evidence["descent_source"], "simulation_scheduler")
        self.assertTrue(universe.fusion_log)
        self.assertEqual(universe.fusion_log[-1]["civ_id"], "test-civ")
        self.assertEqual(universe.fusion_log[-1]["fitness_evidence"], evidence)

    def test_lineage_history_is_bounded(self):
        universe = Universe("bounded-lineage")
        universe.add_civilization("test-civ")
        universe.max_fusion_log = 2
        for _ in range(5):
            universe.simulate_cycle()
        self.assertLessEqual(len(universe.fusion_log), 2)
        self.assertLessEqual(len(universe.colony_snapshot()["fusion_history"]), 2)

    def test_promotion_transition_carries_same_evidence(self):
        universe = Universe("promotion-lineage")
        civ = universe.add_civilization("test-civ")
        civ["belief"]["truth"] = 1.0
        civ["resources"] = {"attention": 150, "compute": 40, "memory_nodes": 8}
        for _ in range(10):
            universe.simulate_cycle()
        for event in universe.promote_log:
            self.assertIn("fitness_evidence", event)
            self.assertIn("signed_eta", event["fitness_evidence"])


if __name__ == "__main__":
    unittest.main()
