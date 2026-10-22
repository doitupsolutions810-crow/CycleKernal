import os
from threading import Event, Thread
import unittest
from unittest.mock import patch

from simulation_core import Universe, app, kernel


class CycleKernalDescentIntegrationTests(unittest.TestCase):
    def test_one_descent_tick_per_universe_cycle(self):
        universe = Universe("test-universe")
        civ = universe.add_civilization("test-civ")
        universe.simulate_cycle()
        self.assertEqual(universe.descent_engine.t, 1)
        self.assertIn("stress_residual", civ)
        self.assertIn("stress_residual_normalized", civ)
        self.assertIn("neural_entropy_used", civ)
        self.assertGreaterEqual(civ["neural_entropy_used"], 0.0)
        self.assertLessEqual(civ["neural_entropy_used"], 1.0)

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

    def test_cycle_kernel_state_contains_descent_snapshot(self):
        kernel.run_simulation(1)
        state = kernel.get_state()
        self.assertIn("descent", state["universes"]["U1"])
        self.assertEqual(state["universes"]["U1"]["descent"]["schema"], "great-scale.descent/v0.4.2")

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
        self.assertEqual(payload["sourceVersion"], "great-scale/public/scale.js@a0fd4b10b964932f90abf7004bbe7e28687168d1")
        self.assertIn("stress_residual_normalized", payload)
        self.assertIn("cycle_count", payload)
        self.assertEqual(payload["universe_id"], "U1")
        self.assertEqual(payload["cycle_count"], payload["t"])


if __name__ == "__main__":
    unittest.main()
