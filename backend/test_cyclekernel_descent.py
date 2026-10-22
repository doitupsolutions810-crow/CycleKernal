import os
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
        self.assertIn("stress_residual_normalized", payload)
        self.assertIn("cycle_count", payload)


if __name__ == "__main__":
    unittest.main()
