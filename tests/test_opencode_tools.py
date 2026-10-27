import io
import base64
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from brain.tools_executor import RISK_LEVELS, execute_tool
from tools import opencode_tools as oc
from tools.opencode_tools import (
    OpenCodeClient,
    OpenCodeError,
    OpenCodeTimeout,
    parse_model,
    resolve_password,
)


class FakeResponse:
    def __init__(self, payload: bytes = b""):
        self._payload = payload

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeServer:
    """Simula urlopen sin red. Registra (metodo, path, body)."""

    base = "http://127.0.0.1:4096"

    def __init__(self, routes):
        self.routes = routes
        self.calls = []
        self.requests = []

    def __call__(self, request, timeout=None):
        path = request.full_url.split(self.base, 1)[-1]
        method = request.get_method()
        body = json.loads(request.data) if request.data else None
        self.requests.append(request)
        self.calls.append({"method": method, "path": path, "body": body, "timeout": timeout})

        key = (method, path)
        if key not in self.routes:
            for candidate in (path, method):
                if candidate in self.routes:
                    key = candidate
                    break
            else:
                raise AssertionError(f"ruta no simulada: {method} {path}")

        handler = self.routes[key]
        if isinstance(handler, Exception):
            raise handler
        if callable(handler):
            handler = handler()
        if handler is None:
            return FakeResponse(b"")
        if isinstance(handler, bytes):
            return FakeResponse(handler)
        return FakeResponse(json.dumps(handler).encode("utf-8"))


def make_client(**overrides):
    cfg = {
        "enabled": True,
        "host": "127.0.0.1",
        "port": 4096,
        "password": "secreto",
        "model": "opencode/big-pickle",
        "auto_start": False,
        "permissions": "allow",
        "wait_timeout": 60,
        "request_timeout": 5,
    }
    cfg.update(overrides)
    return OpenCodeClient(cfg)


def assistant(created, text="", finish="stop", tools=None, files=None, cost=0.0):
    content = []
    if text:
        content.append({"type": "text", "text": text})
    for name in tools or []:
        content.append(
            {"type": "tool", "name": name, "state": {"status": "completed", "input": {}}}
        )
    message = {
        "type": "assistant",
        "time": {"created": created},
        "content": content,
        "finish": finish,
        "cost": cost,
    }
    if files:
        message["snapshot"] = {"files": files}
    return message


class ParseModelTest(unittest.TestCase):
    def test_simple(self):
        self.assertEqual(
            parse_model("opencode/big-pickle"),
            {"providerID": "opencode", "id": "big-pickle"},
        )

    def test_nested_model_id(self):
        self.assertEqual(
            parse_model("openrouter/anthropic/claude-sonnet-5"),
            {"providerID": "openrouter", "id": "anthropic/claude-sonnet-5"},
        )

    def test_invalid(self):
        self.assertIsNone(parse_model(None))
        self.assertIsNone(parse_model(""))
        self.assertIsNone(parse_model("sin-barra"))
        self.assertIsNone(parse_model("/modelo"))
        self.assertIsNone(parse_model("proveedor/"))


class PasswordTest(unittest.TestCase):
    def test_config_wins(self):
        with mock.patch.dict(os.environ, {"OPENCODE_SERVER_PASSWORD": "del-entorno"}):
            self.assertEqual(resolve_password({"password": "de-config"}), "de-config")

    def test_env_second(self):
        with mock.patch.dict(os.environ, {"OPENCODE_SERVER_PASSWORD": "del-entorno"}):
            self.assertEqual(resolve_password({}), "del-entorno")

    def test_cached_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / ".opencode_password"
            cache.write_text("cacheado", encoding="utf-8")
            with mock.patch.object(oc, "_PASSWORD_FILE", cache), mock.patch.dict(
                os.environ, {"OPENCODE_SERVER_PASSWORD": ""}
            ):
                self.assertEqual(resolve_password({}), "cacheado")

    def test_generates_and_stores(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / ".opencode_password"
            with mock.patch.object(oc, "_PASSWORD_FILE", cache), mock.patch.dict(
                os.environ, {"OPENCODE_SERVER_PASSWORD": ""}
            ):
                password = resolve_password({})
                self.assertGreater(len(password), 20)
                self.assertEqual(cache.read_text(encoding="utf-8"), password)


class RequestTest(unittest.TestCase):
    def test_ok_and_basic_auth(self):
        server = FakeServer({("GET", "/api/info"): {"version": "2.1.4"}})
        client = make_client()
        with mock.patch.object(oc.urllib.request, "urlopen", server):
            self.assertEqual(client._request("GET", "/api/info")["version"], "2.1.4")

        # El header Authorization va en la peticion (Basic usuario:password).
        self.assertTrue(server.requests[0].headers.get("Authorization").startswith("Basic "))
        expected = "Basic " + base64.b64encode(b"opencode:secreto").decode("ascii")
        self.assertEqual(server.requests[0].headers.get("Authorization"), expected)

    def test_json_body(self):
        server = FakeServer({("POST", "/api/session"): {"data": {"id": "ses_1"}}})
        client = make_client()
        with mock.patch.object(oc.urllib.request, "urlopen", server):
            client._request("POST", "/api/session", {"title": "x"})
        self.assertEqual(server.calls[0]["body"], {"title": "x"})

    def test_no_content(self):
        server = FakeServer({("POST", "/api/x"): b""})
        client = make_client()
        with mock.patch.object(oc.urllib.request, "urlopen", server):
            self.assertIsNone(client._request("POST", "/api/x", {}))

    def test_http_error_has_status(self):
        error = urllib.error.HTTPError(
            "http://127.0.0.1:4096/api/info",
            401,
            "Unauthorized",
            {},
            io.BytesIO(b'{"message":"API key expired."}'),
        )
        server = FakeServer({("GET", "/api/info"): error})
        client = make_client()
        with mock.patch.object(oc.urllib.request, "urlopen", server):
            with self.assertRaises(OpenCodeError) as ctx:
                client._request("GET", "/api/info")
        self.assertEqual(ctx.exception.status, 401)
        self.assertIn("401", str(ctx.exception))

    def test_connection_error(self):
        server = FakeServer(
            {("GET", "/api/info"): urllib.error.URLError("connection refused")}
        )
        client = make_client()
        with mock.patch.object(oc.urllib.request, "urlopen", server):
            with self.assertRaises(OpenCodeError):
                client._request("GET", "/api/info")


class ProbeTest(unittest.TestCase):
    def test_ok(self):
        server = FakeServer({("GET", "/api/info"): {"version": "2"}})
        client = make_client()
        with mock.patch.object(oc.urllib.request, "urlopen", server):
            self.assertEqual(client.probe(), "ok")

    def test_unauthorized(self):
        error = urllib.error.HTTPError(
            "http://127.0.0.1:4096/api/info", 401, "Unauthorized", {}, io.BytesIO(b"")
        )
        server = FakeServer({("GET", "/api/info"): error})
        client = make_client()
        with mock.patch.object(oc.urllib.request, "urlopen", server):
            self.assertEqual(client.probe(), "unauthorized")
            self.assertFalse(client.is_alive())

    def test_down(self):
        server = FakeServer({("GET", "/api/info"): urllib.error.URLError("no")})
        client = make_client()
        with mock.patch.object(oc.urllib.request, "urlopen", server):
            self.assertEqual(client.probe(), "down")


class EnsureServerTest(unittest.TestCase):
    def test_unauthorized_port_is_explained(self):
        error = urllib.error.HTTPError(
            "http://127.0.0.1:4096/api/info", 401, "Unauthorized", {}, io.BytesIO(b"")
        )
        server = FakeServer({("GET", "/api/info"): error})
        client = make_client()
        with mock.patch.object(oc.urllib.request, "urlopen", server):
            with self.assertRaises(OpenCodeError) as ctx:
                client.ensure_server()
        self.assertIn("password", str(ctx.exception))

    def test_disabled(self):
        client = make_client(enabled=False)
        with self.assertRaises(OpenCodeError) as ctx:
            client.ensure_server()
        self.assertIn("desactivada", str(ctx.exception))

    def test_auto_start_off(self):
        server = FakeServer({("GET", "/api/info"): urllib.error.URLError("no")})
        client = make_client()
        with mock.patch.object(oc.urllib.request, "urlopen", server):
            with self.assertRaises(OpenCodeError) as ctx:
                client.ensure_server()
        self.assertIn("no esta corriendo", str(ctx.exception))


class SummarizeTest(unittest.TestCase):
    def test_final_text_is_last_terminal(self):
        messages = [
            {"type": "user", "time": {"created": 1}, "text": "hazlo"},
            assistant(2, "voy a escribirlo", finish="tool-calls", tools=["write"]),
            assistant(3, "listo, creado", finish="stop", files=["a.py"], cost=0.5),
            {"type": "idle", "time": {"created": 4}},
        ]
        client = make_client()
        result = client.summarize(messages)
        self.assertEqual(result["answer"], "listo, creado")
        self.assertEqual(result["tools"], ["write:completed"])
        self.assertIn("a.py", result["files_changed"])
        self.assertAlmostEqual(result["cost_usd"], 0.5)

    def test_since_filters_previous_turns(self):
        messages = [
            assistant(10, "turno viejo", finish="stop"),
            assistant(20, "turno nuevo", finish="stop"),
        ]
        client = make_client()
        self.assertEqual(client.summarize(messages, since=15)["answer"], "turno nuevo")

    def test_error_message_is_terminal(self):
        messages = [
            {"type": "user", "time": {"created": 1}, "text": "x"},
            {
                "type": "assistant",
                "time": {"created": 2},
                "content": [],
                "finish": "error",
                "error": {"message": "API key expired."},
            },
        ]
        client = make_client()
        final = client.final_answer(messages, since=0)
        self.assertIsNotNone(final)
        self.assertEqual(final["finish"], "error")

    def test_no_answer(self):
        client = make_client()
        self.assertIsNone(client.final_answer([{"type": "user", "time": {"created": 1}}]))


class NoServerCheck(unittest.TestCase):
    """Los tests de API no deben arrancar un opencode serve real."""

    def setUp(self):
        patcher = mock.patch.object(
            OpenCodeClient, "ensure_server", lambda self: None
        )
        patcher.start()
        self.addCleanup(patcher.stop)


class RunTaskTest(NoServerCheck):
    def _routes(self, messages, created=1000):
        return {
            ("POST", "/api/session"): {"data": {"id": "ses_1", "model": {"providerID": "opencode", "id": "big-pickle"}}},
            ("POST", "/api/session/ses_1/prompt"): {"data": {"time": {"created": created}}},
            ("POST", "/api/experimental/session/ses_1/wait"): b"",
            ("GET", "/api/session/ses_1/message"): {"data": messages},
        }

    def test_completed(self):
        messages = [
            {"type": "user", "time": {"created": 1001}, "text": "x"},
            assistant(1002, "hecho", finish="stop", files=["saludo.py"]),
        ]
        server = FakeServer(self._routes(messages))
        client = make_client()
        with mock.patch.object(oc.urllib.request, "urlopen", server):
            result = client.run_task("crea saludo.py", directory=tempfile.gettempdir())

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["answer"], "hecho")
        self.assertEqual(result["session_id"], "ses_1")
        self.assertEqual(result["model"], "opencode/big-pickle")
        self.assertIn("saludo.py", result["files_changed"])

        create = server.calls[0]["body"]
        self.assertEqual(create["model"], {"providerID": "opencode", "id": "big-pickle"})
        self.assertEqual(create["location"]["directory"], str(Path(tempfile.gettempdir()).resolve()))
        self.assertEqual(
            create["permissions"], [{"action": "*", "resource": "*", "effect": "allow"}]
        )

    def test_does_not_auto_approve_when_ask(self):
        messages = [assistant(1002, "ok")]
        server = FakeServer(self._routes(messages))
        client = make_client(permissions="ask")
        with mock.patch.object(oc.urllib.request, "urlopen", server):
            client.run_task("x", directory=tempfile.gettempdir())
        self.assertNotIn("permissions", server.calls[0]["body"])

    def test_background_returns_immediately(self):
        server = FakeServer(self._routes([]))
        client = make_client()
        with mock.patch.object(oc.urllib.request, "urlopen", server):
            result = client.run_task("tarea larga", directory=tempfile.gettempdir(), background=True)
        self.assertEqual(result["status"], "running")
        self.assertEqual(result["session_id"], "ses_1")
        paths = [c["path"] for c in server.calls]
        self.assertNotIn(("POST", "/api/experimental/session/ses_1/wait"), [
            (c["method"], c["path"]) for c in server.calls
        ])
        self.assertTrue(any("/prompt" in p for p in paths))

    def test_timeout_returns_running(self):
        routes = self._routes([])
        server = FakeServer(routes)
        client = make_client(wait_timeout=1)
        with mock.patch.object(oc.urllib.request, "urlopen", server), mock.patch.object(
            oc.time, "sleep", lambda *_: None
        ):
            result = client.run_task("algo eterno", directory=tempfile.gettempdir())
        self.assertEqual(result["status"], "running")
        self.assertIn("opencode_result", result["message"])

    def test_empty_task(self):
        client = make_client()
        self.assertEqual(client.run_task("   ")["status"], "error")

    def test_creates_missing_directory(self):
        messages = [assistant(1002, "ok")]
        server = FakeServer(self._routes(messages))
        client = make_client()
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "nuevo" / "proyecto"
            with mock.patch.object(oc.urllib.request, "urlopen", server):
                result = client.run_task("x", directory=str(target))
            self.assertTrue(target.exists())
            self.assertTrue(result["created_directory"])

    def test_error_status_when_no_answer(self):
        messages = [
            {"type": "user", "time": {"created": 1001}, "text": "x"},
            {
                "type": "assistant",
                "time": {"created": 1002},
                "content": [],
                "finish": "error",
                "error": {"message": "API key expired."},
            },
        ]
        server = FakeServer(self._routes(messages))
        client = make_client()
        with mock.patch.object(oc.urllib.request, "urlopen", server):
            result = client.run_task("x", directory=tempfile.gettempdir())
        self.assertEqual(result["status"], "error")
        self.assertIn("API key expired", result["error"])


class McpTest(NoServerCheck):
    def test_list(self):
        server = FakeServer(
            {
                ("GET", "/api/mcp"): {
                    "data": [
                        {"name": "github", "status": {"status": "connected"}},
                        {"name": "roto", "status": {"status": "failed", "error": "boom"}},
                    ]
                }
            }
        )
        client = make_client()
        with mock.patch.object(oc.urllib.request, "urlopen", server):
            result = client.mcp("list")
        self.assertEqual(result["servers"][0], {"name": "github", "status": "connected", "error": ""})
        self.assertEqual(result["servers"][1]["status"], "failed")

    def test_add_remote(self):
        server = FakeServer({("PUT", "/api/experimental/mcp/prueba"): b""})
        client = make_client()
        with mock.patch.object(oc.urllib.request, "urlopen", server):
            result = client.mcp("add", server="prueba", url="https://example.com/mcp")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(
            server.calls[0]["body"], {"config": {"type": "remote", "url": "https://example.com/mcp"}}
        )

    def test_add_local_uses_shlex(self):
        server = FakeServer({("PUT", "/api/experimental/mcp/local"): b""})
        client = make_client()
        with mock.patch.object(oc.urllib.request, "urlopen", server):
            client.mcp("add", server="local", command="npx -y @paquete/mcp")
        self.assertEqual(
            server.calls[0]["body"]["config"]["command"], ["npx", "-y", "@paquete/mcp"]
        )

    def test_add_without_url_or_command(self):
        client = make_client()
        result = client.mcp("add", server="x")
        self.assertEqual(result["status"], "error")

    def test_remove_connect_disconnect(self):
        routes = {
            ("DELETE", "/api/experimental/mcp/x"): b"",
            ("POST", "/api/experimental/mcp/x/connect"): b"",
            ("POST", "/api/experimental/mcp/x/disconnect"): b"",
        }
        server = FakeServer(routes)
        client = make_client()
        with mock.patch.object(oc.urllib.request, "urlopen", server):
            self.assertEqual(client.mcp("remove", server="x")["status"], "ok")
            self.assertEqual(client.mcp("connect", server="x")["status"], "ok")
            self.assertEqual(client.mcp("disconnect", server="x")["status"], "ok")

    def test_unknown_action(self):
        client = make_client()
        result = client.mcp("inventada")
        self.assertEqual(result["status"], "error")
        self.assertIn("desconocida", result["error"])

    def test_missing_server(self):
        client = make_client()
        self.assertEqual(client.mcp("add")["status"], "error")

    def test_list_with_directory_uses_location(self):
        server = FakeServer({"GET": {"data": []}})
        client = make_client()
        with mock.patch.object(oc.urllib.request, "urlopen", server):
            client.mcp("list", directory=tempfile.gettempdir())
        self.assertIn("location%5Bdirectory%5D=", server.calls[0]["path"])


class GetResultTest(NoServerCheck):
    def test_collects_existing_session(self):
        server = FakeServer(
            {
                ("POST", "/api/experimental/session/ses_9/wait"): b"",
                ("GET", "/api/session/ses_9/message"): {
                    "data": [assistant(5, "terminado", finish="stop")]
                },
            }
        )
        client = make_client()
        with mock.patch.object(oc.urllib.request, "urlopen", server):
            result = client.get_result("ses_9")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["answer"], "terminado")

    def test_missing_id(self):
        client = make_client()
        self.assertEqual(client.get_result("")["status"], "error")

    def test_still_running(self):
        server = FakeServer(
            {
                ("POST", "/api/experimental/session/ses_9/wait"): b"",
                ("GET", "/api/session/ses_9/message"): {"data": []},
            }
        )
        client = make_client(wait_timeout=1)
        with mock.patch.object(oc.urllib.request, "urlopen", server), mock.patch.object(
            oc.time, "sleep", lambda *_: None
        ):
            result = client.get_result("ses_9")
        self.assertEqual(result["status"], "running")


class ToolRegistrationTest(unittest.TestCase):
    def test_registered_with_risk(self):
        for name in (
            "opencode_code",
            "opencode_result",
            "opencode_sessions",
            "opencode_mcp",
        ):
            self.assertIn(name, RISK_LEVELS)

    def test_execute_tool_forwards_to_client(self):
        with mock.patch.object(oc, "_client", make_client()), mock.patch.object(
            OpenCodeClient, "run_task", return_value={"status": "completed", "answer": "ok"}
        ) as run:
            result = execute_tool("opencode_code", {"task": "crea x", "directory": ""})
        self.assertEqual(result["answer"], "ok")
        run.assert_called_once()

    def test_execute_tool_errors_are_captured(self):
        with mock.patch.object(oc, "_client", make_client()), mock.patch.object(
            OpenCodeClient, "run_task", side_effect=OpenCodeError("sin servidor")
        ):
            result = execute_tool("opencode_code", {"task": "x"})
        self.assertIn("sin servidor", result["error"])


if __name__ == "__main__":
    unittest.main()
