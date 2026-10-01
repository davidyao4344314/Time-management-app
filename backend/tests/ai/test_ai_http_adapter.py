"""The original app mounts the extracted AI routes without changing their URLs."""

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend import fastapi_test
from backend.app.api import ai


class AIHTTPAdapterTests(unittest.TestCase):
    def test_ai_routes_are_mounted_once_and_owned_by_adapter(self):
        expected = {
            ("/ai/config/status", "GET"), ("/ai/config", "POST"),
            ("/ai/model-config", "GET"), ("/ai/model-config", "PUT"),
            ("/ai/memory-config", "GET"), ("/ai/memory-config", "PUT"),
            ("/ai/test-observation", "POST"), ("/ai/propose", "POST"),
        }
        routes = [route for route in fastapi_test.app.routes
                  if route.path.startswith("/ai/")]
        self.assertEqual(len(routes), len(expected))
        self.assertEqual({(route.path, next(iter(route.methods))) for route in routes}, expected)
        self.assertTrue(all(route.endpoint.__module__ == ai.__name__ for route in routes))
        self.assertIs(fastapi_test.get_agent_proposal, ai.get_agent_proposal)

    def test_status_exposes_only_a_boolean_through_both_entry_points(self):
        with patch.object(fastapi_test, "is_openai_api_key_configured", return_value=True):
            response = TestClient(fastapi_test.app).get("/ai/config/status")
            self.assertEqual(response.json(), {"configured": True})
            self.assertEqual(ai.ai_config_status(), {"configured": True})


if __name__ == "__main__":
    unittest.main()
