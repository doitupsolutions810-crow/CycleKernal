import os
from threading import Event, Thread
import unittest
from unittest.mock import patch

from simulation_core import Universe, app, kernel


class CycleKernalDescentIntegrationTests(unittest.TestCase):
    def test_one_descent_tick_and_fusion_receipt_per_universe_cycle(self):
        universe = Universe("test-universe")
        civ = universe.add_civilization("test-civ")
        universe.simulate_cycle()
        self.assertEqual(universe.descent_engine.t, 1)
        self.assertIn("stress_residual", civ)
        self.assertIn("stress_residual_normalized", civ)
        self.assertIn("neural_entropy_used", civ)
        self.assertGreaterEqual(civ["neural_entropy_used"], 0.0)
        self.assertLessEqual(civ["neural_entropy_used"], 1.0)
        evidence = civ["fitness_evidence"]
        self.assertIn("symbolic_score", evidence)
        self.assertIn("neural_score", evidence)
        self.assertEqual(evidence["descent_source"], "simulation_scheduler")
        self.assertEqual(len(universe.fusion_log), 1)
        self.assertEqual(universe.fusion_log[0]["civ_id"], "test-civ")
        self.assertEqual(universe.fusion_log[0]["fusion_state_id"], civ["fusion_state_id"])
        self.assertEqual(evidence["fusion_state_id"], civ["fusion_state_id"])
        self.assertEqual(evidence["metric_source"], "simulation_scheduler")
        self.assertEqual(universe.fusion_log[0]["fitness_evidence"], evidence)

        # The recorded inputs must be the values actually used by the scheduler,
        # not the evidence builder's fallback defaults.
        symbolic = evidence["inputs"]["symbolic"]
        neural = evidence["inputs"]["neural"]
        witness = evidence["fusion_state_witness"]
        self.assertEqual(symbolic["truth"], civ["belief"]["truth"])
        self.assertEqual(symbolic["deception"], civ["belief"]["deception"])
        self.assertEqual(symbolic["attention"], civ["resources"]["attention"])
        self.assertEqual(symbolic["compute"], civ["resources"]["compute"])
        self.assertEqual(symbolic["memory_nodes"], civ["resources"]["memory_nodes"])
        self.assertTrue(all(symbolic["field_presence"].values()))
        self.assertEqual(symbolic["belief_source"], "provided")
        self.assertEqual(symbolic["resource_source"], "provided")
        self.assertEqual(neural["core"], civ["belief"]["truth"])
        self.assertEqual(neural["base_entropy"], 0.15)
        self.assertEqual(neural["coupling"], 0.02)
        self.assertEqual(witness["belief_truth"], symbolic["truth"])
        self.assertEqual(witness["resource_attention"], symbolic["attention"])
        self.assertEqual(witness["resource_compute"], symbolic["compute"])
        self.assertEqual(witness["resource_memory_nodes"], symbolic["memory_nodes"])
        self.assertEqual(witness["belief_deception"], symbolic["deception"])

    def test_fusion_lineage_is_bounded_and_in_snapshots(self):
        universe = Universe("bounded-lineage")
        universe.add_civilization("test-civ")
        universe.max_fusion_log = 2
        for _ in range(5):
            universe.simulate_cycle()
        snapshot = universe.colony_snapshot()
        self.assertLessEqual(len(universe.fusion_log), 2)
        self.assertLessEqual(len(snapshot["fusion_history"]), 2)
        self.assertIn("fitness_evidence", snapshot["members"][0])

    def test_promotion_transition_carries_companion_evidence(self):
        universe = Universe("promotion-lineage")
        civ = universe.add_civilization("test-civ")
        civ["belief"]["truth"] = 1.0
        civ["resources"] = {"attention": 150, "compute": 40, "memory_nodes": 8}
        universe.simulate_cycle()
        promoted_events = [event for event in universe.promote_log if event["action"] == "promote"]
        self.assertEqual(len(promoted_events), 1, "high-evidence fixture should promote on the first cycle")
        evidence = promoted_events[0]["fitness_evidence"]
        self.assertEqual(evidence, civ["fitness_evidence"])
        self.assertEqual(evidence["descent_source"], "simulation_scheduler")
        self.assertEqual(evidence["metric_source"], "simulation_scheduler")
        self.assertEqual(evidence["fusion_state_id"], civ["fusion_state_id"])
        self.assertIn("signed_eta", evidence)
        self.assertIn("threshold_margins", evidence)

    def test_scale_snapshot_is_atomic_with_scheduler_updates(self):
        universe = Universe("test-universe")
        tick_started = Event()
        release_tick = Event()
        snapshot_started = Event()
        snapshot_done = Event()
        snapshots = []
        original_tick = universe.descent_engine.tick

        def delayed_tick():
            tick_started.set()
            if not release_tick.wait(2):
                raise TimeoutError("test did not release descent tick")
            return original_tick()

        def read_snapshot():
            snapshot_started.set()
            snapshots.append(universe.scale_state_snapshot())
            snapshot_done.set()

        universe.descent_engine.tick = delayed_tick
        scheduler = Thread(target=universe.simulate_cycle)
        reader = Thread(target=read_snapshot)
        scheduler.start()
        try:
            self.assertTrue(tick_started.wait(2))
            reader.start()
            self.assertTrue(snapshot_started.wait(2))
            self.assertFalse(snapshot_done.wait(0.05))
        finally:
            release_tick.set()
            scheduler.join(2)
            if reader.ident is not None:
                reader.join(2)

        self.assertFalse(scheduler.is_alive())
        self.assertFalse(reader.is_alive())
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0]["cycle_count"], snapshots[0]["t"])

    def test_colony_snapshot_waits_for_fusion_and_lineage_completion(self):
        universe = Universe("atomic-colony")
        civ = universe.add_civilization("test-civ")
        cycle_complete = Event()
        release_cycle = Event()
        snapshot_started = Event()
        snapshot_done = Event()
        snapshots = []
        original_cycle = universe._simulate_cycle_locked

        def delayed_cycle():
            original_cycle()
            cycle_complete.set()
            if not release_cycle.wait(2):
                raise TimeoutError("test did not release complete cycle")

        def read_snapshot():
            snapshot_started.set()
            snapshots.append(universe.colony_snapshot())
            snapshot_done.set()

        universe._simulate_cycle_locked = delayed_cycle
        runner = Thread(target=universe.simulate_cycle)
        reader = Thread(target=read_snapshot)
        runner.start()
        try:
            self.assertTrue(cycle_complete.wait(2))
            reader.start()
            self.assertTrue(snapshot_started.wait(2))
            self.assertFalse(snapshot_done.wait(0.05))
        finally:
            release_cycle.set()
            runner.join(2)
            if reader.ident is not None:
                reader.join(2)

        self.assertFalse(runner.is_alive())
        self.assertFalse(reader.is_alive())
        self.assertEqual(len(snapshots), 1)
        snap = snapshots[0]
        self.assertEqual(snap["cycle_count"], universe.cycle_count)
        self.assertEqual(snap["fusion_history"][-1]["cycle"], snap["cycle_count"])
        member = next(row for row in snap["members"] if row["id"] == "test-civ")
        self.assertEqual(member["fusion_state_id"], member["fitness_evidence"]["fusion_state_id"])
        self.assertEqual(snap["fusion_history"][-1]["fusion_state_id"], member["fusion_state_id"])
        self.assertEqual(civ["fusion_state_id"], member["fusion_state_id"])

    def test_cycle_kernel_state_contains_cycle_aligned_descent_and_lineage(self):
        kernel.run_simulation(1)
        state = kernel.get_state()
        universe = state["universes"]["U1"]
        self.assertIn("descent", universe)
        self.assertEqual(universe["descent"]["schema"], "great-scale.descent/v0.4.2")
        self.assertEqual(universe["cycle_count"], universe["descent"]["t"])
        self.assertEqual(universe["cycle_count"], universe["colony"]["cycle_count"])
        self.assertTrue(universe["colony"]["fusion_history"])
        latest = universe["colony"]["fusion_history"][-1]
        member = next(row for row in universe["colony"]["members"] if row["id"] == latest["civ_id"])
        self.assertEqual(latest["fusion_state_id"], member["fusion_state_id"])
        self.assertEqual(latest["fitness_evidence"]["fusion_state_id"], member["fitness_evidence"]["fusion_state_id"])

    def test_state_snapshot_is_detached_from_live_nested_dictionaries(self):
        universe = Universe("detached-state")
        civ = universe.add_civilization("test-civ")
        universe.simulate_cycle()
        before = civ["belief"]["truth"]
        snapshot = universe.state_snapshot()
        snapshot["civilizations"]["test-civ"]["belief"]["truth"] = 0.123
        snapshot["colony"]["members"][0]["fitness_evidence"]["symbolic_score"] = -1
        after = universe.state_snapshot()
        self.assertEqual(civ["belief"]["truth"], before)
        self.assertNotEqual(after["civilizations"]["test-civ"]["belief"]["truth"], 0.123)
        self.assertGreaterEqual(after["colony"]["members"][0]["fitness_evidence"]["symbolic_score"], 0.0)

    def test_scale_state_endpoint_fails_closed_without_token(self):
        client = app.test_client()
        with patch.dict(os.environ, {"SCALE_API_TOKEN": ""}, clear=False):
            response = client.get("/api/v1/scale/state")
        self.assertEqual(response.status_code, 503)

    def test_scale_state_endpoint_rejects_bad_token(self):
        client = app.test_client()
        with patch.dict(os.environ, {"SCALE_API_TOKEN": "test-secret"}, clear=False):
            response = client.get("/api/v1/scale/state", headers={"Authorization": "Bearer wrong"})
        self.assertEqual(response.status_code, 401)

    def test_scale_state_endpoint_returns_snapshot_with_token(self):
        client = app.test_client()
        with patch.dict(os.environ, {"SCALE_API_TOKEN": "test-secret"}, clear=False):
            response = client.get("/api/v1/scale/state", headers={"Authorization": "Bearer test-secret"})
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["schema"], "great-scale.descent/v0.4.2")
        self.assertIn("stress_residual_normalized", payload)
        self.assertIn("cycle_count", payload)
        self.assertEqual(payload["universe_id"], "U1")
        self.assertEqual(payload["cycle_count"], payload["t"])


if __name__ == "__main__":
    unittest.main()
