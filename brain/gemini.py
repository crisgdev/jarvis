import logging
import time

from google import genai
from google.genai import types

from config import get_env, get_config
from brain import router
from brain.prompts import PROMPT_CORE, build_prompt
from brain.tools_definitions import tools_for
from brain.tools_executor import execute_tool, get_risk_level, execute_dangerous_tool
from brain.tool_labels import describe_tool_call
from memory import database as memory_db
from memory.context import (
    build_system_context,
    build_gemini_history,
    get_current_session_id,
    get_recent_user_messages,
)
from utils import turn_log

logger = logging.getLogger("jarvis.gemini")

# Alias historico: el prompt SOLO con el nucleo. El prompt real de cada turno
# lo arma _build_system_prompt() con los packs que elige el router
# (brain/router.py), asi una pregunta simple no paga las reglas de
# programacion, calendario o cuentas de Google.
SYSTEM_PROMPT = PROMPT_CORE

# Lista de respaldo por defecto. Se puede sustituir en config.json ->
# llm.fallback_models (que es lo que se usa normalmente).
FALLBACK_MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-3.6-flash",
    "gemini-3.1-flash-lite",
    "gemini-flash-lite-latest",
]

# Modelos que NO aceptan thinking_config (devuelven 400 INVALID_ARGUMENT)
NO_THINKING_MODELS = ("gemini-3.5-flash-lite", "gemini-flash-lite-latest")

# Presupuesto minimo de salida cuando una respuesta llega vacia por truncado
MIN_RETRY_OUTPUT_TOKENS = 1024

# Frases con las que el modelo admite que no puede hacer algo. Solo se usan
# para detectar un fallo del router (turno sin pack reconocido) y reintentar
# el turno con TODAS las herramientas.
REFUSAL_MARKERS = (
    "no puedo",
    "no tengo",
    "no cuento con",
    "no dispongo",
    "no me es posible",
    "no soy capaz",
    "no tengo acceso",
    "no tengo la capacidad",
    "no esta disponible",
    "no está disponible",
    "no tengo esa herramienta",
    "no tengo herramientas",
)


def _result_ok(result) -> bool:
    """¿La tool termino bien? (para pintar la subtarea de verde o rojo)."""
    if not isinstance(result, dict):
        return True
    if result.get("error"):
        return False
    return result.get("status") not in ("error", "cancelled")


def _response_text(response) -> str:
    """Texto de una respuesta aunque el SDK no exponga `.text`.

    La propiedad `.text` de google-genai es comoda pero puede ser None (o no
    existir en objetos simulados) aunque las partes si traigan texto.
    """
    text = getattr(response, "text", None)
    if text:
        return text
    try:
        parts = response.candidates[0].content.parts
    except Exception:
        return ""
    return "\n".join(
        part.text for part in parts if getattr(part, "text", None)
    )


def _parse_plan(args: dict) -> list[str]:
    """Normaliza los pasos que manda la tool show_plan."""
    raw = args.get("steps") or args.get("plan") or []
    if isinstance(raw, str):
        raw = raw.splitlines()
    steps = []
    for item in raw:
        if isinstance(item, dict):
            text = (
                item.get("step")
                or item.get("title")
                or item.get("label")
                or item.get("text")
                or ""
            )
        else:
            text = item
        text = str(text).strip().lstrip("-*\u2022 0123456789.)")
        text = " ".join(text.split())
        if text:
            steps.append(text[:70])
    return steps[:8]


class GeminiBrain:
    _system_prompt: str = SYSTEM_PROMPT
    _context_fp: tuple | None = None

    def __init__(self, detailed: bool = False):
        self.config = get_config()
        self._detailed = detailed
        api_key = get_env("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY no configurada en .env")

        llm_cfg = self.config.get("llm", {})
        routing_cfg = llm_cfg.get("routing", {}) or {}

        self._default_model = llm_cfg.get("model", "gemini-3.5-flash-lite")
        self.max_turns = llm_cfg.get("max_history_turns", 8)
        self.max_output_tokens = llm_cfg.get("max_output_tokens", 200)
        self.temperature = llm_cfg.get("temperature", 0.7)

        # Router de turno: elige packs de prompt, subconjunto de tools y modelo.
        self._routing_enabled = bool(routing_cfg.get("enabled", True))
        self._fast_model = routing_cfg.get("fast_model") or self._default_model
        self._strong_model = routing_cfg.get("strong_model") or self._default_model
        self._fast_history_turns = int(
            routing_cfg.get("fast_history_turns", 6) or 6
        )
        self._strong_history_turns = int(
            routing_cfg.get("strong_history_turns", self.max_turns) or self.max_turns
        )
        self._escalate_on_failure = bool(routing_cfg.get("escalate_on_failure", True))
        self._full_tools_on_unknown = bool(
            routing_cfg.get("full_tools_on_unknown", True)
        )

        self.model = self._default_model
        self._history_turns = self.max_turns

        self.client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=45000),
        )
        self._confirm_cb = None
        self._exchanges = 0
        self._retried_empty = False
        self._system_prompt = SYSTEM_PROMPT
        self._context_fp = None
        # Ruta vigente del turno (brain/router.py) y clave para no recrear el
        # chat cuando la ruta no cambia.
        self._route = None
        self._route_key = None
        # Metricas del turno en curso (se escriben en logs/turns.jsonl).
        self._turn_tools = ()
        self._turn_iterations = 0
        self._turn_escalated = False
        self._turn_finish_reason = None
        self._turn_ok = True
        self._turn_tokens = {}
        self._full_tools_retried = False
        # Artefactos visuales del ultimo turno (capturas de pantalla).
        # Los canales los usan para enviarlos al usuario (Telegram: foto).
        self.artifacts: list[dict] = []
        self._on_artifact_cb = None
        self._task_cb = None
        self._create_chat(self.model)

        logger.info(
            "GeminiBrain inicializado (model=%s, routing=%s)",
            self.model,
            self._routing_enabled,
        )

    def set_confirmation_callback(self, cb):
        self._confirm_cb = cb

    def set_artifact_callback(self, cb):
        """Callback invocado cada vez que se registra un artefacto (captura).

        Permite a los canales (Telegram) enviar la captura al usuario de
        inmediato, sin esperar a que termine el turno.
        """
        self._on_artifact_cb = cb

    def set_task_callback(self, cb):
        """Eventos de subtareas para la GUI (plan / task_start / task_done)."""
        self._task_cb = cb

    def _emit_task(self, kind: str, **data):
        # getattr: los tests construyen el cerebro con __new__ y sin callback.
        cb = getattr(self, "_task_cb", None)
        if cb is None:
            return
        event = {"kind": kind}
        event.update(data)
        try:
            cb(event)
        except Exception as e:
            logger.debug("Error en callback de tareas: %s", e)

    # ── Router de turno ──────────────────────────────────────────────────

    def _apply_route(self, text: str):
        """Decide prompt/tools/modelo para este turno.

        Recrear el chat es una operacion local (no gasta tokens), asi que solo
        se hace cuando cambia la ruta: mismo tema + mismo modelo = mismo chat.
        """
        enabled = bool(getattr(self, "_routing_enabled", True))
        detailed = bool(getattr(self, "_detailed", False))
        try:
            route = router.route(text, detailed, enabled=enabled)
        except Exception as e:  # el router nunca debe tumbar un turno
            logger.warning("Router fallo (%s); se usan todas las tools", e)
            route = router.route("", detailed, enabled=False)

        fast = getattr(self, "_fast_model", self.model)
        strong = getattr(self, "_strong_model", self.model)
        target = strong if route.tier == "strong" else fast

        if route.tier == "strong":
            self._history_turns = getattr(
                self, "_strong_history_turns", self.max_turns
            )
        else:
            self._history_turns = getattr(self, "_fast_history_turns", self.max_turns)

        self._route = route
        self._turn_tools = route.tools

        key = (target, route.key)
        if getattr(self, "_route_key", None) != key:
            self._route_key = key
            logger.info(
                "Ruta: packs=%s tier=%s model=%s tools=%d (%s)",
                list(route.packs) or "-",
                route.tier,
                target,
                len(route.tools),
                route.reason,
            )
            self._create_chat(target, history=self._history())
            self._exchanges = 0

    def _tool_subset(self):
        """Tools que viajan a Gemini en la ruta actual (None = todas)."""
        route = getattr(self, "_route", None)
        if route is None:
            return None
        return route.tools

    def _switch_to_full_tools(self):
        """Red de seguridad: reintenta el turno con las 53 herramientas."""
        route = router.Route(
            packs=tuple(router.PACK_TOOLS),
            tools=router.all_tool_names(),
            tier=getattr(self._route, "tier", "fast") if self._route else "fast",
            reason="router sin coincidencia: reintento con todas las tools",
            all_tools=True,
        )
        self._route = route
        self._turn_tools = route.tools
        self._route_key = (self.model, route.key)
        self._create_chat(self.model, history=self._history())
        self._exchanges = 0
        self._full_tools_retried = True
        self._turn_escalated = True
        logger.info(
            "Reintentando el turno con TODAS las tools (%d)", len(route.tools)
        )

    def _should_retry_with_full_tools(self, text: str) -> bool:
        """¿El router se quedo corto y el modelo se excusa por falta de tools?"""
        if not getattr(self, "_full_tools_on_unknown", False):
            return False
        if getattr(self, "_full_tools_retried", False):
            return False
        route = getattr(self, "_route", None)
        if route is None or route.all_tools or route.packs:
            return False
        low = (text or "").lower()
        return any(marker in low for marker in REFUSAL_MARKERS)

    # ── Contabilidad de tokens ───────────────────────────────────────────

    def _usage_enabled(self) -> bool:
        cfg = getattr(self, "config", None) or {}
        return bool(cfg.get("logging", {}).get("log_token_usage", True))

    def _accumulate_usage(self, response):
        usage = getattr(response, "usage_metadata", None)
        if usage is None:
            return
        bucket = getattr(self, "_turn_tokens", None)
        if bucket is None:
            bucket = {}
            self._turn_tokens = bucket
        for key, attr in (
            ("prompt", "prompt_token_count"),
            ("thoughts", "thoughts_token_count"),
            ("candidates", "candidates_token_count"),
            ("total", "total_token_count"),
        ):
            value = getattr(usage, attr, None)
            if value:
                bucket[key] = bucket.get(key, 0) + int(value)
        if self._usage_enabled():
            logger.debug("Tokens %s: %s", self.model, bucket)

    def _log_turn(self, user_text: str, started: float):
        if not turn_log.is_enabled():
            return
        route = getattr(self, "_route", None)
        try:
            turn_log.record(
                channel="chat" if getattr(self, "_detailed", False) else "voice",
                text=user_text,
                packs=list(route.packs) if route is not None else [],
                tier=route.tier if route is not None else "",
                reason=route.reason if route is not None else "",
                model=getattr(self, "model", ""),
                tools=len(getattr(self, "_turn_tools", ()) or ()),
                iterations=getattr(self, "_turn_iterations", 0),
                escalated=getattr(self, "_turn_escalated", False),
                latency_ms=int((time.monotonic() - started) * 1000),
                ok=getattr(self, "_turn_ok", True),
                finish_reason=getattr(self, "_turn_finish_reason", None),
                tokens=getattr(self, "_turn_tokens", {}) or {},
            )
        except Exception as e:  # el log nunca tumba el turno
            logger.debug("No se pudo registrar el turno: %s", e)

    # ── Chat de Gemini ───────────────────────────────────────────────────

    def _thinking_config(self):
        """thinking_budget configurable (0 = sin razonamiento, mas rapido).

        Algunos modelos (p. ej. gemini-3.5-flash-lite) NO aceptan este campo
        y responden 400 INVALID_ARGUMENT, asi que se omite en esos casos.
        """
        budget = self.config.get("llm", {}).get("thinking_budget")
        if budget is None:
            return None
        if any(name in self.model for name in NO_THINKING_MODELS):
            logger.debug("thinking_config omitido para %s", self.model)
            return None
        try:
            return types.ThinkingConfig(thinking_budget=budget)
        except Exception as e:
            logger.warning("thinking_budget=%s no soportado: %s", budget, str(e)[:120])
            return None

    def _create_chat(self, model: str, history=None):
        self.model = model
        self._system_prompt = self._build_system_prompt()
        # Fingerprint del contexto de MEMORIA (sin fecha ni hora). Solo se
        # recrea el chat cuando cambian las notas/preferencias/proyectos, no
        # por el paso del tiempo ni por el dia. El prompt completo ya no sirve
        # como fingerprint porque cambia en cada turno segun la ruta.
        self._context_fp = self._memory_fp()

        tool = tools_for(self._tool_subset())

        def _config(thinking):
            return types.GenerateContentConfig(
                system_instruction=self._system_prompt,
                tools=[tool],
                temperature=self.temperature,
                max_output_tokens=self.max_output_tokens,
                thinking_config=thinking,
            )

        thinking = self._thinking_config()
        try:
            self.chat = self.client.chats.create(
                model=model, config=_config(thinking), history=history
            )
        except Exception as e:
            # Si el modelo rechaza thinking_config, se recrea sin el.
            if thinking is not None and "INVALID_ARGUMENT" in str(e):
                logger.warning(
                    "%s rechazo thinking_budget: se recrea sin razonamiento", model
                )
                self.chat = self.client.chats.create(
                    model=model, config=_config(None), history=history
                )
            else:
                raise

    def _memory_fp(self):
        """Identidad del bloque de memoria persistente (para invalidar cache)."""
        try:
            return (
                memory_db.memory_version(),
                str(getattr(memory_db, "_db_path", "")),
            )
        except Exception:
            return None

    def _build_system_prompt(self, include_time: bool = True, include_date: bool = True) -> str:
        route = getattr(self, "_route", None)
        packs = route.packs if route is not None else None

        base = build_prompt(PROMPT_CORE, packs, bool(getattr(self, "_detailed", False)))

        context = build_system_context(
            include_time=include_time,
            include_date=include_date,
            packs=packs,
        )

        # Contexto reciente de la conversacion: ayuda al modelo a no perder
        # el hilo (evita "amnesia" sobre lo dicho hace un par de mensajes).
        # Solo en el prompt real (no en el fingerprint, que es estable).
        if include_date:
            recent = get_recent_user_messages(4)
            if recent:
                base = base + "\n\n" + recent
        if context:
            return (
                f"{base}\n\nINFORMACION ACTUAL (nombre del usuario, "
                f"preferencias, notas y proyectos guardados; usala para llamarlo "
                f"por su nombre y personalizar respuestas):\n{context}"
            )
        return base

    def _history(self):
        sid = get_current_session_id()
        if not sid:
            return None
        turns = getattr(self, "_history_turns", None) or self.max_turns
        return build_gemini_history(sid, max_turns=turns + 2) or None

    def _maybe_refresh_context(self):
        fp = self._memory_fp()
        if fp is None:
            return
        if getattr(self, "_context_fp", None) != fp:
            logger.info("Memoria actualizada, recreando chat con nuevo contexto")
            self._create_chat(self.model, history=self._history())
            self._exchanges = 0

    def _try_send(self, content):
        for attempt in range(3):
            try:
                return self.chat.send_message(content)
            except Exception as e:
                err_str = str(e)
                if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                    logger.warning("Cuota agotada en %s, intentando fallback...", self.model)
                    return None
                if (
                    "503" in err_str
                    or "UNAVAILABLE" in err_str
                    or "timed out" in err_str.lower()
                    or "timeout" in err_str.lower()
                    or "connect" in err_str.lower()
                ):
                    wait = 2 ** attempt
                    logger.warning("Gemini %s, reintento en %ds...", err_str[:120], wait)
                    time.sleep(wait)
                else:
                    logger.warning(
                        "Error de Gemini (%s): %s", self.model, err_str[:300]
                    )
                    return None
        return None

    def _image_part(self, result):
        """Convierte una captura en una Parte de imagen real para Gemini.

        El function_response solo transporta JSON, asi que la foto de la
        pantalla tiene que viajar aparte como Part.from_bytes para que el
        modelo la vea de verdad.
        """
        if not isinstance(result, dict):
            return None
        path = result.get("image_path")
        if not path:
            return None
        try:
            with open(path, "rb") as handle:
                data = handle.read()
            if not data:
                return None
            mime = "image/png" if str(path).lower().endswith(".png") else "image/jpeg"
            return types.Part.from_bytes(data=data, mime_type=mime)
        except Exception as e:
            logger.warning("No se pudo adjuntar la imagen %s: %s", path, e)
            return None

    def _register_artifact(self, result):
        """Guarda la captura del turno para que el canal la envie."""
        if not isinstance(result, dict):
            return
        path = result.get("image_path")
        if not path:
            return
        artifact = {
            "type": "image",
            "path": path,
            "caption": result.get("message", "Captura de pantalla"),
        }
        self.artifacts.append(artifact)
        # Notificacion inmediata al canal (Telegram envia la foto al instante)
        # sin esperar a que termine el turno completo.
        cb = getattr(self, "_on_artifact_cb", None)
        if cb is not None:
            try:
                cb(artifact)
            except Exception as e:
                logger.warning("Error en artifact callback: %s", e)

    def chat_message(self, user_text: str) -> str:
        """Turno completo del usuario, con eventos de subtareas para la GUI."""
        started = time.monotonic()
        self._turn_tools = ()
        self._turn_iterations = 0
        self._turn_escalated = False
        self._turn_finish_reason = None
        self._turn_ok = True
        self._turn_tokens = {}
        self._full_tools_retried = False

        self._emit_task("turn_start", text=user_text)
        try:
            return self._chat_message(user_text)
        finally:
            self._emit_task("turn_end")
            self._log_turn(user_text, started)

    def _chat_message(self, user_text: str) -> str:
        logger.info("Usuario: %s", user_text[:100])

        # 1) Router: decide packs de prompt, tools y modelo ANTES de hablar
        #    con Gemini. Recrea el chat solo si la ruta cambio.
        self._apply_route(user_text)

        # 2) Memoria: si nota/preferencia/proyecto cambio, refresca el contexto.
        self._maybe_refresh_context()
        self.artifacts = []

        if self._exchanges >= self.max_turns:
            logger.info("Contexto reiniciado (max %d turnos)", self.max_turns)
            self._create_chat(self.model, history=self._history())
            self._exchanges = 0
        self._exchanges += 1
        self._retried_empty = False

        max_iterations = 8
        # Primer turno: texto del usuario. Turnos siguientes: solo las
        # respuestas (function_response) de las tools ejecutadas.
        content = user_text

        # Cache de aprobacion por turno del usuario: si en un mismo turno
        # Gemini pide varias veces la MISMA tool peligrosa (ej: borrar varios
        # eventos), se confirma una sola vez y el resto se ejecuta directo.
        turn_approval = {}

        for iteration in range(max_iterations):
            self._turn_iterations = iteration + 1
            response = self._try_send(content)

            if response is None:
                fallback = self._try_fallback(content)
                if fallback:
                    response = fallback
                    self._turn_escalated = True
                else:
                    self._turn_ok = False
                    return "Se agotó la cuota de Gemini. Intenta de nuevo en unos minutos."

            self._accumulate_usage(response)

            if not response.candidates:
                logger.warning("Sin candidates en respuesta")
                self._turn_ok = False
                return "No pude generar una respuesta."

            candidate = response.candidates[0]
            finish = getattr(candidate, "finish_reason", None)
            self._turn_finish_reason = str(getattr(finish, "value", finish)) if finish is not None else None

            if not candidate.content or not candidate.content.parts:
                logger.warning(
                    "Respuesta sin parts: %s", self._response_debug_info(response)
                )
                self._turn_ok = False
                return "No pude generar una respuesta."

            function_calls = [
                part.function_call
                for part in candidate.content.parts
                if part.function_call
            ]

            if not function_calls:
                text_parts = [p.text for p in candidate.content.parts if p.text]
                if not text_parts:
                    info = self._response_debug_info(response)
                    logger.warning("Respuesta de Gemini SIN TEXTO: %s", info)

                    # Truncado por max_output_tokens (o finish_reason desconocido):
                    # reintenta UNA vez con mas presupuesto antes de rendirse.
                    if not self._retried_empty and self._can_retry_empty(info, content):
                        self._retried_empty = True
                        self._grow_token_budget()
                        continue

                    reason = info.get("finish_reason") or "sin finish_reason"
                    self._turn_ok = False
                    return (
                        f"No pude generar una respuesta ({reason}). "
                        "Intenta de nuevo en un momento."
                    )

                final_text = "\n".join(text_parts)

                # 3) Red de seguridad del router: si el turno no tenia pack
                #    reconocido y el modelo se excusa por falta de herramientas,
                #    se reintenta el MISMO turno con las 53 tools.
                if self._should_retry_with_full_tools(final_text):
                    logger.info(
                        "Router sin coincidencia + respuesta de limite; reintento completo"
                    )
                    self._switch_to_full_tools()
                    content = user_text
                    continue

                logger.info("JARVIS: %s", final_text[:100])
                return final_text

            content_parts = []
            for index, fc in enumerate(function_calls):
                tool_name = fc.name
                tool_args = dict(fc.args) if fc.args else {}

                if tool_name == "show_plan":
                    steps = _parse_plan(tool_args)
                    if steps:
                        self._emit_task("plan", steps=steps)
                        logger.info("Plan declarado por Gemini: %s", steps)
                    result = {"status": "ok", "message": "Plan mostrado al usuario."}
                    content_parts.append(
                        types.Part(
                            function_response=types.FunctionResponse(
                                name=tool_name,
                                response=result,
                            )
                        )
                    )
                    continue

                task_id = f"{tool_name}-{iteration}-{index}"
                self._emit_task(
                    "task_start",
                    id=task_id,
                    tool=tool_name,
                    label=describe_tool_call(tool_name, tool_args),
                )

                risk = get_risk_level(tool_name)
                logger.info(
                    "Tool call: %s(%s) [risk=%s]",
                    tool_name,
                    tool_args,
                    risk,
                )

                if risk == "dangerous":
                    if tool_name in turn_approval:
                        if turn_approval[tool_name]:
                            result = execute_tool(tool_name, tool_args)
                        else:
                            logger.info(
                                "Tool %s auto-cancelada (usuario ya la rechazo este turno)",
                                tool_name,
                            )
                            result = {
                                "status": "cancelled",
                                "message": f"El usuario cancelo la accion '{tool_name}'.",
                            }
                    else:
                        result = execute_dangerous_tool(
                            tool_name, tool_args, self._confirm_cb
                        )
                        turn_approval[tool_name] = not (
                            isinstance(result, dict)
                            and result.get("status") == "cancelled"
                        )
                else:
                    result = execute_tool(tool_name, tool_args)

                self._emit_task(
                    "task_done",
                    id=task_id,
                    tool=tool_name,
                    ok=_result_ok(result),
                )

                content_parts.append(
                    types.Part(
                        function_response=types.FunctionResponse(
                            name=tool_name,
                            response=result,
                        )
                    )
                )

                # Si la tool devolvio una captura, se la mandamos al modelo
                # como imagen real (justo despues de su function_response,
                # para que la asocie con esa tool) y la guardamos para el
                # canal (Telegram la envia como foto).
                self._register_artifact(result)
                image_part = self._image_part(result)
                if image_part is not None:
                    content_parts.append(image_part)

            # El siguiente turno es la respuesta de las tools; esto hace que
            # Gemini continúe (con más tools o con texto final).
            content = content_parts

        self._turn_ok = False
        return "No pude completar el procesamiento."

    def _response_debug_info(self, response):
        """Diagnostico de una respuesta sin texto (finish_reason + tokens)."""
        finish = None
        candidates = getattr(response, "candidates", None) or []
        if candidates:
            finish = getattr(candidates[0], "finish_reason", None)
        # FinishReason es un enum str: usar .value para comparar con "MAX_TOKENS".
        finish_value = getattr(finish, "value", finish)

        info = {"finish_reason": str(finish_value) if finish_value is not None else None}

        usage = getattr(response, "usage_metadata", None)
        if usage is not None:
            info["tokens"] = {
                "thoughts": getattr(usage, "thoughts_token_count", None),
                "candidates": getattr(usage, "candidates_token_count", None),
                "total": getattr(usage, "total_token_count", None),
            }
        return info

    def _can_retry_empty(self, info, content):
        # Solo se puede reenviar texto del usuario: un function_response
        # suelto en un chat nuevo es INVALID_ARGUMENT.
        if not isinstance(content, str) or not content.strip():
            return False
        return info.get("finish_reason") in (None, "MAX_TOKENS")

    def _grow_token_budget(self):
        nuevo = max(int(self.max_output_tokens) * 2, MIN_RETRY_OUTPUT_TOKENS)
        logger.info(
            "Respuesta vacia: subiendo max_output_tokens de %s a %d",
            self.max_output_tokens,
            nuevo,
        )
        self.max_output_tokens = nuevo
        self._create_chat(self.model, history=self._history())

    # ── Respaldo de modelo ───────────────────────────────────────────────

    def _configured_fallbacks(self) -> list[str]:
        """Modelos de respaldo de config.json (o la lista por defecto)."""
        cfg = getattr(self, "config", None) or {}
        models = cfg.get("llm", {}).get("fallback_models")
        if isinstance(models, str):
            models = [models]
        if not models:
            models = list(FALLBACK_MODELS)
        out = []
        for model in models:
            name = str(model).strip()
            if name and name not in out:
                out.append(name)
        return out

    def _fallback_candidates(self) -> list[str]:
        """Orden de reintento: primero el modelo fuerte (si escalamos)."""
        current = getattr(self, "model", "")
        ordered: list[str] = []
        if getattr(self, "_escalate_on_failure", False):
            strong = getattr(self, "_strong_model", None)
            if strong and strong != current:
                ordered.append(strong)
        for model in self._configured_fallbacks():
            if model != current and model not in ordered:
                ordered.append(model)
        return ordered

    def _try_fallback(self, content):
        """Cambia a un modelo de respaldo y REINTENTA el turno real del usuario.

        Antes mandaba 'Responde solo: OK' y devolvia esa respuesta, asi que el
        usuario veia un 'OK' sin relacion con su pregunta y el turno falso
        quedaba en el historial del chat.
        """
        if not isinstance(content, str) or not content.strip():
            logger.warning(
                "Fallback omitido: el turno pendiente es function_response, "
                "no se puede reenviar en un chat nuevo"
            )
            return None

        original = self.model
        for model in self._fallback_candidates():
            logger.info("Intentando modelo fallback: %s", model)
            try:
                self._create_chat(model, history=self._history())
                # Enviamos el mensaje ORIGINAL (sin envolver en "responde corto")
                # para que el modelo procese la petición real y llame las tools
                # necesarias (abrir correo, calendario, etc.), no solo texto.
                resp = self.chat.send_message(content)
                resp_text = _response_text(resp)
                # Aceptamos la respuesta si tiene texto útil O si tiene function_calls
                # (el modelo puede querer ejecutar una herramienta).
                has_text = bool(resp_text.strip()) and len(resp_text.strip()) >= 3
                has_tools = (
                    resp
                    and resp.candidates
                    and resp.candidates[0].content
                    and resp.candidates[0].content.parts
                    and any(p.function_call for p in resp.candidates[0].content.parts)
                )
                # Filtrar respuestas genéricas del tipo "No pude abrir..."
                # que no ayudan al usuario.
                generic_phrases = [
                    "no pude abrir",
                    "no pude acceder",
                    "no pude ejecutar",
                    "no pude realizar",
                    "no puedo abrir",
                    "no puedo acceder",
                    "no puedo ejecutar",
                    "no puedo realizar",
                    "te sugiero abrirlo directamente",
                    "te sugiero abrir directamente",
                    "abriendo tu navegador",
                    "abriendo el navegador",
                    "abriendo tu correo",
                    "abriendo tu calendario",
                ]
                text_lower = resp_text.lower()
                is_generic = any(phrase in text_lower for phrase in generic_phrases)
                # Filtrar alucinaciones: si el modelo dice que hizo algo pero
                # no llamó ninguna tool, es un alucinación y no sirve.
                is_hallucination = (
                    has_text
                    and not has_tools
                    and any(
                        phrase in text_lower
                        for phrase in [
                            "abriendo",
                            "abriendo tu",
                            "voy a abrir",
                            "he abierto",
                            "abri",
                            "abriré",
                            "abriendo la",
                            "abriendo el",
                        ]
                    )
                )
                if resp and (has_text or has_tools) and not is_generic and not is_hallucination:
                    logger.info("Fallback exitoso con %s", model)
                    return resp
                if is_generic or is_hallucination:
                    logger.warning(
                        "Fallback %s devolvió respuesta inútil (genérica o alucinación): %s",
                        model,
                        resp_text[:80],
                    )
                # Si no tiene buen texto ni tools, continúa al siguiente modelo
                logger.warning(
                    "Fallback %s devolvió respuesta inválida: %s",
                    model,
                    resp_text[:80] or "None",
                )
                continue
            except Exception as e:
                if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                    logger.warning("%s también sin cuota", model)
                    continue
                logger.warning("Fallback %s fallo: %s", model, str(e)[:200])
                break

        # Ningun modelo de respaldo funciono: volver al original para no
        # dejar el chat apuntando a un modelo que acaba de fallar.
        if self.model != original:
            logger.info("Restaurando modelo original %s", original)
            self._create_chat(original, history=self._history())
        return None
