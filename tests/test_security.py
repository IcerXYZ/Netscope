import json
import os
import tempfile
import unittest
from unittest.mock import patch
from werkzeug.security import generate_password_hash
import app as netscope

class NetScopeSecurityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.tokens = os.path.join(self.temp.name, "agents.json")
        with open(self.tokens, "w", encoding="utf-8") as handle:
            json.dump({"node-01": generate_password_hash("agent-secret", method="scrypt")}, handle)
        self.env = patch.dict(os.environ, {
            "NETSCOPE_AUTH_ENABLED": "true",
            "NETSCOPE_AUTH_USERNAME": "admin",
            "NETSCOPE_AUTH_PASSWORD_HASH": generate_password_hash("dashboard-password", method="scrypt"),
            "NETSCOPE_AGENT_TOKENS_FILE": self.tokens,
        })
        self.env.start()
        netscope._last_local_status = None
        netscope.app.config.update(TESTING=True, SECRET_KEY="test-secret")
        self.client = netscope.app.test_client()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def test_dashboard_redirects_to_login(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.location)

    def test_api_requires_dashboard_login(self):
        response = self.client.get("/api/cluster")
        self.assertEqual(response.status_code, 401)

    def test_login_accepts_valid_credentials(self):
        response = self.client.post("/login", data={"username":"admin","password":"dashboard-password"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get("/").status_code, 200)

    def test_agent_report_requires_unique_valid_token(self):
        payload={"agent_id":"node-01","name":"node-01","data":{"hostname":"node-01"}}
        bad=self.client.post("/api/agent/report", json=payload, headers={"X-NetScope-Token":"wrong"})
        self.assertEqual(bad.status_code, 401)
        good=self.client.post("/api/agent/report", json=payload, headers={"X-NetScope-Token":"agent-secret"})
        self.assertEqual(good.status_code, 200)

    def test_logout_control_hidden_when_authentication_is_disabled(self):
        with patch.dict(os.environ, {"NETSCOPE_AUTH_ENABLED": "false"}):
            response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b'action="/logout"', response.data)

    def test_cluster_reuses_latest_local_sample_instead_of_resetting_traffic_rate(self):
        cached={"hostname":"central-01","interfaces":[{"rx_rate":123.0}]}
        netscope._last_local_status=cached
        with patch.dict(os.environ, {"NETSCOPE_AUTH_ENABLED":"false","NETSCOPE_ROLE":"server"}), patch.object(netscope,"get_local_status") as collect:
            response=self.client.get("/api/cluster")
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.get_json()["nodes"][0]["data"],cached)
        collect.assert_not_called()

    def test_cluster_refreshes_expired_local_status(self):
        netscope._last_local_status={"hostname":"old","timestamp":1}
        fresh={"hostname":"current","timestamp":100}
        with patch.dict(os.environ, {"NETSCOPE_AUTH_ENABLED":"false","NETSCOPE_ROLE":"server"}), \
             patch.object(netscope,"get_local_status",return_value=fresh) as collect:
            response=self.client.get("/api/cluster")
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.get_json()["nodes"][0]["data"],fresh)
        collect.assert_called_once()
        self.assertEqual(netscope._last_local_status,fresh)

    def test_health_is_public_and_has_security_headers(self):
        response=self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("X-Frame-Options"), "DENY")
        self.assertIn("Content-Security-Policy", response.headers)

if __name__ == "__main__":
    unittest.main()
