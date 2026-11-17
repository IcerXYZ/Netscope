import contextlib
import io
import json
import os
import tempfile
import unittest
from unittest.mock import patch

import agent_tokens
from werkzeug.security import check_password_hash


class AgentTokenCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.temp.name, "agents.json")
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("{}")

    def tearDown(self):
        self.temp.cleanup()

    def run_cli(self, *args):
        output = io.StringIO()
        with patch.dict(os.environ, {"NETSCOPE_AGENT_TOKENS_FILE": self.path}), \
             patch("agent_tokens.os.chown"), \
             contextlib.redirect_stdout(output):
            result = agent_tokens.main(list(args))
        return result, output.getvalue()

    def test_empty_registry_is_treated_as_no_agents(self):
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("")
        self.assertEqual(agent_tokens.read_tokens(self.path), {})

    def test_invalid_registry_is_not_silently_overwritten(self):
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("{broken")
        with self.assertRaises(RuntimeError):
            agent_tokens.read_tokens(self.path)
        with open(self.path, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "{broken")

    def test_add_creates_a_hashed_token_and_displays_raw_token_once(self):
        result, output = self.run_cli("add", "node-01")
        self.assertEqual(result, 0)
        self.assertIn("Agent token (shown once", output)
        raw_token = output.splitlines()[2]
        with open(self.path, encoding="utf-8") as handle:
            registry = json.load(handle)
        self.assertEqual(list(registry), ["node-01"])
        self.assertTrue(check_password_hash(registry["node-01"], raw_token))
        self.assertNotEqual(registry["node-01"], raw_token)

    def test_duplicate_agent_id_is_rejected_without_replacing_token(self):
        self.run_cli("add", "node-01")
        with open(self.path, encoding="utf-8") as handle:
            before = json.load(handle)
        with self.assertRaises(SystemExit):
            self.run_cli("add", "node-01")
        with open(self.path, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), before)

    def test_revoke_removes_agent(self):
        self.run_cli("add", "node-01")
        result, output = self.run_cli("revoke", "node-01")
        self.assertEqual(result, 0)
        self.assertIn("Revoked agent: node-01", output)
        self.assertEqual(agent_tokens.read_tokens(self.path), {})

    def test_list_empty_registry_gives_next_step(self):
        result, output = self.run_cli("list")
        self.assertEqual(result, 0)
        self.assertIn("No agents enrolled yet", output)


if __name__ == "__main__":
    unittest.main()
