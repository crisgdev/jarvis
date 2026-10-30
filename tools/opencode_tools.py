"""Integracion con OpenCode: JARVIS delega el trabajo de programacion.

OpenCode expone un servidor HTTP local (`opencode serve`) con un agente capaz
de editar archivos, ejecutar comandos, crear repositorios, manejar servidores
MCP, etc. JARVIS NO reimplementa nada de eso: solo le pide las cosas por HTTP.

Flujo de una tarea:
  1. POST /api/session                        -> crea la sesion en el directorio
  2. POST /api/session/{id}/prompt            -> encola el pedido del usuario
  3. POST /api/experimental/session/{id}/wait -> espera a que el agente quede idle
  4. GET  /api/session/{id}/message           -> lee la conversacion y resume

Autenticacion: HTTP Basic (usuario `opencode` + password). El password sale de
`config.json -> opencode.password`, de la variable de entorno
`OPENCODE_SERVER_PASSWORD` o de `logs/.opencode_password` (se genera solo la
primera vez). JARVIS pasa ese mismo password al servidor que arranca el mismo.

Los endpoints `/api/experimental/...` son los que documenta OpenCode V2; si una
version futura los mueve, `opencode_code` es el unico sitio que hay que tocar.
"""

import base64
import json
import logging
import os
import secrets
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from brain.tools_executor import register_tool
from config import BASE_DIR, get_config

logger = logging.getLogger("jarvis.tools.opencode")

_PASSWORD_FILE = BASE_DIR / "logs" / ".opencode_password"
_SERVER_LOG = BASE_DIR / "logs" / "opencode_server.log"
_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

# Un mensaje del asistente con estos `finish` ya no va a cambiar.
_TERMINAL_FINISH = ("stop", "length", "content-filter", "error")


class OpenCodeError(RuntimeError):
    """Fallo hablando con el servidor de OpenCode."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class OpenCodeTimeout(OpenCodeError):
    """La tarea sigue corriendo cuando se acabo el tiempo de espera."""


# ── Configuracion y password ────────────────────────────────────────────────

def _settings() -> dict:
    return get_config().get("opencode", {}) or {}


def _read_cached_password() -> str:
    try:
        return _PASSWORD_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _store_password(password: str) -> None:
    try:
        _PASSWORD_FILE.parent.mkdir(parents=True, exist_ok=True)
        _PASSWORD_FILE.write_text(password, encoding="utf-8")
        if os.name != "nt":
            os.chmod(_PASSWORD_FILE, 0o600)
    except OSError as e:  # pragma: no cover - depende del disco
        logger.warning("No se pudo guardar el password de OpenCode: %s", e)


def resolve_password(cfg: dict | None = None) -> str:
    """Config > entorno > cache en disco > uno nuevo (y se guarda)."""
    cfg = cfg if cfg is not None else _settings()
    password = str(cfg.get("password") or "").strip()
    if password:
        return password
    password = (os.getenv("OPENCODE_SERVER_PASSWORD") or "").strip()
    if password:
        return password
    password = _read_cached_password()
    if password:
        return password
    password = secrets.token_urlsafe(32)
    _store_password(password)
    return password


def parse_model(spec: str | None) -> dict | None:
    """'opencode/big-pickle' -> {'providerID': 'opencode', 'id': 'big-pickle'}.

    Se corta por el PRIMER '/': los ids de OpenRouter tambien llevan barras
    ('openrouter/anthropic/claude-sonnet-5').
    """
    if not spec or "/" not in str(spec):
        return None
    provider, _, model_id = str(spec).partition("/")
    provider, model_id = provider.strip(), model_id.strip()
    if not provider or not model_id:
        return None
    return {"providerID": provider, "id": model_id}

# Palabras que sugieren que el fallo se debe al modelo/proveedor (no al codigo
# ni a la red), por lo que vale la pena reintentar con el modelo de respaldo.
_MODEL_ERROR_KEYWORDS = (
    "free usage limit",
    "free-limit",
    "free limit",
    "provider.free",
    "provider error",
    "model",
    "provider",
    "unavailable",
    "not available",
    "not found",
    "does not exist",
    "no such model",
    "expired",
    "rate limit",
    "rate-limit",
    "quota",
    "capacity",
    "overloaded",
    "resource exhausted",
)


def is_model_unavailable(exc_or_text) -> bool:
    """True si el error parece deberse al modelo/proveedor (no al codigo/red)."""
    status = None
    text = ""
    if isinstance(exc_or_text, OpenCodeError):
        status = getattr(exc_or_text, "status", None)
        text = str(exc_or_text)
    elif isinstance(exc_or_text, Exception):
        text = str(exc_or_text)
    else:
        text = str(exc_or_text or "")

    if status is not None and status in (400, 404, 408, 429, 500, 502, 503, 504):
        # 401/403 son de autenticacion: reintentar con otro modelo no ayuda.
        return True
    lowered = text.lower()
    return any(keyword in lowered for keyword in _MODEL_ERROR_KEYWORDS)


def _describe_http_error(err: urllib.error.HTTPError) -> str:
    try:
        raw = err.read().decode("utf-8", errors="replace")
    except Exception:  # pragma: no cover - body ya consumido
        raw = ""
    detail = ""
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                detail = (
                    parsed.get("message")
                    or parsed.get("error")
                    or parsed.get("detail")
                    or ""
                )
                if isinstance(detail, dict):
                    detail = detail.get("message") or json.dumps(detail)
        except (ValueError, TypeError):
            detail = raw
    detail = str(detail).strip()[:400]
    return detail or (err.reason if isinstance(err.reason, str) else str(err.reason))


# ── Cliente ────────────────────────────────────────────────────────────────

class OpenCodeClient:
    def __init__(self, config: dict | None = None):
        cfg = config if config is not None else _settings()
        self.cfg = cfg or {}
        self.enabled = bool(self.cfg.get("enabled", True))
        self.host = str(self.cfg.get("host") or "127.0.0.1")
        self.port = int(self.cfg.get("port") or 4096)
        self.username = str(self.cfg.get("username") or "opencode")
        self.password = resolve_password(self.cfg)
        self.model = parse_model(self.cfg.get("model"))
        # Respaldo simple (compatibilidad): fallback_model / model_fallback.
        primary_fallback = parse_model(
            self.cfg.get("fallback_model")
            or self.cfg.get("model_fallback")
            or self.cfg.get("backup_model")
        )
        # Cadena de respaldos (doble/triple fallback): 'fallback_models' es
        # una lista de specs 'proveedor/modelo' que se prueban en orden si
        # el modelo principal (y los respaldos previos) fallan.
        fallback_models: list[dict] = []
        if primary_fallback:
            fallback_models.append(primary_fallback)
        for spec in self.cfg.get("fallback_models") or []:
            parsed = parse_model(spec)
            if parsed:
                fallback_models.append(parsed)
        # Deduplicar conservando el orden (y excluyendo el modelo principal).
        candidates_seen: list[dict] = [self.model] if self.model else []
        for m in fallback_models:
            if m and m not in candidates_seen:
                candidates_seen.append(m)
        self.fallback_models = candidates_seen[1:]
        self.fallback_model = self.fallback_models[0] if self.fallback_models else None
        self.default_directory = str(self.cfg.get("directory") or "")
        self.auto_start = bool(self.cfg.get("auto_start", True))
        self.approve_all = str(self.cfg.get("permissions", "allow")).lower() != "ask"
        self.wait_timeout = int(self.cfg.get("wait_timeout", 240) or 0)
        self.request_timeout = int(self.cfg.get("request_timeout", 30) or 30)
        self.start_timeout = int(self.cfg.get("start_timeout", 90) or 90)
        self.shutdown_on_exit = bool(self.cfg.get("shutdown_on_exit", False))
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()

    # -- HTTP ---------------------------------------------------------
    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def _auth(self) -> str:
        token = f"{self.username}:{self.password}".encode("utf-8")
        return "Basic " + base64.b64encode(token).decode("ascii")

    def _request(self, method: str, path: str, payload=None, timeout: int | None = None):
        data = None
        headers = {"Accept": "application/json", "Authorization": self._auth()}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = urllib.request.Request(
            self.base_url + path, data=data, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(
                request, timeout=timeout or self.request_timeout
            ) as response:
                raw = response.read()
        except urllib.error.HTTPError as e:
            raise OpenCodeError(
                f"OpenCode respondio {e.code}: {_describe_http_error(e)}", status=e.code
            ) from e
        except urllib.error.URLError as e:
            raise OpenCodeError(
                f"No pude conectar con OpenCode en {self.base_url}: {e.reason}"
            ) from e
        except (TimeoutError, OSError) as e:
            raise OpenCodeTimeout(f"OpenCode no respondio a tiempo ({path}): {e}") from e

        if not raw:
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as e:
            raise OpenCodeError(f"Respuesta invalida de OpenCode ({path}): {e}") from e

    def probe(self) -> str:
        """'ok' | 'unauthorized' | 'down'."""
        try:
            self._request("GET", "/api/info", timeout=4)
            return "ok"
        except OpenCodeError as e:
            return "unauthorized" if e.status in (401, 403) else "down"

    def is_alive(self) -> bool:
        return self.probe() == "ok"

    # -- Servidor -----------------------------------------------------
    def ensure_server(self) -> None:
        if not self.enabled:
            raise OpenCodeError(
                "La integracion con OpenCode esta desactivada (opencode.enabled=false)."
            )

        state = self.probe()
        if state == "ok":
            return
        if state == "unauthorized":
            raise OpenCodeError(
                f"Hay un servidor OpenCode en {self.base_url} pero no acepta el password "
                "de JARVIS. Cierralo (o ajusta opencode.password / opencode.port)."
            )
        if not self.auto_start:
            raise OpenCodeError(
                "El servidor OpenCode no esta corriendo. Arrancalo con 'opencode serve' "
                "o activa opencode.auto_start en config.json."
            )

        with self._lock:
            if self.probe() == "ok":
                return

            executable = shutil.which("opencode")
            if not executable:
                raise OpenCodeError(
                    "No encontre el comando 'opencode' en el PATH. Instalalo con "
                    "'npm i -g opencode-ai'."
                )

            env = os.environ.copy()
            env["OPENCODE_SERVER_PASSWORD"] = self.password
            _SERVER_LOG.parent.mkdir(parents=True, exist_ok=True)
            logger.info("Arrancando servidor OpenCode en %s", self.base_url)
            with open(_SERVER_LOG, "ab") as log_handle:
                try:
                    self._proc = subprocess.Popen(
                        [
                            executable,
                            "serve",
                            "--port",
                            str(self.port),
                            "--hostname",
                            self.host,
                        ],
                        cwd=str(BASE_DIR),
                        env=env,
                        stdout=log_handle,
                        stderr=subprocess.STDOUT,
                        creationflags=_NO_WINDOW,
                    )
                except OSError as e:
                    raise OpenCodeError(f"No pude lanzar 'opencode serve': {e}") from e

            deadline = time.time() + self.start_timeout
            while time.time() < deadline:
                state = self.probe()
                if state == "ok":
                    logger.info("Servidor OpenCode listo (pid %s)", self._proc.pid)
                    return
                if state == "unauthorized":
                    raise OpenCodeError(
                        f"El servidor OpenCode de {self.base_url} rechazo el password."
                    )
                if self._proc.poll() is not None:
                    raise OpenCodeError(
                        "El servidor OpenCode termino al arrancar. Revisa "
                        f"{_SERVER_LOG.name}."
                    )
                time.sleep(0.4)

            raise OpenCodeError(
                f"El servidor OpenCode no respondio en {self.start_timeout}s. "
                f"Revisa {_SERVER_LOG.name}."
            )

    def stop_server(self) -> None:
        """Detiene SOLO el servidor que arranco JARVIS (si esta configurado)."""
        if not self.shutdown_on_exit or self._proc is None:
            return
        if self._proc.poll() is not None:
            self._proc = None
            return
        logger.info("Deteniendo servidor OpenCode (pid %s)", self._proc.pid)
        try:
            self._proc.terminate()
            self._proc.wait(timeout=10)
        except Exception as e:  # pragma: no cover - depende del SO
            logger.warning("No se pudo detener OpenCode limpiamente: %s", e)
            try:
                self._proc.kill()
            except Exception:
                pass
        finally:
            self._proc = None

    # -- Sesiones -----------------------------------------------------
    def resolve_directory(self, directory: str | None) -> tuple[str, bool]:
        """Devuelve (ruta_absoluta, la_creamos)."""
        raw = str(directory or self.default_directory or "").strip()
        path = Path(raw).expanduser() if raw else Path(BASE_DIR)
        if not path.is_absolute():
            path = Path(BASE_DIR) / path
        path = path.resolve()
        created = False
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
            created = True
        return str(path), created

    def create_session(
        self, directory: str, title: str = "JARVIS", model: dict | None = None
    ) -> dict:
        payload: dict = {
            "title": title[:80],
            "location": {"directory": directory},
        }
        chosen = model or self.model
        if chosen:
            payload["model"] = chosen
        if self.approve_all:
            # Sin esto el agente se queda esperando aprobacion en cada archivo
            # que quiere escribir. El usuario pidio que JARVIS trabaje solo.
            payload["permissions"] = [{"action": "*", "resource": "*", "effect": "allow"}]

        data = self._request("POST", "/api/session", payload)
        session = (data or {}).get("data") or {}
        if not session.get("id"):
            raise OpenCodeError("OpenCode no devolvio la sesion creada.")
        return session

    def send_prompt(self, session_id: str, text: str) -> dict:
        data = self._request(
            "POST", f"/api/session/{session_id}/prompt", {"text": text}
        )
        return (data or {}).get("data") or {}

    def wait_session(self, session_id: str, timeout: int) -> None:
        self._request(
            "POST",
            f"/api/experimental/session/{session_id}/wait",
            {},
            timeout=max(int(timeout), 5) + 30,
        )

    def get_messages(self, session_id: str) -> list[dict]:
        data = self._request("GET", f"/api/session/{session_id}/message")
        items = (data or {}).get("data") or []
        # La API los devuelve del mas nuevo al mas viejo.
        return sorted(items, key=lambda m: (m.get("time") or {}).get("created") or 0)

    # -- Lectura de resultados ----------------------------------------
    @staticmethod
    def _finish(message: dict) -> str:
        return str(message.get("finish") or "")

    def final_answer(self, messages: list[dict], since: float = 0) -> dict | None:
        """Ultimo mensaje del asistente que ya termino (o con error)."""
        for message in reversed(messages):
            if message.get("type") != "assistant":
                continue
            created = (message.get("time") or {}).get("created") or 0
            if created < since:
                continue
            if self._finish(message) in _TERMINAL_FINISH:
                return message
        return None

    def summarize(self, messages: list[dict], since: float = 0) -> dict:
        texts: list[str] = []
        tools: list[str] = []
        files: list[str] = []
        cost = 0.0
        final_text = ""

        for message in messages:
            if message.get("type") != "assistant":
                continue
            created = (message.get("time") or {}).get("created") or 0
            if created < since:
                continue
            try:
                cost += float(message.get("cost") or 0)
            except (TypeError, ValueError):
                pass
            for chunk in message.get("content") or []:
                kind = chunk.get("type")
                if kind == "text":
                    text = (chunk.get("text") or "").strip()
                    if text:
                        texts.append(text)
                        if self._finish(message) in _TERMINAL_FINISH:
                            final_text = text
                elif kind == "tool":
                    name = chunk.get("name") or "tool"
                    status = (chunk.get("state") or {}).get("status") or ""
                    tools.append(f"{name}:{status}" if status else name)
                    tool_input = (chunk.get("state") or {}).get("input") or {}
                    path = tool_input.get("filePath") or tool_input.get("path")
                    if path:
                        files.append(str(path))
            for path in (message.get("snapshot") or {}).get("files") or []:
                files.append(str(path))

        if not final_text and texts:
            final_text = texts[-1]
        if not final_text:
            final_text = "\n\n".join(texts)

        return {
            "answer": final_text,
            "tools": _unique(tools),
            "files_changed": _unique(files),
            "cost_usd": round(cost, 6),
        }

    def _collect(self, session_id: str, since: float, timeout: int) -> list[dict]:
        """Espera a que el turno termine y devuelve los mensajes."""
        deadline = time.time() + max(int(timeout), 0)
        attempts = 0
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                raise OpenCodeTimeout(
                    "La tarea de OpenCode sigue en ejecucion."
                )
            # El endpoint de wait bloquea del lado del servidor. El bucle extra
            # cubre la carrera de pedir wait antes de que el agente arranque.
            self.wait_session(session_id, int(min(remaining, 120)))
            messages = self.get_messages(session_id)
            if self.final_answer(messages, since):
                return messages
            attempts += 1
            if attempts >= 5 or time.time() >= deadline:
                raise OpenCodeTimeout("La tarea de OpenCode sigue en ejecucion.")
            time.sleep(0.4)

    # -- API de alto nivel --------------------------------------------
    def run_task(
        self,
        task: str,
        directory: str | None = None,
        timeout: int | None = None,
        background: bool = False,
    ) -> dict:
        task = (task or "").strip()
        if not task:
            return {"status": "error", "error": "Falta la tarea a programar."}

        self.ensure_server()

        # Candidatos de modelo: principal + cadena de respaldos (doble o mas
        # fallbacks). La logica de reintento ya recorre la lista completa:
        # si el modelo idx falla por disponibilidad, prueba el idx+1.
        candidates = [self.model] if self.model else []
        for m in getattr(self, "fallback_models", []):
            if m and m not in candidates:
                candidates.append(m)

        last_error = None
        last_result = None
        for idx, chosen in enumerate(candidates):
            is_fallback = idx > 0
            try:
                result = self._run_one(
                    task, directory, timeout, background, chosen
                )
            except OpenCodeError as e:
                last_error = e
                if is_model_unavailable(e) and idx + 1 < len(candidates):
                    logger.warning(
                        "Modelo %s no disponible, probando respaldo %s: %s",
                        _model_label(chosen),
                        _model_label(candidates[idx + 1]),
                        e,
                    )
                    continue
                return {"status": "error", "error": str(e)}

            last_result = result

            # Si la tarea termino con error atribuible al modelo, reintentar.
            if (
                result.get("status") == "error"
                and idx + 1 < len(candidates)
                and is_model_unavailable(result.get("error"))
            ):
                logger.warning(
                    "Modelo %s fallo por disponibilidad, probando respaldo %s: %s",
                    _model_label(chosen),
                    _model_label(candidates[idx + 1]),
                    result.get("error"),
                )
                continue

            if is_fallback:
                result["fallback_used"] = True
            return result

        if last_result is not None:
            return last_result
        return {
            "status": "error",
            "error": str(last_error) if last_error else "No se pudo ejecutar la tarea.",
        }

    def _run_one(
        self,
        task: str,
        directory: str | None,
        timeout: int | None,
        background: bool,
        model_override: dict | None,
    ) -> dict:
        chosen = model_override or self.model
        target, created = self.resolve_directory(directory)

        session = self.create_session(target, title="JARVIS: " + task, model=chosen)
        session_id = session["id"]
        logger.info(
            "OpenCode: tarea encolada session=%s dir=%s model=%s (%d chars)",
            session_id,
            target,
            _model_label(chosen),
            len(task),
        )

        started = time.time()
        prompt = self.send_prompt(session_id, task)
        prompt_created = (prompt.get("time") or {}).get("created") or 0

        result = {
            "status": "running",
            "session_id": session_id,
            "directory": target,
            "created_directory": created,
            "model": _model_label(session) or _model_label(chosen),
        }

        if background:
            result["message"] = (
                "Tarea lanzada en segundo plano. Usa opencode_result con este "
                "session_id para saber como termino."
            )
            return result

        limit = self.wait_timeout if timeout is None else int(timeout)
        if limit <= 0:
            result["message"] = "Tarea lanzada (opencode.wait_timeout=0)."
            return result

        try:
            messages = self._collect(session_id, prompt_created, limit)
        except OpenCodeTimeout:
            result["message"] = (
                "La tarea sigue en ejecucion. Usa opencode_result con este "
                "session_id para recoger el resultado."
            )
            result["elapsed_seconds"] = round(time.time() - started, 1)
            return result

        result.update(self.summarize(messages, prompt_created))
        result["status"] = "completed" if result.get("answer") else "error"
        result["elapsed_seconds"] = round(time.time() - started, 1)
        if not result.get("answer"):
            error = self.final_answer(messages, prompt_created) or {}
            detail = (error.get("error") or {}).get("message") if isinstance(
                error.get("error"), dict
            ) else error.get("error")
            result["error"] = detail or "OpenCode termino sin dar una respuesta."
        logger.info(
            "OpenCode: tarea %s en %.1fs (session=%s)",
            result["status"],
            result["elapsed_seconds"],
            session_id,
        )
        return result

    def get_result(self, session_id: str, timeout: int | None = None) -> dict:
        session_id = (session_id or "").strip()
        if not session_id:
            return {"status": "error", "error": "Falta el session_id."}

        self.ensure_server()
        limit = self.wait_timeout if timeout is None else int(timeout)
        result: dict = {"session_id": session_id}
        if limit > 0:
            try:
                messages = self._collect(session_id, 0, limit)
                result.update(self.summarize(messages, 0))
                result["status"] = "completed" if result.get("answer") else "error"
                if not result.get("answer"):
                    result["error"] = "La sesion no devolvio una respuesta."
                return result
            except OpenCodeTimeout:
                pass
        result["status"] = "running"
        result["message"] = "La tarea sigue en ejecucion."
        return result

    def list_sessions(self, limit: int = 10, directory: str | None = None) -> dict:
        self.ensure_server()
        query = ""
        if directory:
            target, _ = self.resolve_directory(directory)
            query = "?" + urllib.parse.urlencode({"directory": target})
        data = self._request("GET", f"/api/session{query}")
        items = ((data or {}).get("data") or [])[: max(int(limit), 1)]
        sessions = []
        for item in items:
            stamp = (item.get("time") or {}).get("updated") or 0
            sessions.append(
                {
                    "session_id": item.get("id"),
                    "title": item.get("title") or "",
                    "outcome": item.get("outcome") or "",
                    "updated": _iso(stamp),
                    "directory": (item.get("location") or {}).get("directory") or "",
                }
            )
        return {"sessions": sessions}

    # -- MCP ----------------------------------------------------------
    def _mcp_path(self, suffix: str = "", directory: str | None = None) -> str:
        path = f"/api/experimental/mcp{suffix}"
        if directory:
            target, _ = self.resolve_directory(directory)
            path += "?" + urllib.parse.urlencode({"location[directory]": target})
        return path

    def mcp(self, action: str, server: str = "", url: str = "", command: str = "",
            directory: str | None = None) -> dict:
        action = (action or "list").strip().lower()
        known = {
            "list", "lista", "listar",
            "add", "agregar", "anadir", "añadir",
            "remove", "quitar", "eliminar",
            "connect", "conectar",
            "disconnect", "desconectar",
        }
        if action not in known:
            return {
                "status": "error",
                "error": (
                    f"Accion MCP desconocida: '{action}'. Usa list, add, remove, "
                    "connect o disconnect."
                ),
            }

        self.ensure_server()

        if action in ("list", "lista", "listar"):
            path = "/api/mcp"
            if directory:
                target, _ = self.resolve_directory(directory)
                path += "?" + urllib.parse.urlencode({"location[directory]": target})
            data = self._request("GET", path)
            servers = []
            for item in (data or {}).get("data") or []:
                status = item.get("status") or {}
                servers.append(
                    {
                        "name": item.get("name"),
                        "status": status.get("status") or "unknown",
                        "error": status.get("error") or "",
                    }
                )
            return {"servers": servers}

        server = (server or "").strip()
        if not server:
            return {"status": "error", "error": "Falta el nombre del servidor MCP."}

        quoted = urllib.parse.quote(server, safe="")

        if action in ("add", "agregar", "anadir", "añadir"):
            if url:
                config = {"type": "remote", "url": url.strip()}
            elif command:
                import shlex

                config = {"type": "local", "command": shlex.split(command)}
            else:
                return {
                    "status": "error",
                    "error": "Para agregar un MCP necesito 'url' (remoto) o 'command' (local).",
                }
            self._request("PUT", self._mcp_path(f"/{quoted}", directory), {"config": config})
            return {"status": "ok", "message": f"Servidor MCP '{server}' agregado.", "config": config}

        if action in ("remove", "quitar", "eliminar"):
            self._request("DELETE", self._mcp_path(f"/{quoted}", directory))
            return {"status": "ok", "message": f"Servidor MCP '{server}' eliminado."}

        if action in ("connect", "conectar"):
            self._request("POST", self._mcp_path(f"/{quoted}/connect", directory), {})
            return {"status": "ok", "message": f"Servidor MCP '{server}' conectado."}

        if action in ("disconnect", "desconectar"):
            self._request("POST", self._mcp_path(f"/{quoted}/disconnect", directory), {})
            return {"status": "ok", "message": f"Servidor MCP '{server}' desconectado."}

        return {
            "status": "error",
            "error": f"Accion MCP desconocida: '{action}'. Usa list, add, remove, connect o disconnect.",
        }


# ── Utilidades ─────────────────────────────────────────────────────────────

def _unique(values: list[str]) -> list[str]:
    seen = set()
    out = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


def _iso(timestamp_ms) -> str:
    try:
        stamp = float(timestamp_ms) / 1000.0
    except (TypeError, ValueError):
        return ""
    if stamp <= 0:
        return ""
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(stamp))


def _model_label(session_or_model) -> str:
    data = session_or_model if isinstance(session_or_model, dict) else {}
    model = data.get("model") if isinstance(data.get("model"), dict) else data
    if not model:
        return ""
    provider = model.get("providerID") or ""
    model_id = model.get("id") or model.get("modelID") or ""
    if provider and model_id:
        return f"{provider}/{model_id}"
    return model_id


_client: OpenCodeClient | None = None
_client_lock = threading.Lock()


def get_client() -> OpenCodeClient:
    global _client
    with _client_lock:
        if _client is None:
            _client = OpenCodeClient()
        return _client


def reset_client() -> None:
    """Olvida el cliente (util en tests o al recargar config.json)."""
    global _client
    with _client_lock:
        _client = None


def stop_server() -> None:
    """Hook de cierre: solo detiene el servidor si asi esta configurado."""
    if _client is not None:
        _client.stop_server()


# ── Tools para Gemini ──────────────────────────────────────────────────────

@register_tool("opencode_code")
def opencode_code(task: str, directory: str = "", background: bool = False) -> dict:
    """Delega una tarea de programacion al agente de OpenCode."""
    client = get_client()
    # Si no se indico carpeta, trabajar por defecto en la ULTIMA carpeta que
    # el usuario abrio con open_vscode_folder (su proyecto actual), no en la
    # carpeta del proyecto JARVIS.
    directory = (directory or "").strip()
    if not directory:
        try:
            from tools import system as _system

            last = _system.last_vscode_folder()
            if last:
                directory = last
                logger.info(
                    "opencode_code: sin directory, uso el proyecto abierto: %s", last
                )
        except Exception:
            pass
    return client.run_task(task, directory=directory, background=background)


@register_tool("opencode_result")
def opencode_result(session_id: str, wait_seconds: int = 0) -> dict:
    """Recoge el resultado de una tarea lanzada antes."""
    client = get_client()
    timeout = int(wait_seconds) if int(wait_seconds or 0) > 0 else None
    return client.get_result(session_id, timeout=timeout)


@register_tool("opencode_sessions")
def opencode_sessions(limit: int = 10, directory: str = "") -> dict:
    """Lista las sesiones recientes de OpenCode."""
    client = get_client()
    return client.list_sessions(limit=int(limit or 10), directory=directory or None)


@register_tool("opencode_mcp")
def opencode_mcp(
    action: str = "list", server: str = "", url: str = "", command: str = "",
    directory: str = "",
) -> dict:
    """Lista, agrega, quita, conecta o desconecta servidores MCP."""
    client = get_client()
    return client.mcp(
        action,
        server=server,
        url=url,
        command=command,
        directory=directory or None,
    )


def _click_opencode_input(window_title: str) -> bool:
    """Hace clic en el input de la TUI de OpenCode dentro de VS Code.

    El input de la TUI de opencode arranca SIN foco (estilo vim): sin este
    clic, el texto que envia pyautogui no entra en ningun lado — el usuario
    lo hace manualmente con el mouse. El input ocupa las ultimas lineas del
    panel de terminal, justo encima de la statusbar de VS Code (~22px), asi
    que clicamos cerca del borde inferior-centro de la ventana.
    """
    try:
        from tools import window_tools

        import pyautogui as _pg

        found = window_tools.find_window(window_title)
        if not found:
            logger.warning("click input opencode: no encontre la ventana %r", window_title)
            return False
        win, _real = found
        offset = int(
            get_config().get("input", {}).get("opencode_input_click_offset", 55) or 55
        )
        x = int(win.left + win.width / 2)
        y = int(win.top + win.height - offset)
        _pg.moveTo(x, y, duration=0.15)
        time.sleep(0.1)
        _pg.click(x, y)
        logger.info("Clic en el input de opencode: (%s, %s) [offset=%s]", x, y, offset)
        return True
    except Exception as e:
        logger.warning("No se pudo hacer clic en el input de opencode: %s", e)
        return False


@register_tool("opencode_code_visual")
def opencode_code_visual(
    task: str, window: str = "Visual Studio Code", wait_seconds: int = 15
) -> dict:
    """Envia un prompt al panel de OpenCode en VS Code (terminal integrada) para
    que el usuario vea en vivo como trabaja OpenCode. No devuelve resultado
    estructurado: toma una captura de pantalla al final."""
    task = (task or "").strip()
    if not task:
        return {"status": "error", "error": "Falta la tarea a programar."}

    # Si el usuario acaba de abrir un proyecto con open_vscode_folder, apuntar
    # a ESA ventana (el titulo contiene el nombre de la carpeta) para no
    # escribir el prompt en otra ventana de VS Code.
    try:
        from tools import system as _system

        last = _system.last_vscode_folder()
        if last and (not window or window == "Visual Studio Code"):
            window = os.path.basename(last)
            logger.info("opencode_code_visual: ventana objetivo = %s", window)
    except Exception:
        pass

    try:
        from tools import window_tools, input_tools, screen_tools
    except Exception as e:
        return {
            "status": "error",
            "error": f"No pude cargar las tools de ventana/input/pantalla: {e}",
        }

    # 1. Poner VS Code en primer plano.
    try:
        window_tools._activate_window(title=window)
    except Exception as e:  # pragma: no cover - depende del SO/ventana
        logger.warning("opencode_code_visual: activate_window fallo: %s", e)
    time.sleep(0.6)

    # 1b. CLIC EN EL INPUT DE OPENCODE. El input de la TUI arranca SIN foco
    # (estilo vim): sin este clic el texto no entra en ningun lado. Despues
    # del clic NO volvemos a activar la ventana (write/enter sin 'window')
    # para no perder el foco interno que acabamos de ganar.
    input_clicked = _click_opencode_input(window)
    time.sleep(0.4)

    # 2. Escribir el prompt en la terminal de OpenCode (sin 'window': la
    # ventana ya esta activada y el input enfocado con el clic; re-activar
    # podria perder el foco del input). _type_text maneja acentos/ñ con el
    # portapapeles cuando hace falta.
    try:
        input_tools._type_text(text=task)
        logger.info("Prompt escrito en la TUI de opencode (%d chars)", len(task))
    except Exception as e:
        return {"status": "error", "error": f"No pude escribir el prompt en VS Code: {e}"}
    time.sleep(0.5)

    # 3. Enviar (Enter), tambien sin 'window' para no perder el foco.
    try:
        input_tools._press_key(key="enter")
        logger.info("Enter enviado a la TUI de opencode")
    except Exception as e:
        return {"status": "error", "error": f"No pude pulsar Enter en VS Code: {e}"}

    # 4. Esperar a que OpenCode procese.
    time.sleep(max(int(wait_seconds or 0), 1))

    # 5. Capturar la pantalla para ver el resultado.
    screenshot_path = None
    try:
        shot = screen_tools._take_screenshot()
        if isinstance(shot, dict):
            screenshot_path = (
                shot.get("image_path")
                or shot.get("path")
                or shot.get("file")
                or shot.get("screenshot")
                or shot.get("image")
            )
    except Exception as e:  # pragma: no cover - depende del SO
        logger.warning("opencode_code_visual: take_screenshot fallo: %s", e)

    return {
        "status": "sent",
        "window": window,
        "input_clicked": input_clicked,
        "waited_seconds": wait_seconds,
        "screenshot": screenshot_path,
        "note": (
            "El prompt se escribio en el input de OpenCode en VS Code "
            "(primero se hace clic en el input para enfocarlo, porque la TUI "
            "arranca sin foco) y se envio con Enter. JARVIS no recibe "
            "respuesta estructurada por esta via; revisa la captura de "
            "pantalla (screenshot) para ver si OpenCode lo recibio y esta "
            "trabajando. Si input_clicked es false, el clic al input fallo "
            "y el texto pudo no llegar."
        ),
    }
