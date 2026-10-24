import unittest

from simulation_core import Universe
from ns_fusion import fitness_state_id, promotion_decision_state_id


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
        self.assertEqual(universe.fusion_log[-1]["fusion_state_id"], civ["fusion_state_id"])
        self.assertEqual(evidence["fusion_state_id"], civ["fusion_state_id"])
        self.assertEqual(fitness_state_id(evidence["fusion_state_witness"]), civ["fusion_state_id"])
        self.assertEqual(universe.fusion_log[-1]["fitness_evidence"], evidence)
        self.assertEqual(civ["promotion_decision_id"], evidence["promotion_decision_id"])
        self.assertEqual(
            promotion_decision_state_id(evidence["promotion_decision_witness"]),
            evidence["promotion_decision_id"],
        )
        self.assertEqual(
            evidence["promotion_decision_witness"]["action"],
            universe.fusion_log[-1]["action"],
        )
        self.assertFalse(evidence["promotion_decision_witness"]["already_promoted"])
        self.assertEqual(evidence["promotion_decision_witness"]["threshold"], 0.62)
        self.assertEqual(
            universe.fusion_log[-1]["promotion_decision_id"],
            evidence["promotion_decision_id"],
        )
        symbolic = evidence["inputs"]["symbolic"]
        witness = evidence["fusion_state_witness"]
        self.assertTrue(all(symbolic["field_presence"].values()))
        self.assertEqual(symbolic["belief_source"], "provided")
        self.assertEqual(symbolic["resource_source"], "provided")
        self.assertEqual(symbolic["truth"], civ["belief"]["truth"])
        self.assertEqual(symbolic["deception"], civ["belief"]["deception"])
        self.assertEqual(symbolic["attention"], civ["resources"]["attention"])
        self.assertEqual(symbolic["compute"], civ["resources"]["compute"])
        self.assertEqual(symbolic["memory_nodes"], civ["resources"]["memory_nodes"])
        self.assertEqual(witness["belief_truth"], symbolic["truth"])
        self.assertEqual(witness["belief_deception"], symbolic["deception"])
        self.assertEqual(witness["resource_attention"], symbolic["attention"])
        self.assertEqual(witness["resource_compute"], symbolic["compute"])
        self.assertEqual(witness["resource_memory_nodes"], symbolic["memory_nodes"])

    def test_lineage_history_is_bounded(self):
        universe = Universe("bounded-lineage")
        civ = universe.add_civilization("test-civ")
        universe.max_fusion_log = 2
        universe.max_promotion_log = 2
        for cycle in range(6):
            if cycle % 2 == 0:
                civ["belief"]["truth"] = 1.0
                civ["resources"] = {"attention": 150, "compute": 40, "memory_nodes": 8}
                civ["promoted"] = False
                civ["state"] = "active"
            else:
                civ["belief"]["truth"] = 0.0
                civ["resources"] = {"attention": 0, "compute": 0, "memory_nodes": 0}
                civ["promoted"] = True
                civ["state"] = "promoted"
            universe.simulate_cycle()
        snapshot = universe.colony_snapshot()
        self.assertLessEqual(len(universe.fusion_log), 2)
        self.assertLessEqual(len(universe.promote_log), 2)
        self.assertLessEqual(len(snapshot["fusion_history"]), 2)
        self.assertLessEqual(len(snapshot["promotion_history"]), 2)
        self.assertEqual(len(universe.promote_log), 2)

    def test_promotion_transition_carries_same_evidence(self):
        universe = Universe("promotion-lineage")
        civ = universe.add_civilization("test-civ")
        civ["belief"]["truth"] = 1.0
        civ["resources"] = {"attention": 150, "compute": 40, "memory_nodes": 8}
        universe.simulate_cycle()
        promoted_events = [event for event in universe.promote_log if event["action"] == "promote"]
        self.assertEqual(len(promoted_events), 1, "high-evidence test fixture should promote on the first cycle")
        evidence = promoted_events[0]["fitness_evidence"]
        self.assertEqual(promoted_events[0]["fusion_state_id"], civ["fusion_state_id"])
        self.assertEqual(promoted_events[0]["promotion_decision_id"], civ["promotion_decision_id"])
        self.assertEqual(evidence["promotion_decision_witness"]["action"], "promote")
        self.assertFalse(evidence["promotion_decision_witness"]["already_promoted"])
        self.assertEqual(evidence["promotion_decision_witness"]["threshold"], 0.62)
        self.assertEqual(
            fitness_state_id(evidence["promotion_decision_witness"]),
            evidence["promotion_decision_id"],
        )
        self.assertEqual(evidence["fusion_state_id"], civ["fusion_state_id"])
        self.assertEqual(evidence, civ["fitness_evidence"])
        self.assertEqual(evidence["descent_source"], "simulation_scheduler")
        self.assertIn("signed_eta", evidence)
        self.assertIn("threshold_margins", evidence)
        self.assertEqual(fitness_state_id(evidence["fusion_state_witness"]), civ["fusion_state_id"])


if __name__ == "__main__":
    unittest.main()
