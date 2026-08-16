"""Tests for MCP-2: bridge client extraction to bridge_mcp/client.py."""

from __future__ import annotations

import os
import pathlib
import tempfile
import unittest
from unittest import mock

from bridge_mcp.client import LAYOUT, PRODUCT_IDS, BridgeClient, resolve_runtime_bridge


class BridgeResolutionTests(unittest.TestCase):
    """Test bridge root resolution for DIY and product modes."""

    def test_explicit_path_overrides_env_and_default(self) -> None:
        """Explicit --bridge-root path takes precedence."""
        explicit = pathlib.Path("/tmp/custom-bridge")
        with mock.patch.dict(os.environ, {"CHATGPT_CODEX_IMESSAGE_BRIDGE": "/tmp/env-bridge"}):
            resolved = resolve_runtime_bridge(explicit_path=explicit)
            self.assertEqual(resolved, explicit)

    def test_env_var_overrides_default(self) -> None:
        """CHATGPT_CODEX_IMESSAGE_BRIDGE env var is used when no explicit path."""
        env_path = "/tmp/env-bridge"
        with mock.patch.dict(os.environ, {"CHATGPT_CODEX_IMESSAGE_BRIDGE": env_path}):
            resolved = resolve_runtime_bridge()
            self.assertEqual(resolved, pathlib.Path(env_path))

    def test_default_bridge_when_no_explicit_or_env(self) -> None:
        """DEFAULT_BRIDGE is used when no explicit path or env var."""
        with mock.patch.dict(os.environ, {}, clear=True):
            resolved = resolve_runtime_bridge()
            expected = pathlib.Path.home() / "Library" / "Application Support" / "ChatGPTCodexIMessage"
            self.assertEqual(resolved, expected)

    def test_product_mode_claude(self) -> None:
        """Product mode resolves to Bridge Pro/bridges/<product-id>."""
        resolved = resolve_runtime_bridge(product="claude")
        expected = pathlib.Path.home() / "Library" / "Application Support" / "Bridge Pro" / "bridges" / "claude"
        self.assertEqual(resolved, expected)

    def test_product_mode_grok(self) -> None:
        """Product mode grok resolves correctly."""
        resolved = resolve_runtime_bridge(product="grok")
        expected = pathlib.Path.home() / "Library" / "Application Support" / "Bridge Pro" / "bridges" / "grok"
        self.assertEqual(resolved, expected)

    def test_product_mode_openai(self) -> None:
        """Product mode openai resolves correctly."""
        resolved = resolve_runtime_bridge(product="openai")
        expected = pathlib.Path.home() / "Library" / "Application Support" / "Bridge Pro" / "bridges" / "openai"
        self.assertEqual(resolved, expected)

    def test_product_and_explicit_path_are_mutually_exclusive(self) -> None:
        """Providing both --product and --bridge-root raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            resolve_runtime_bridge(explicit_path="/tmp/custom", product="claude")
        self.assertIn("mutually exclusive", str(ctx.exception))

    def test_unknown_product_raises_error(self) -> None:
        """Unknown product ID raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            resolve_runtime_bridge(product="unknown-product")
        self.assertIn("Unknown product", str(ctx.exception))

    def test_layout_constant_has_expected_mappings(self) -> None:
        """PRODUCT_IDS constant contains expected product IDs."""
        self.assertIn("claude", PRODUCT_IDS)
        self.assertIn("grok", PRODUCT_IDS)
        self.assertIn("openai", PRODUCT_IDS)
        self.assertEqual(len(PRODUCT_IDS), 3)


class BridgeClientBackwardCompatTests(unittest.TestCase):
    """Test BridgeClient constructor still works as before."""

    def test_bridge_client_explicit_path(self) -> None:
        """BridgeClient accepts explicit bridge_root."""
        with tempfile.TemporaryDirectory() as tmpdir:
            bridge = pathlib.Path(tmpdir)
            client = BridgeClient(bridge_root=bridge)
            self.assertEqual(client.bridge_root, bridge)
            self.assertEqual(client.requests, bridge / "control" / "requests")
            self.assertEqual(client.responses, bridge / "control" / "responses")

    def test_bridge_client_env_fallback(self) -> None:
        """BridgeClient uses CHATGPT_CODEX_IMESSAGE_BRIDGE env when no explicit path."""
        env_path = "/tmp/env-bridge"
        with mock.patch.dict(os.environ, {"CHATGPT_CODEX_IMESSAGE_BRIDGE": env_path}):
            client = BridgeClient()
            self.assertEqual(client.bridge_root, pathlib.Path(env_path))

    def test_bridge_client_default_fallback(self) -> None:
        """BridgeClient uses DEFAULT_BRIDGE when no path or env."""
        with mock.patch.dict(os.environ, {}, clear=True):
            client = BridgeClient()
            expected = pathlib.Path.home() / "Library" / "Application Support" / "ChatGPTCodexIMessage"
            self.assertEqual(client.bridge_root, expected)


class ReexportTests(unittest.TestCase):
    """Test that plugin_server.bridge re-exports work."""

    def test_plugin_server_bridge_imports_work(self) -> None:
        """Existing imports from plugin_server.bridge still work."""
        from plugin_server.bridge import BridgeClient, BridgeError, DEFAULT_BRIDGE, MAX_RESPONSE_BYTES
        
        self.assertIsNotNone(BridgeClient)
        self.assertIsNotNone(BridgeError)
        self.assertIsNotNone(DEFAULT_BRIDGE)
        self.assertEqual(MAX_RESPONSE_BYTES, 16 * 1024 * 1024)

    def test_bridge_client_from_plugin_server_works(self) -> None:
        """BridgeClient from plugin_server.bridge is functional."""
        from plugin_server.bridge import BridgeClient
        
        with tempfile.TemporaryDirectory() as tmpdir:
            bridge = pathlib.Path(tmpdir)
            client = BridgeClient(bridge_root=bridge)
            self.assertEqual(client.bridge_root, bridge)


if __name__ == "__main__":
    unittest.main()
