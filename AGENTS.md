# JARVIS - Asistente de Voz Personal

## Descripción del Proyecto

JARVIS es un asistente de voz personal construido en Python, inspirado en el asistente de Iron Man. El usuario interactúa por voz en español, y JARVIS ejecuta tareas reales en la PC: abrir aplicaciones, buscar en internet, gestionar emails, calendario, memoria de proyectos, y más. Incluye una GUI completa con CustomTkinter.

## Stack Tecnológico

| Componente | Librería | Estado |
|---|---|---|
| Lenguaje | Python 3.14.6 | ✅ Instalado |
| IA / Cerebro | Google Gemini API (Flash) | ✅ API Key configurada |
| Speech-to-Text | faster-whisper (turbo, configurable en config.json `voice.stt_model`: small/turbo/medium/large-v3) | ✅ Instalado |
| Text-to-Speech | edge-tts (neural, español) | ✅ Instalado |
| Activación | Ctrl+Alt+Shift+J (una consulta) + Ctrl+Shift+J (modo llamada) + GUI buttons (teclado `keyboard`) | ✅ Instalado |
| GUI | CustomTkinter | ✅ Instalado |
| Memoria | SQLite (persistente) | Built-in Python |
| Búsqueda semántica | ChromaDB + sentence-transformers (opcional, apagada: `memory.semantic_search=false`) | Opcional |
| Navegador | webbrowser + duckduckgo-search (sin Playwright) | ✅ Instalado |
| Email | yagmail (Gmail SMTP) | ✅ App Password configurado |
| Calendar | Google Calendar API | ✅ credentials.json configurado |
| Automatización PC | psutil + subprocess | ✅ Instalado |
| Teclado/Ratón | pyautogui + pyperclip + pygetwindow | ✅ Instalado |
| Audio | sounddevice (captura) + pygame (reproducción) | ✅ Instalado |
| Chat (Telegram) | python-telegram-bot | ✅ Instalado |
| Activación por palmadas | sounddevice (detección de doble palmada) | ✅ Implementado (`voice.clap_enabled`) |

## API Keys y Credenciales

Las API keys están en el archivo `.env` (nunca commitear a git). Template en `.env.example`.

- **Gemini API Key**: Formato `AQ.Ab...` (formato nuevo Google 2026)
- **Gmail App Password**: Contraseña de 16 caracteres de Google
- **Google Calendar**: Archivo `credentials.json` en raíz del proyecto (OAuth2)
- **Telegram Bot Token**: `TELEGRAM_BOT_TOKEN` en `.env` (creado con BotFather)
- **Telegram Owner ID**: `TELEGRAM_ALLOWED_USER_IDS` en `.env` (ids del dueño separados por coma)

## Arquitectura del Pipeline de Voz

```
Usuario presiona Ctrl+Alt+Shift+J (una consulta)
  → Captura de audio del micrófono (sounddevice)
  → faster-whisper transcribe audio → texto
  → Gemini procesa texto + historial + tools disponibles
  → Gemini responde con texto O function_call(s)
  → Si function_call: ejecutar tool → resultado → Gemini genera respuesta final
  → edge-tts conviene respuesta a audio
  → Reproducir audio por altavoces (pygame)
  → Mostrar en GUI (CustomTkinter)
  → Guardar en SQLite (memoria persistente)
```

## Canal de Chat (Telegram)

```
Mensaje de texto en Telegram (solo dueno, TELEGRAM_ALLOWED_USER_IDS)
  → BRAIN: segunda instancia de GeminiBrain (modo detailed/markdown)
  → Gemini procesa texto + historial + tools disponibles
  → Si function_call DANGEROUS: boton inline Si/No (confirm_timeout)
  → Ejecutar tool → Gemini genera respuesta → texto markdown al chat
  → Guardar en SQLite (misma memoria que la voz)

Tambien acepta NOTAS DE VOZ y audios: se descargan a un tmp
(`jarvis_telegram/`), se transcriben con `stt.transcribe_file`
(faster-whisper directo al archivo .ogg) y el texto entra al mismo flujo.
```

Mismo cerebro y misma memoria que la voz: notas, proyectos, preferencias y
recuerdos se comparten (misma `jarvis_memory.db`). Cada canal mantiene su
propia conversacion en curso en el chat de Gemini.

## Tools Disponibles para Gemini

Gemini puede elegir automáticamente qué herramienta usar:

### Sistema
- `get_system_info`: Hora, fecha, CPU, memoria, disco, batería
- `open_application`: Abrir apps (chrome, spotify, vscode, notepad, explorer)
- `close_application`: Cerrar apps específicas o todas
- `control_volume`: Subir/bajar/silenciar volumen
- `wake_on_lan`: Encender por red una PC apagada de la LAN (usando `wol.mac` de config.json)
- `shutdown_pc`: Suspende la PC por defecto (para poder encenderla con WOL); apagado real solo con `mode='off'` (DANGEROUS - requiere confirmación)
- `restart_pc`: Reiniciar PC (DANGEROUS - requiere confirmación)

### Navegador
- `browse_url`: Abrir página web (webbrowser)
- `search_web`: Buscar en DuckDuckGo y extraer resultados (duckduckgo-search)
- `play_youtube_video`: Abrir en el navegador un video de YouTube por nombre (usa yt-dlp para resolver el primer resultado)
- `list_bookmarks`: Ver la barra de marcadores de Chrome (carpetas y páginas). Opcional `folder` (soporta rutas `pkmn/relo`)
- `open_bookmark`: Abrir un marcador por nombre o TODAS las páginas de una carpeta (`name`, opcional `max_tabs`, default `browser.max_tabs_per_folder`=8)

### Archivos
- `search_file`: Buscar archivo por nombre en la PC
- `read_file`: Leer contenido de archivo de texto
- `write_file`: Escribir/agregar contenido a un archivo (MODERATE)
- `delete_file`: Eliminar un archivo (DANGEROUS - requiere confirmación)

### Email
- `send_email`: Enviar email por Gmail (DANGEROUS - requiere confirmación explícita)
- `read_recent_emails`: Leer últimos emails recibidos

### Calendario
- `list_calendars`: Lista tus calendarios (nombre e id) para que Gemini ofrezca dónde guardar un evento
- `get_upcoming_events`: Ver próximos eventos (busca en TODOS los calendarios de la cuenta — "u", "c", "mi chamba", etc. — y cada evento indica en qué calendario está). Cada evento repetido incluye `recurrence` (RRULE) y `recurrence_text` en español (ej. "se repite semanal los lunes y jueves, y finaliza el 16 de octubre de 2026") para responder cómo se repite y hasta cuándo.
- `create_calendar_event`: Crear evento (MODERATE - requiere confirmación GUI; opcional `calendar`=nombre/id para crear en un calendario específico; soporta eventos repetidos con `recurrence` RRULE + `recurrence_until` — ej. "todos los martes hasta el 15 de octubre")
- `update_calendar_event`: Modificar evento existente (MODERATE - requiere confirmación GUI; cambia título, día/hora, duración, calendario — mover — y repetición; `recurrence` vacío quita la repetición; usa `event_id` de get_upcoming_events)
- `delete_calendar_event`: Eliminar evento (DANGEROUS - requiere confirmación; busca en todos los calendarios). Si Gemini pide borrar VARIOS eventos en el mismo turno del usuario, la confirmación se pide UNA sola vez y los demás se ejecutan directo (`turn_approval` en brain/gemini.py); si el usuario cancela, el resto del turno se auto-cancela.

### Memoria
- `save_note`: Guardar nota importante
- `recall_information`: Buscar en memoria pasada
- `forget_information`: Borrar de la memoria persistente las notas que mencionen ciertas palabras (edad, datos, etc.)
- `create_project`: Crear proyecto
- `add_project_note`: Agregar nota a proyecto
- `get_project_info`: Ver info de proyecto
- `list_projects`: Listar proyectos activos
- `update_project_status`: Cambiar estado de proyecto

### Pantalla, teclado, ratón y ventanas
- `take_screenshot`: Captura la pantalla (o una región `x,y,w,h`). **El cerebro adjunta la imagen REAL al modelo** (`brain/gemini.py` la lee del disco y la manda como `Part.from_bytes`), así que Gemini de verdad VE la pantalla. Opcional `region` y `max_width`.
- `press_key`: Pulsa cualquier tecla o combinación (`i`, `enter`, `escape`, `tab`, flechas, `f1`-`f24`, `ctrl+c`, `ctrl+shift+j`, `alt+f4`). Opcional `presses` y `window` (título de la ventana destino).
- `type_text`: Escribe texto en la ventana enfocada (o en la de `window`). ASCII con `pyautogui.write`; con acentos/ñ/emoji usa portapapeles + `ctrl+v` y **restaura el portapapeles original**. Nunca pulsa Enter.
- `click`: Clic del ratón, en `(x, y)` o donde esté el puntero. `button` (left/right/middle), `clicks`, `window`.
- `scroll`: Rueda del ratón (`up`/`down`/`left`/`right`, `amount`).
- `move_mouse` / `get_mouse_position`: Mover y leer el puntero.
- `list_windows`: Ventanas abiertas (la activa primero). `get_active_window`: la enfocada.
- `activate_window`: Poner una ventana en primer plano (con el truco de la tecla ALT para robar el foco, que Windows bloquea si no).
- `close_window`: Cerrar por título, o la ventana enfocada si se omite el título.
- `minimize_window` / `maximize_window`: Minimizar o maximizar.

### Código
- `run_python_code`: Ejecutar Python en sandbox (DANGEROUS - requiere confirmación)
- `opencode_code`: Delegar una tarea de PROGRAMACIÓN a OpenCode (crear/modificar archivos de un proyecto, escribir código, git, repos, comandos, instalar dependencias). Opcional `directory` y `background=True` para tareas largas
- `opencode_result`: Recoger el resultado de una tarea lanzada en background (`session_id`)
- `opencode_sessions`: Listar las tareas de programación recientes y su estado
- `opencode_mcp`: Controlar los servidores MCP de OpenCode (`list`/`add`/`remove`/`connect`/`disconnect`)

## Sistema de Permisos

| Nivel | Acciones | Confirmación |
|---|---|---|
| SAFE | Leer hora, info sistema, buscar archivo, abrir navegador | Auto |
| MODERATE | Abrir/cerrar apps, volumen, crear evento, guardar nota | GUI botón |
| DANGEROUS | Enviar email, apagar PC, eliminar, ejecutar código | Voz (sí/procede vs no/cancela) |

## Estructura del Proyecto

```
Jarvis/
├── main.py                    # Entry point
├── wake_listener.py           # Companion WOL standalone (corre en dispositivo siempre-encendido de la LAN)
├── enable_wol.ps1             # Activa Wake-on-LAN en Windows (admin, reversible con -Undo; backup en wol_backup/)
├── TERMUX_SETUP.md            # Guia: celular Android/Termux como listener de WOL
├── config.py                  # Carga de configuración
├── config.json                # Settings persistentes
├── requirements.txt           # Dependencias
├── .env                       # API keys (NO commitear)
├── .env.example               # Template de API keys
├── AGENTS.md                  # Este archivo - contexto del proyecto
├── PROJECT_PLAN.md            # Roadmap de desarrollo
├── credentials.json           # Google OAuth2 (NO commitear)
│
├── core/
│   ├── __init__.py
│   ├── jarvis.py              # Orquestador principal
│   ├── events.py              # Sistema de eventos proactivos
│   ├── voice_confirm.py       # Interpretacion de confirmaciones por voz
│   └── confirmations.py       # Labels/mensajes compartidos de acciones peligrosas
│
├── services/
│   ├── __init__.py
│   ├── audio.py               # Captura de audio
│   ├── stt.py                 # Speech-to-Text (faster-whisper)
│   ├── tts.py                 # Text-to-Speech (edge-tts)
│   ├── wake_word.py           # Hotkeys Ctrl+Alt+Shift+J (una consulta) y Ctrl+Shift+J (pausa/reanuda llamada)
│   ├── clap_detector.py       # Detector de doble palmada (activa JARVIS con un aplauso)
│   └── telegram_bot.py        # Bot de Telegram (mismo cerebro/memoria)
│
├── brain/
│   ├── __init__.py
│   ├── gemini.py              # Integración Gemini + tools
│   ├── tools_definitions.py   # Definiciones de tools
│   └── tools_executor.py      # Ejecutor con permisos
│
├── memory/
│   ├── __init__.py
│   ├── database.py            # SQLite CRUD
│   ├── context.py             # Gestión de contexto LLM
│   └── search.py              # Búsqueda semántica (ChromaDB)
│
├── tools/
│   ├── __init__.py
│   ├── system.py              # Comandos del sistema
│   ├── browser_tools.py       # Herramientas navegador
│   ├── bookmark_tools.py      # Marcadores de Chrome (barra, carpetas, páginas)
│   ├── file_tools.py          # Operaciones archivos
│   ├── email_tools.py         # Envío/lectura emails
│   ├── calendar_tools.py      # Google Calendar
│   ├── code_executor.py       # Ejecución código Python
│   ├── input_tools.py         # Teclado y ratón (pyautogui)
│   ├── window_tools.py        # Ventanas: listar, activar, cerrar (pygetwindow)
│   ├── screen_tools.py        # Captura de pantalla (Pillow) → imagen para Gemini
│   ├── opencode_tools.py      # Programar via OpenCode (API HTTP local): código, archivos, MCP
│
├── gui/
│   ├── __init__.py
│   ├── app.py                 # Ventana principal
│   ├── call_view.py           # Overlay animado del modo llamada (orbe + particulas)
│   ├── components.py          # Widgets reutilizables
│   ├── confirmation.py        # Diálogos de confirmación
│   └── tray.py                # Icono en la bandeja del sistema (pystray)
│
└── utils/
    ├── __init__.py
    └── logger.py              # Logging
```

## Preferencias del Usuario

- Idioma: Español
- Framework GUI: CustomTkinter
- LLM: Google Gemini Flash (gratis)
- Hardware: PC moderada (sin GPU dedicada)
- Activación de voz: Ctrl+Alt+Shift+J para UNA consulta (estado `listening` → procesa → vuelve a `idle`); Ctrl+Shift+J alterna el modo llamada. Orden de teclas configurables en `config.json` -> `voice.once_key` y `voice.activation_key` (futuro: openWakeWord).
- Base de datos: SQLite (no PostgreSQL)

## Notas Importantes

- STT (reconocimiento de voz): usa `faster-whisper`. Modelos disponibles en `config.json` -> `voice.stt_model`: `small` (RÁPIDO para CPU moderada, ~2-3s por frase; el recomendado para conversación fluida en esta PC; algo menos preciso), `turbo` (balance, ~5x más lento en esta CPU; más preciso), `medium` (lento, más preciso), `large-v3` (muy lento, máxima precisión). También configurable: `stt_beam_size` (1 = greedy, el más rápido), `stt_temperature` (0 = determinista) y `stt_initial_prompt`. Benchmark en esta PC (7.6s de audio): small ~2.6s vs turbo ~14.5s (sin VAD).
- El wake word con Picovoice ya NO es gratis (discontinuó junio 2026). Usar Ctrl+Alt+Shift+J (una consulta) / Ctrl+Shift+J (llamada) por ahora.
- **Doble palmada**: `services/clap_detector.py` detecta dos transients (pico >= `voice.clap_threshold`, por defecto 0.65 del máximo int16) dentro de `voice.clap_double_window_min..max` (0.12-0.9 s). Al detectarlas, JARVIS saluda (`voice.clap_greeting`) y entra en modo una consulta. Solo está activo en reposo (se pausa al grabar/procesar/hablar). Configurable: `voice.clap_enabled` (default true), `clap_cooldown` (2.5 s). Las palmadas deben ser fuertes y nítidas para no dispararse con la voz o la música.
- La API key de Gemini formato `AQ.Ab...` es el formato nuevo y correcto de Google.
- El archivo `credentials.json` de Google Calendar ya está configurado.
- ChromaDB es opcional - se puede habilitar después con `--enable-memory`.
- El usuario planea agregar wake word por palmadas en el futuro.
- Modo voz 100%: `voice.auto_start=true` iniciaría la conversación continua (modo llamada) al arrancar; **por defecto está apagado** (`false`): JARVIS arranca en reposo (`idle`) todo el tiempo y atiende solo UNA consulta con `Ctrl+Alt+Shift+J` o el botón de la bandeja. La GUI es solo indicador visual y en `--background` la ventana se oculta a la bandeja del sistema (`gui.tray`). Hotkey `Ctrl+Shift+J` pausa/reanuda una llamada. El usuario puede INTERRUMPIR a JARVIS mientras habla con "para", "espera", "silencio", "cállate", "basta", etc. y rectificar su consulta en el mismo audio (`voice.interrupt_enabled`, `interrupt_threshold` alto para no oirse a si mismo, `interrupt_max_wait`).
- Telegram: mismo cerebro y memoria que la voz (cada canal su conversación). Confirmaciones de acciones peligrosas con botones inline; `services/telegram_bot.py` corre el bot en un hilo propio.

## Visión de pantalla + control de teclado/ratón (implementado)

- **Visión**: `tools/screen_tools.py` captura con `PIL.ImageGrab.grab(all_screens=True)`, redimensiona a `input.max_image_width` (1280 px) y guarda un JPEG en `logs/screenshots/`. El `function_response` de una tool solo transporta JSON, así que `brain/gemini.py` tiene que **adjuntar la imagen aparte** como `types.Part.from_bytes(data=..., mime_type="image/jpeg")`, justo después del `function_response` de `take_screenshot` (si se separan, Gemini no las asocia). Verificado: `gemini-3.5-flash-lite` **sí es multimodal** (lee capturas y describe lo que ve).
- **Artefactos**: `GeminiBrain.artifacts` guarda las capturas del turno (`{"type":"image","path":...}`) y se limpia en cada `chat_message`. Telegram las envía como **foto** al chat (`_reply_with_images` → `send_photo`); el pie de foto lleva la descripción del modelo, truncada a 1024 chars (límite de Telegram).
- **Teclado/ratón**: `tools/input_tools.py` con pyautogui. `pyautogui.FAILSAFE` queda **activo**: si el puntero llega a la esquina (0,0) la acción se aborta. `type_text` con acentos/ñ/emoji va por portapapeles + `ctrl+v` (y restaura el portapapeles original) porque `pyautogui.write` no soporta Unicode. `type_text` **nunca** pulsa Enter, así que no puede ejecutar comandos por su cuenta.
- **Foco**: Windows no deja que una app en background robe el foco. `tools/window_tools.py` usa `pygetwindow` (ctypes puro, no necesita pywin32) y el truco de simular ALT (`keybd_event`) para forzar `SetForegroundWindow`. Todas las tools de input aceptan `window="titulo"` para enfocar el destino antes de actuar.
- **Nivel de riesgo**: las tools de pantalla/teclado/ratón/ventanas son `safe` o `moderate` → en este proyecto **se ejecutan sin confirmación** (decisión del usuario). Para volver a pedir confirmación por voz basta con cambiar su entrada en `RISK_LEVELS` a `dangerous` en `brain/tools_executor.py`.
- **Log y emoji**: los títulos de ventana traen emoji y la consola de Windows es cp1252 → `utils/logger.py` hace `stream.reconfigure(errors="replace")` para que loguear un título no reviente el StreamHandler.
- Dependencias nuevas en `requirements.txt`: `pyautogui>=0.9.54` y `pyperclip>=1.8.2` (ya estaban instaladas en el venv, faltaban en el archivo).
- **Limpieza de capturas**: `_prune_old()` en `tools/screen_tools.py` deja solo las **50 capturas más recientes** en `logs/screenshots/` (borra las viejas) para que el disco no se llene. Se ejecuta en cada `take_screenshot`.
- **Verificado en producción**: `_send_photo()` devuelve el `Message` de Telegram (o `None` si falla) para poder comprobar la entrega; `msg.photo` es una **tupla** de `PhotoSize` (la mayor es `msg.photo[-1]`), no un objeto suelto.
- Marcadores de Chrome: en esta versión de Chrome NO existe el archivo clásico `User Data\Default\Bookmarks`; los marcadores por cuenta están en `User Data\<perfil>\AccountBookmarks` (mismo JSON: `roots.bookmark_bar`). `tools/bookmark_tools.py` lee `AccountBookmarks` y cae a `Bookmarks` por compatibilidad. Perfil: `browser.chrome_profile` en config.json (`auto` = el perfil con más marcadores; esta PC usa `Default`). Los marcadores sin título se muestran como `sin titulo (dominio)` para que el usuario pueda pedirirlos ("abre spotify"). OJO: hay carpetas literalmente nombradas `,` y `.` en la barra del usuario.
- Cuando JARVIS responde literalmente "OK": eso NO es cuota agotada (eso es `"Se agotó la cuota de Gemini..."`). Es una respuesta SIN TEXTO de Gemini (truncada por `llm.max_output_tokens`, filtrada, o generación degenerada). `brain/gemini.py` ahora loguea `finish_reason` + `usage_metadata` (` thoughts/candidates/total`), reintenta UNA vez con el doble de presupuesto si fue `MAX_TOKENS`, y devuelve un mensaje con el motivo real. OJO: `max_output_tokens: 200` era demasiado bajo (200). Subido a 1024.
- `llm.thinking_budget` es opcional (0 = sin razonamiento) pero **NO existe para `gemini-3.5-flash-lite`**: mandarlo da `400 INVALID_ARGUMENT` ("Request contains an invalid argument") en CADA request. Verificado: `gemini-3.1-flash-lite` sí lo acepta, `gemini-3.5-flash-lite` no. Por eso no está en `config.json`. Si lo activas y ves 400, el Cerebro cae solo al modelo de respaldo por `_try_fallback`.
- El fallback de modelo (`_try_fallback`) reintenta el mensaje REAL del usuario en el modelo de respaldo; antes mandaba un ping "Responde solo: OK" y devolvía ese "OK" como si fuera la respuesta (el usuario veía OK y perdía su respuesta, y el turno falso quedaba en el historial).
- Wake-on-LAN: herramienta JARVIS `wake_on_lan` (MAC de la laptop: `B0:6E:BF:11:1A:4C` en `config.json` -> `wol.mac`; broadcast `wol.broadcast`). NO puede encender la propia PC desde fuera: el paquete mágico debe salir de un dispositivo de la MISMA red local mientras la PC está apagada. `wake_listener.py` es un compañero standalone que escucha un bot de Telegram (usa `TELEGRAM_BOT_TOKEN` o mejor `TELEGRAM_WOL_BOT_TOKEN`/`WOL_MAC`/`WOL_BROADCAST` en `.env`) y envía el paquete WOL; corre en un dispositivo siempre-encendido de la LAN (celular Termux, Raspberry, otro PC). `enable_wol.ps1` activa WOL en Windows (admin; backup en `wol_backup/`; reversible con `-Undo`; `-Status` para ver estado) y desactiva Fast Startup. Setup del celular en `TERMUX_SETUP.md`. LIMITACION CONFIRMADA: en esta laptop el WOL despierta desde SUSPENSION pero NO desde apagado real (S5); por eso `power.shutdown_mode: "sleep"` en config.json hace que JARVIS "apague" = suspenda (apagado real solo con `mode='off'`). Para encender la laptop desde el celular con datos móviles hace falta un dispositivo en casa: router con WOL remoto, o smart-plug + BIOS "Restore on AC power loss".

## Programación con OpenCode (implementado)

JARVIS no programa por su cuenta: **delega en OpenCode**, que expone un servidor HTTP local (`opencode serve`) con un agente que de verdad edita archivos, ejecuta comandos y maneja MCP.

- **Módulo**: `tools/opencode_tools.py` (`OpenCodeClient`). Usa `urllib` de la stdlib: **no hay dependencias nuevas**.
- **Flujo**: `POST /api/session` (con `location.directory`, `model` y `permissions`) → `POST /api/session/{id}/prompt` → `POST /api/experimental/session/{id}/wait` (bloquea hasta que el agente queda idle) → `GET /api/session/{id}/message`. Los mensajes llegan **del más nuevo al más viejo**: `get_messages()` los ordena por `time.created`, y el resultado final es el último `assistant` con `finish` en `stop|length|content-filter|error`.
- **Autenticación**: HTTP **Basic**, usuario `opencode` + password. Prioridad: `config.json -> opencode.password` → `OPENCODE_SERVER_PASSWORD` del entorno → `logs/.opencode_password` (se genera y se guarda la primera vez). JARVIS pasa ese password al servidor que arranca él mismo con la misma variable de entorno (por eso `opencode serve` ya no imprime el password).
- **Auto-arranque**: si nadie escucha en `opencode.port` (4096) y `opencode.auto_start` es true, JARVIS lanza `opencode serve --port 4096 --hostname 127.0.0.1` con `CREATE_NO_WINDOW` (nada de ventanas negras bajo `pythonw`) y logs en `logs/opencode_server.log`. Si el puerto lo ocupa un servidor con OTRO password, el error lo dice explícitamente en vez de hacer timeout.
- **Permisos**: la sesión se crea con `permissions: [{action:"*", resource:"*", effect:"allow"}]` para que el agente no se quede esperando aprobación en cada archivo (el usuario pidió que trabaje solo). `opencode.permissions: "ask"` quita ese ruleset y deja que OpenCode consulte.
- **Modelo**: `opencode.model` = `proveedor/modelo` (`opencode/big-pickle` por defecto). Se corta por el **primer** `/` para que funcionen ids anidados (`openrouter/anthropic/claude-sonnet-5`). OJO: el modelo por defecto del `serve` de esta PC era `openai/gpt-6.1-terra` por OpenRouter y devolvía `provider.auth: API key expired` — de ahí que el modelo sea explícito.
- **Tools nuevas** (49 en total): `opencode_code(task, directory, background)`, `opencode_result(session_id, wait_seconds)`, `opencode_sessions(limit)` y `opencode_mcp(action, server, url, command)`. Riesgos: `opencode_code` y `opencode_mcp` son `moderate` (auto en este proyecto), las de lectura `safe`. Para que pida confirmación por voz, subirlas a `dangerous`.
- **Tareas largas**: `opencode_code` bloquea hasta `opencode.wait_timeout` (240 s). Si se agota devuelve `status: "running"` + `session_id` y Gemini sigue con `opencode_result`; con `background=true` vuelve al instante. Mientras corre, JARVIS está en estado `processing` (no hay interrupción por voz en ese estado).
- **MCP**: `opencode_mcp` usa `GET /api/mcp` y `/api/experimental/mcp/{server}` (PUT/DELETE, `connect`/`disconnect`). Acepta `directory` y lo manda como `location[directory]` (deepObject), porque los MCP se resuelven por *location*: listar sin `directory` muestra los del cwd del `serve`, que es la carpeta del proyecto JARVIS.
- **Carpeta de trabajo**: `opencode.directory` (vacío = carpeta del proyecto). Si la carpeta pedida no existe, se crea (y el resultado lo reporta en `created_directory`).
- **SQLite / memoria**: no toca nada; el resultado vuelve como texto y JARVIS lo resume en 1-2 frases (regla del `SYSTEM_PROMPT`).
- **Cierre**: `stop_server()` solo mata el proceso si `opencode.shutdown_on_exit=true`. Por defecto queda vivo: el próximo JARVIS lo reutiliza sin pagar el arranque (~5 s) y el password está en `logs/.opencode_password`.
- **GitHub**: se usa el **MCP `github`** que ya está configurado en OpenCode (autenticado con la cuenta del usuario). En `task` hay que pedirle explícitamente "usa el servidor MCP 'github'" (herramientas `create_repository`, `create_or_update_file`, `create_pull_request`...), NO `gh` ni comandos de terminal. Regla en el `SYSTEM_PROMPT`: si el usuario no dice público/privado, el repo se crea **privado**. Verificado E2E: "crea un repositorio privado jarvis-e2e-mcp" → repo creado en 18 s. OJO: `gh` (GitHub CLI) **no está instalado** y el MSI de winget pide UAC (falla con código 1602 si se cancela); no hace falta para nada de esto. Los repos **locales** (`git init` + commit) siguen funcionando sin nada extra.
- **Verificado**: proyecto multi-archivo y repo git local creados por OpenCode en 9-30 s; foto/archivos y `files_changed` devueltos correctamente; `opencode_mcp list` ve context7, github, playwright, supabase y testsprite.

## Ejecución y Autoarranque

- **NO usamos ejecutable compilado (PyInstaller) todavía**: cada cambio de código se aplica reiniciando el proceso; compilarlo obligaría a re-empaquetar en cada mejora. Se puede hacer más adelante cuando las features se estabilicen.
- Lanzadores (en la raíz del proyecto):
  - `Iniciar JARVIS.vbs` — arranca JARVIS en segundo plano con `venv\Scripts\pythonw.exe main.py --background` (sin ventana de consola; la GUI se oculta a la bandeja del sistema a los ~2.5s).
  - `Reiniciar JARVIS.vbs` — mata la instancia que corre `main.py` y la vuelve a lanzar. Útil tras cambiar código (no hay nada que recompilar).
  - OJO: ambos VBS tenían la ruta de la carpeta VIEJA (`...Proyectos Ing Sistemas\Personales\Jarvis`) y fallaban al lanzarse. Ya corregidos a `...Proyectos-Ingenieria-Sistemas\Personales\jarvis`. Si cambias de carpeta, edita `sh.CurrentDirectory` en los dos VBS.
- Autoarranque con Windows: acceso directo `JARVIS.lnk` en `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup` → apunta a `pythonw.exe main.py --background` con WorkDir = proyecto.
- `main.py --background` oculta la ventana a la bandeja del sistema (icono JARVIS con menú Iniciar escucha / Abrir ventana / Salir; `gui.tray` en config.json). Cerrar la ventana (X) en modo background solo la oculta; se sale con "Salir" de la bandeja. Logs en `logs/jarvis.log` (bajo pythonw `/dev/null` no hay consola, solo archivo).
- Circunstancias: `pythonw` no tiene `sys.stderr`, por eso `utils/logger.py` solo crea `StreamHandler` si `sys.stderr` no es None.

```bash
# Activar entorno virtual
venv\Scripts\activate

# Ejecutar JARVIS (con consola, para ver logs en vivo)
python main.py

# Ejecutar JARVIS en segundo plano (sin consola, GUI minimizada)
venv\Scripts\pythonw.exe main.py --background

# Instalar dependencias
pip install -r requirements.txt
```
