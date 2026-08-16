"""MCP-7: Python-level egress test.

Verifies that helper.py, send_gate.py, and bridge_mcp/ modules do not open
network connections. Static analysis checks for forbidden imports; dynamic
tests verify no sockets are created during import and basic operations.
"""
from __future__ import annotations

import ast
import importlib.util
import sys
import unittest
from pathlib import Path
from typing import Set
from unittest import mock

from tests._helper_loader import REPO_ROOT


# Network-related modules that are forbidden in the MCP bridge layer
FORBIDDEN_NETWORK_IMPORTS = {
    "socket",
    "ssl",
    "http",
    "http.client",
    "http.server",
    "urllib",
    "urllib.request",
    "urllib.error",
    "urllib.parse",
    "urllib.robotparser",
    "requests",
    "httpx",
    "aiohttp",
    "websocket",
    "websockets",
    "ftplib",
    "poplib",
    "imaplib",
    "nntplib",
    "smtplib",
    "telnetlib",
    "xmlrpc",
    "xmlrpc.client",
}


class StaticEgressAnalyzer(ast.NodeVisitor):
    """AST visitor that collects all imported modules."""

    def __init__(self) -> None:
        self.imports: Set[str] = set()

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            # Store the base module name
            base = alias.name.split(".")[0]
            self.imports.add(base)
            # Also store the full name for submodule checks
            self.imports.add(alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            base = node.module.split(".")[0]
            self.imports.add(base)
            self.imports.add(node.module)
        self.generic_visit(node)


def analyze_file_imports(path: Path) -> Set[str]:
    """Parse a Python file and return all imported module names."""
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    analyzer = StaticEgressAnalyzer()
    analyzer.visit(tree)
    return analyzer.imports


class StaticEgressTest(unittest.TestCase):
    """Static analysis: verify no forbidden network imports in bridge code."""

    def _check_file_has_no_network_imports(self, path: Path, label: str) -> None:
        """Assert that a file contains no forbidden network imports."""
        imports = analyze_file_imports(path)
        forbidden_found = imports & FORBIDDEN_NETWORK_IMPORTS
        self.assertEqual(
            set(),
            forbidden_found,
            f"{label} ({path.relative_to(REPO_ROOT)}) must not import "
            f"network modules: {sorted(forbidden_found)}",
        )

    def test_helper_has_no_network_imports(self) -> None:
        """bin/helper.py must not import network modules."""
        self._check_file_has_no_network_imports(
            REPO_ROOT / "bin" / "helper.py",
            "helper.py",
        )

    def test_send_gate_has_no_network_imports(self) -> None:
        """bin/send_gate.py must not import network modules."""
        self._check_file_has_no_network_imports(
            REPO_ROOT / "bin" / "send_gate.py",
            "send_gate.py",
        )

    def test_bridge_mcp_init_has_no_network_imports(self) -> None:
        """bridge_mcp/__init__.py must not import network modules."""
        self._check_file_has_no_network_imports(
            REPO_ROOT / "bridge_mcp" / "__init__.py",
            "bridge_mcp/__init__.py",
        )

    def test_bridge_mcp_client_has_no_network_imports(self) -> None:
        """bridge_mcp/client.py must not import network modules."""
        self._check_file_has_no_network_imports(
            REPO_ROOT / "bridge_mcp" / "client.py",
            "bridge_mcp/client.py",
        )

    def test_bridge_mcp_server_has_no_network_imports(self) -> None:
        """bridge_mcp/server.py must not import network modules."""
        self._check_file_has_no_network_imports(
            REPO_ROOT / "bridge_mcp" / "server.py",
            "bridge_mcp/server.py",
        )

    def test_bridge_mcp_main_has_no_network_imports(self) -> None:
        """bridge_mcp_main.py must not import network modules."""
        self._check_file_has_no_network_imports(
            REPO_ROOT / "bridge_mcp_main.py",
            "bridge_mcp_main.py",
        )


class DynamicEgressTest(unittest.TestCase):
    """Dynamic tests: verify no sockets are created during import/operations."""

    def test_send_gate_import_creates_no_sockets(self) -> None:
        """Importing send_gate.py must not create any sockets."""
        socket_calls = []

        def mock_socket_constructor(*args, **kwargs):
            socket_calls.append(("socket", args, kwargs))
            raise RuntimeError("send_gate.py attempted to create a socket")

        def mock_create_connection(*args, **kwargs):
            socket_calls.append(("create_connection", args, kwargs))
            raise RuntimeError("send_gate.py attempted socket.create_connection")

        with mock.patch("socket.socket", side_effect=mock_socket_constructor):
            with mock.patch("socket.create_connection", side_effect=mock_create_connection):
                # Import send_gate via importlib to isolate from other tests
                spec = importlib.util.spec_from_file_location(
                    "test_send_gate_egress",
                    REPO_ROOT / "bin" / "send_gate.py",
                )
                self.assertIsNotNone(spec)
                self.assertIsNotNone(spec.loader)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

        self.assertEqual(
            [],
            socket_calls,
            "send_gate.py created sockets during import",
        )

    def test_bridge_mcp_client_import_creates_no_sockets(self) -> None:
        """Importing bridge_mcp.client must not create any sockets."""
        socket_calls = []

        def mock_socket_constructor(*args, **kwargs):
            socket_calls.append(("socket", args, kwargs))
            raise RuntimeError("bridge_mcp.client attempted to create a socket")

        def mock_create_connection(*args, **kwargs):
            socket_calls.append(("create_connection", args, kwargs))
            raise RuntimeError("bridge_mcp.client attempted socket.create_connection")

        with mock.patch("socket.socket", side_effect=mock_socket_constructor):
            with mock.patch("socket.create_connection", side_effect=mock_create_connection):
                spec = importlib.util.spec_from_file_location(
                    "test_bridge_mcp_client_egress",
                    REPO_ROOT / "bridge_mcp" / "client.py",
                )
                self.assertIsNotNone(spec)
                self.assertIsNotNone(spec.loader)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

        self.assertEqual(
            [],
            socket_calls,
            "bridge_mcp/client.py created sockets during import",
        )

    def test_bridge_mcp_server_import_creates_no_sockets(self) -> None:
        """Importing bridge_mcp.server must not create any sockets."""
        socket_calls = []

        def mock_socket_constructor(*args, **kwargs):
            socket_calls.append(("socket", args, kwargs))
            raise RuntimeError("bridge_mcp.server attempted to create a socket")

        def mock_create_connection(*args, **kwargs):
            socket_calls.append(("create_connection", args, kwargs))
            raise RuntimeError("bridge_mcp.server attempted socket.create_connection")

        with mock.patch("socket.socket", side_effect=mock_socket_constructor):
            with mock.patch("socket.create_connection", side_effect=mock_create_connection):
                spec = importlib.util.spec_from_file_location(
                    "test_bridge_mcp_server_egress",
                    REPO_ROOT / "bridge_mcp" / "server.py",
                )
                self.assertIsNotNone(spec)
                self.assertIsNotNone(spec.loader)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

        self.assertEqual(
            [],
            socket_calls,
            "bridge_mcp/server.py created sockets during import",
        )

    def test_helper_import_creates_no_sockets(self) -> None:
        """Importing helper.py must not create any sockets.

        This test verifies the import path up to the point where helper
        loads send_gate. The helper contains subprocess for osascript,
        but no network operations.
        """
        socket_calls = []

        def mock_socket_constructor(*args, **kwargs):
            socket_calls.append(("socket", args, kwargs))
            raise RuntimeError("helper.py attempted to create a socket")

        def mock_create_connection(*args, **kwargs):
            socket_calls.append(("create_connection", args, kwargs))
            raise RuntimeError("helper.py attempted socket.create_connection")

        with mock.patch("socket.socket", side_effect=mock_socket_constructor):
            with mock.patch("socket.create_connection", side_effect=mock_create_connection):
                # Import with minimal environment to avoid missing paths/dirs
                # The critical check is: does the import attempt network I/O?
                # We don't need a full bridge setup for this test.
                import tempfile
                import os

                with tempfile.TemporaryDirectory(prefix="egress-test-") as td:
                    env_backup = {}
                    for key in ("IMESSAGE_BRIDGE_DIR", "COWORK_IMESSAGE_BRIDGE_DIR"):
                        env_backup[key] = os.environ.get(key)
                        os.environ[key] = td

                    try:
                        spec = importlib.util.spec_from_file_location(
                            "test_helper_egress",
                            REPO_ROOT / "bin" / "helper.py",
                        )
                        self.assertIsNotNone(spec)
                        self.assertIsNotNone(spec.loader)
                        module = importlib.util.module_from_spec(spec)
                        # Add to sys.modules before exec to fix dataclass decorator
                        sys.modules[spec.name] = module
                        try:
                            spec.loader.exec_module(module)
                        finally:
                            sys.modules.pop(spec.name, None)
                    finally:
                        for key, value in env_backup.items():
                            if value is None:
                                os.environ.pop(key, None)
                            else:
                                os.environ[key] = value

        self.assertEqual(
            [],
            socket_calls,
            "helper.py created sockets during import",
        )


if __name__ == "__main__":
    unittest.main()
