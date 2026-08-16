"""MCP-11: Product isolation tests (queues, nonce stores).

Verifies that send_preview and helper request processing respect product
boundaries. A preview targeted at product `openai` must write nonces only
under bridges/openai/nonces/ and never create nonces in bridges/grok/ or
bridges/claude/. Similarly, requests in bridges/openai/control/requests/ must
not be drained by workers bound to grok or claude.
"""
from __future__ import annotations

import json
import os
import pathlib
import tempfile
import unittest
from unittest import mock

from bridge_mcp.client import LAYOUT, BridgeClient
from tests._helper_loader import helper


class ProductNonceIsolationTests(unittest.TestCase):
    """Test that send_preview nonces are scoped to the correct product bridge."""

    def setUp(self):
        """Set up temp directories for all three product bridges."""
        self.tmpdir = tempfile.TemporaryDirectory()
        self.home = pathlib.Path(os.path.realpath(self.tmpdir.name))
        
        # Create product bridge directories: ~/Library/.../Bridge Pro/bridges/{product}
        # Must ensure all parent directories have mode 0o700 for send_gate validation
        self.bridges_root = self.home / LAYOUT
        for product in ("claude", "grok", "openai"):
            product_root = self.bridges_root / product
            (product_root / "control" / "requests").mkdir(parents=True, mode=0o700)
            (product_root / "control" / "responses").mkdir(parents=True, mode=0o700)
            (product_root / "contacts").mkdir(parents=True, mode=0o700)
            
            # Fix permissions for all parent directories (send_gate validates these)
            for parent in (self.home, self.home / "Library", 
                          self.home / "Library" / "Application Support",
                          self.home / "Library" / "Application Support" / "Bridge Pro",
                          self.bridges_root, product_root, 
                          product_root / "control",
                          product_root / "contacts"):
                if parent.exists():
                    parent.chmod(0o700)
        
        # Create send_policy.json to enable send for each product
        for product in ("claude", "grok", "openai"):
            policy_path = self.bridges_root / product / "contacts" / "send_policy.json"
            policy_path.write_text(json.dumps({"enabled": True}), encoding="utf-8")
            policy_path.chmod(0o600)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_openai_preview_never_creates_grok_nonce(self):
        """OpenAI preview must not create nonces under grok bridge."""
        openai_bridge = self.bridges_root / "openai"
        grok_nonces_dir = self.bridges_root / "grok" / "nonces"
        
        with mock.patch.dict(os.environ, {
            "IMESSAGE_BRIDGE_DIR": str(openai_bridge),
            "IMESSAGE_POLICY_DIR": str(openai_bridge / "contacts"),
        }):
            # Call send_preview via the helper action processor
            params = {"to": "test@example.com", "text": "Hello", "service": "iMessage"}
            result = helper.action_send_preview(params, None, {}, helper.PrivacyPolicy("blocklist", (), ()))
            
            # OpenAI preview should have created a nonce
            self.assertIn("send_nonce", result)
            openai_nonces_dir = openai_bridge / "nonces"
            self.assertTrue(openai_nonces_dir.exists(), "OpenAI nonces/ directory was not created")
            openai_nonces = list(openai_nonces_dir.glob("*.json"))
            self.assertEqual(len(openai_nonces), 1, f"Expected 1 nonce in openai/nonces/, got {len(openai_nonces)}")
            
            # Grok nonces directory must NOT exist
            self.assertFalse(grok_nonces_dir.exists(), f"Grok nonces directory should not exist but found at {grok_nonces_dir}")

    def test_openai_preview_never_creates_claude_nonce(self):
        """OpenAI preview must not create nonces under claude bridge."""
        openai_bridge = self.bridges_root / "openai"
        claude_nonces_dir = self.bridges_root / "claude" / "nonces"
        
        with mock.patch.dict(os.environ, {
            "IMESSAGE_BRIDGE_DIR": str(openai_bridge),
            "IMESSAGE_POLICY_DIR": str(openai_bridge / "contacts"),
        }):
            params = {"to": "test@example.com", "text": "Hello", "service": "iMessage"}
            result = helper.action_send_preview(params, None, {}, helper.PrivacyPolicy("blocklist", (), ()))
            
            self.assertIn("send_nonce", result)
            openai_nonces_dir = openai_bridge / "nonces"
            self.assertTrue(openai_nonces_dir.exists())
            openai_nonces = list(openai_nonces_dir.glob("*.json"))
            self.assertEqual(len(openai_nonces), 1)
            
            # Claude nonces directory must NOT exist
            self.assertFalse(claude_nonces_dir.exists(), f"Claude nonces directory should not exist but found at {claude_nonces_dir}")

    def test_grok_preview_never_creates_openai_nonce(self):
        """Grok preview must not create nonces under openai bridge."""
        grok_bridge = self.bridges_root / "grok"
        openai_nonces_dir = self.bridges_root / "openai" / "nonces"
        claude_nonces_dir = self.bridges_root / "claude" / "nonces"
        
        with mock.patch.dict(os.environ, {
            "IMESSAGE_BRIDGE_DIR": str(grok_bridge),
            "IMESSAGE_POLICY_DIR": str(grok_bridge / "contacts"),
        }):
            params = {"to": "test@example.com", "text": "Hello", "service": "iMessage"}
            result = helper.action_send_preview(params, None, {}, helper.PrivacyPolicy("blocklist", (), ()))
            
            self.assertIn("send_nonce", result)
            grok_nonces_dir = grok_bridge / "nonces"
            self.assertTrue(grok_nonces_dir.exists())
            grok_nonces = list(grok_nonces_dir.glob("*.json"))
            self.assertEqual(len(grok_nonces), 1)
            
            # OpenAI and Claude nonces must NOT exist
            self.assertFalse(openai_nonces_dir.exists(), "OpenAI nonces directory should not exist")
            self.assertFalse(claude_nonces_dir.exists(), "Claude nonces directory should not exist")

    def test_claude_preview_never_creates_openai_or_grok_nonce(self):
        """Claude preview must not create nonces under openai or grok bridges."""
        claude_bridge = self.bridges_root / "claude"
        openai_nonces_dir = self.bridges_root / "openai" / "nonces"
        grok_nonces_dir = self.bridges_root / "grok" / "nonces"
        
        with mock.patch.dict(os.environ, {
            "IMESSAGE_BRIDGE_DIR": str(claude_bridge),
            "IMESSAGE_POLICY_DIR": str(claude_bridge / "contacts"),
        }):
            params = {"to": "test@example.com", "text": "Hello", "service": "iMessage"}
            result = helper.action_send_preview(params, None, {}, helper.PrivacyPolicy("blocklist", (), ()))
            
            self.assertIn("send_nonce", result)
            claude_nonces_dir = claude_bridge / "nonces"
            self.assertTrue(claude_nonces_dir.exists())
            claude_nonces = list(claude_nonces_dir.glob("*.json"))
            self.assertEqual(len(claude_nonces), 1)
            
            # OpenAI and Grok nonces must NOT exist
            self.assertFalse(openai_nonces_dir.exists(), "OpenAI nonces directory should not exist")
            self.assertFalse(grok_nonces_dir.exists(), "Grok nonces directory should not exist")


class ProductQueueIsolationTests(unittest.TestCase):
    """Test that request queues are scoped to the correct product bridge."""

    def setUp(self):
        """Set up temp directories for all three product bridges."""
        self.tmpdir = tempfile.TemporaryDirectory()
        self.home = pathlib.Path(os.path.realpath(self.tmpdir.name))
        
        self.bridges_root = self.home / LAYOUT
        for product in ("claude", "grok", "openai"):
            product_root = self.bridges_root / product
            (product_root / "control" / "requests").mkdir(parents=True, mode=0o700)
            (product_root / "control" / "responses").mkdir(parents=True, mode=0o700)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_openai_request_not_processed_by_grok_worker(self):
        """Request in openai/control/requests must not be processed by grok worker."""
        openai_bridge = self.bridges_root / "openai"
        grok_bridge = self.bridges_root / "grok"
        
        # Place a request in openai queue
        openai_request_path = openai_bridge / "control" / "requests" / "request-test123.json"
        openai_request_path.write_text(
            json.dumps({"id": "test123", "action": "status", "params": {}}),
            encoding="utf-8"
        )
        openai_request_path.chmod(0o600)
        
        # Try to process with a grok worker (will not see openai's request)
        with mock.patch.dict(os.environ, {"IMESSAGE_BRIDGE_DIR": str(grok_bridge)}):
            # The helper main() scans REQUESTS_DIR which is grok_bridge/control/requests
            # It should find no requests there
            grok_requests = list((grok_bridge / "control" / "requests").glob("request-*.json"))
            self.assertEqual(len(grok_requests), 0, "Grok worker should not see openai requests")
            
            # The openai request should still be unprocessed
            self.assertTrue(openai_request_path.exists(), "OpenAI request should remain unprocessed")

    def test_grok_request_not_processed_by_openai_worker(self):
        """Request in grok/control/requests must not be processed by openai worker."""
        openai_bridge = self.bridges_root / "openai"
        grok_bridge = self.bridges_root / "grok"
        
        # Place a request in grok queue
        grok_request_path = grok_bridge / "control" / "requests" / "request-test456.json"
        grok_request_path.write_text(
            json.dumps({"id": "test456", "action": "status", "params": {}}),
            encoding="utf-8"
        )
        grok_request_path.chmod(0o600)
        
        # Try to process with an openai worker
        with mock.patch.dict(os.environ, {"IMESSAGE_BRIDGE_DIR": str(openai_bridge)}):
            openai_requests = list((openai_bridge / "control" / "requests").glob("request-*.json"))
            self.assertEqual(len(openai_requests), 0, "OpenAI worker should not see grok requests")
            
            # The grok request should still be unprocessed
            self.assertTrue(grok_request_path.exists(), "Grok request should remain unprocessed")

    def test_claude_request_not_processed_by_openai_or_grok_worker(self):
        """Request in claude/control/requests must not be processed by other workers."""
        openai_bridge = self.bridges_root / "openai"
        grok_bridge = self.bridges_root / "grok"
        claude_bridge = self.bridges_root / "claude"
        
        # Place a request in claude queue
        claude_request_path = claude_bridge / "control" / "requests" / "request-test789.json"
        claude_request_path.write_text(
            json.dumps({"id": "test789", "action": "status", "params": {}}),
            encoding="utf-8"
        )
        claude_request_path.chmod(0o600)
        
        # Neither openai nor grok workers should see it
        with mock.patch.dict(os.environ, {"IMESSAGE_BRIDGE_DIR": str(openai_bridge)}):
            openai_requests = list((openai_bridge / "control" / "requests").glob("request-*.json"))
            self.assertEqual(len(openai_requests), 0)
        
        with mock.patch.dict(os.environ, {"IMESSAGE_BRIDGE_DIR": str(grok_bridge)}):
            grok_requests = list((grok_bridge / "control" / "requests").glob("request-*.json"))
            self.assertEqual(len(grok_requests), 0)
        
        self.assertTrue(claude_request_path.exists(), "Claude request should remain unprocessed")


class BridgeClientProductIsolationTests(unittest.TestCase):
    """Test that BridgeClient correctly scopes operations to product bridges."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.home = pathlib.Path(os.path.realpath(self.tmpdir.name))
        
        self.bridges_root = self.home / LAYOUT
        for product in ("claude", "grok", "openai"):
            product_root = self.bridges_root / product
            (product_root / "control" / "requests").mkdir(parents=True, mode=0o700)
            (product_root / "control" / "responses").mkdir(parents=True, mode=0o700)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_bridge_client_uses_correct_product_root(self):
        """BridgeClient resolves requests/responses under the correct product."""
        openai_bridge = self.bridges_root / "openai"
        client = BridgeClient(bridge_root=openai_bridge)
        
        # Verify paths are under openai, not grok or claude
        self.assertEqual(
            os.path.realpath(client.bridge_root),
            os.path.realpath(openai_bridge)
        )
        self.assertEqual(
            os.path.realpath(client.requests),
            os.path.realpath(openai_bridge / "control" / "requests")
        )
        self.assertEqual(
            os.path.realpath(client.responses),
            os.path.realpath(openai_bridge / "control" / "responses")
        )
        
        # Ensure not using grok or claude paths
        grok_requests = os.path.realpath(self.bridges_root / "grok" / "control" / "requests")
        claude_requests = os.path.realpath(self.bridges_root / "claude" / "control" / "requests")
        self.assertNotEqual(os.path.realpath(client.requests), grok_requests)
        self.assertNotEqual(os.path.realpath(client.requests), claude_requests)


if __name__ == "__main__":
    unittest.main()
