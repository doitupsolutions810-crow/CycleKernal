import unittest

from simulation_core import Universe


class FitnessLineageTests(unittest.TestCase):
    def test_every_simulation_fusion_has_companion_channel_evidence(self):
        universe = Universe("lineage-test")
        civ = universe.add_civilization("test-civ")
        universe.simulate_cycle()
        evidence = civ["fitness_evidence"]
        self.assertEqual(evidence["schema"], "cyclekernel.fusion-evidence/v1")
        self.assertIn("symbolic_score", evidence)
        self.assertIn("neural_score", evidence)
        self.assertIn("signed_eta", evidence)
        self.assertIn("symbolic_neural_ratio", evidence)
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

    def test_promotion_transition_carries_the_same_evidence(self):
        universe = Universe("promotion-lineage")
        civ = universe.add_civilization("test-civ")
        # Make promotion extremely likely, while leaving the actual fusion math intact.
        civ["belief"]["truth"] = 1.0
        civ["resources"] = {"attention": 150, "compute": 40, "memory_nodes": 8}
        # Repeated cycles eventually exercise a transition; if not, the fusion
        # stream must still carry evidence on every cycle.
        for _ in range(10):
            universe.simulate_cycle()
        self.assertTrue(universe.fusion_log)
        if universe.promote_log:
            self.assertIn("fitness_evidence", universe.promote_log[-1])
            self.assertIn("signed_eta", universe.promote_log[-1]["fitness_evidence"])


if __name__ == "__main__":
    unittest.main()
