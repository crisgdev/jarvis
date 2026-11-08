# PROJECT_PLAN.md - Roadmap de Desarrollo de JARVIS

> **DOCUMENTO HISTORICO** (agosto 2026): este fue el plan ORIGINAL de construccion.
> El estado REAL del proyecto (features, arquitectura, cuenta de tools) esta en
> `AGENTS.md`. Algunas cosas de aqui ya no aplican (no se usa Playwright, el
> navegador es webbrowser + duckduckgo-search; wake word es por hotkeys; las
> claves reales SOLO van en `.env`).

## FASE 0: Setup Inicial (Primera sesion)

### 0.1 Crear entorno virtual e instalar dependencias
```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
```

### 0.2 Crear archivo `.env` con API keys
```
GEMINI_API_KEY=<tu_api_key_real_va_en_.env>
GMAIL_USER=<tu_email_real_va_en_.env>
GMAIL_APP_PASSWORD=<tu_app_password_real_va_en_.env>
```

### 0.3 Crear estructura de directorios
Crear todas las carpetas y archivos `__init__.py`.

### 0.4 Crear `config.py` y `config.json`
Carga de configuracion desde `.env` y `config.json`.

### 0.5 Verificar que Gemini funciona
Script de prueba que envia un mensaje a Gemini y muestra la respuesta.

---

## FASE 1: Cerebro - Integracion Gemini (Prioridad Alta)

### 1.1 `brain/tools_definitions.py`
Definir todas las tools como diccionarios JSON para la API de Gemini.

### 1.2 `brain/gemini.py`
- Inicializar cliente `google.genai` con la API key
- System prompt de JARVIS en espanol
- Manejo de historial de conversacion (ultimos 20 mensajes)
- Funcion `chat(user_text)` que:
  1. Envia texto + historial + tools a Gemini
  2. Si Gemini responde con texto -> retorna texto
  3. Si Gemini responde con function_call -> ejecuta la tool -> envia resultado -> retorna respuesta final
  4. Soporte para multiples function calls encadenados

### 1.3 `brain/tools_executor.py`
- Mapa de tools a sus funciones Python
- Sistema de permisos (safe/moderate/dangerous)
- Funcion `execute_tool(name, args)` con logging
- Request de confirmacion para acciones dangerous

### 1.4 Prueba del cerebro
Script de prueba: usuario escribe texto, Gemini responde y ejecuta tools.

---

## FASE 2: Tools del Sistema (Prioridad Alta)

### 2.1 `tools/permissions.py`
```python
RISK_LEVELS = {
    "get_system_info": "safe",
    "open_application": "moderate",
    "close_application": "moderate",
    "control_volume": "moderate",
    "shutdown_pc": "dangerous",
    "restart_pc": "dangerous",
    "browse_url": "safe",
    "search_web": "safe",
    "read_page_content": "safe",
    "search_file": "safe",
    "read_file": "safe",
    "send_email": "dangerous",
    "read_recent_emails": "safe",
    "get_upcoming_events": "safe",
    "create_calendar_event": "moderate",
    "delete_calendar_event": "dangerous",
    "save_note": "moderate",
    "recall_information": "safe",
    "create_project": "moderate",
    "add_project_note": "moderate",
    "get_project_info": "safe",
    "list_projects": "safe",
    "update_project_status": "moderate",
    "run_python_code": "dangerous",
}
```

### 2.2 `tools/system.py`
- `get_system_info(info_type)`: Hora, fecha, CPU, RAM, disco, bateria con psutil
- `open_application(app_name)`: Abrir apps con subprocess (chrome, spotify, vscode, notepad, explorer, calculator)
- `close_application(app_name)`: Cerrar apps con taskkill
- `control_volume(action, level)`: Controlar volumen con ctypes (Windows API)
- `shutdown_pc()`: `shutdown /s /t 60`
- `restart_pc()`: `shutdown /r /t 60`

### 2.3 `tools/file_tools.py`
- `search_file(filename)`: Buscar archivo con `os.walk`
- `read_file(filepath)`: Leer archivo con encoding UTF-8

### 2.4 `tools/browser_tools.py`
- `browse_url(url)`: Abrir URL con webbrowser.open
- `search_web(query)`: Buscar en Google, extraer resultados con requests + BeautifulSoup
- `read_page_content()`: Leer contenido de pagina actual

### 2.5 `tools/email_tools.py`
- `send_email(to, subject, body)`: Enviar con yagmail
- `read_recent_emails(count)`: Leer con IMAP (imaplib)

### 2.6 `tools/calendar_tools.py`
- `get_upcoming_events(days_ahead)`: Leer eventos con Google Calendar API
- `create_calendar_event(summary, start, end, ...)`: Crear evento
- `delete_calendar_event(event_id)`: Eliminar evento
- Primera ejecucion: OAuth flow para autorizar

### 2.7 `tools/code_executor.py`
- `run_python_code(code, description)`: Ejecutar en subprocess con timeout 30s, output limitado

### 2.8 `tools/executor.py`
- Dispatcher central que recibe (tool_name, args) y ejecuta la funcion correcta
- Logging de todas las ejecuciones
- Manejo de errores

---

## FASE 3: Memoria Persistente (Prioridad Alta)

### 3.1 `memory/database.py`
Tablas SQLite:
```sql
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    started_at TIMESTAMP,
    ended_at TIMESTAMP,
    summary TEXT
);

CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT REFERENCES sessions(id),
    role TEXT,  -- 'user', 'assistant', 'system'
    content TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE preferences (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE,
    description TEXT,
    status TEXT DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE project_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER REFERENCES projects(id),
    content TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

Funciones CRUD para cada tabla.

### 3.2 `memory/context.py`
- `build_context(session_id, max_turns=20)`: Construir historial para Gemini
- `save_conversation(session_id, role, content)`: Guardar mensaje
- `get_relevant_context(query)`: Buscar en memoria pasada para contexto

### 3.3 `memory/search.py` (Opcional)
- ChromaDB para busqueda semantica
- Se activa con flag `--enable-memory`
- `store_memory(text, source)`: Guardar chunk con embedding
- `search_memory(query, top_k=3)`: Buscar chunks relevantes

---

## FASE 4: Audio - STT y TTS (Prioridad Alta)

### 4.1 `services/audio.py`
- `start_recording()`: Iniciar captura con sounddevice
- `stop_recording() -> numpy.ndarray`: Detener y retornar audio
- `get_audio_level() -> float`: Nivel actual del microfono (para GUI)
- Configuracion: sample_rate=16000, channels=1

### 4.2 `services/stt.py`
- Cargar modelo faster-whisper (small)
- `transcribe(audio) -> str`: Transcribir audio a texto en espanol
- VAD (Voice Activity Detection) para detectar silencio

### 4.3 `services/tts.py`
- `speak(text)`: Convertir texto a audio con edge-tts y reproducir
- Voz: `es-HN-CarlosNeural` (o configurable)
- `stop_speech()`: Detener reproduccion actual
- Streaming: enviar fragmentos para reducir latencia

### 4.4 `services/wake_word.py` (Futuro)
- Placeholder para openWakeWord
- Por ahora: activacion por Ctrl+Alt+Shift+J con la libreria `keyboard`

---

## FASE 5: GUI con CustomTkinter (Prioridad Media)

### 5.1 `gui/app.py`
Ventana principal:
- Tema oscuro futurista
- Panel central: indicador de estado (Escuchando/Procesando/Hablando/Esperando)
- Historial de conversacion tipo chat (scrollable)
- Barra inferior: boton mic on/off, boton configuracion
- Indicador de nivel de audio (barra visual)
- Boton de emergencia para cancelar

### 5.2 `gui/components.py`
- `ChatBubble(role, text)`: Burbuja de chat (usuario a la derecha, JARVIS a la izquierda)
- `StatusIndicator(state)`: Indicador animado del estado
- `AudioLevelBar(level)`: Barra de nivel de audio
- `ControlBar()`: Barra con botones de control

### 5.3 `gui/confirmation.py`
- `ConfirmationDialog(title, message, on_confirm, on_cancel)`: Dialogo modal
- Nivel MODERATE: boton Confirmar/Cancelar
- Nivel DANGEROUS: dialogo + timeout + confirmacion por voz

---

## FASE 6: Orquestador Principal (Prioridad Alta)

### 6.1 `core/jarvis.py`
Clase `JARVIS` que coordina todo:
```
Estados: IDLE -> LISTENING -> PROCESSING -> SPEAKING -> IDLE
```

Flujo:
1. Esperar activacion (Ctrl+Alt+Shift+J)
2. Capturar audio del microfono
3. Transcribir con faster-whisper
4. Enviar a Gemini con tools
5. Ejecutar tools si las hay
6. Generar respuesta final
7. Convertir a voz con edge-tts
8. Reproducir audio
9. Guardar en memoria
10. Volver a IDLE

### 6.2 `core/events.py`
Sistema de eventos proactivos en background thread:
- Monitor de memoria (cada 60s)
- Monitor de disco (cada 60s)
- Monitor de bateria (cada 60s)
- Si evento detectado -> JARVIS habla proactivamente

---

## FASE 7: Entry Point y Configuracion (Prioridad Alta)

### 7.1 `main.py`
- Cargar configuracion
- Inicializar todos los servicios
- Mostrar GUI
- Iniciar loop de JARVIS
- Manejar cierre limpio

### 7.2 `config.py`
- Cargar `.env` con python-dotenv
- Cargar `config.json`
- Validar API keys
- Funcion `get_config()` que retorna diccionario de configuracion

### 7.3 `config.json`
```json
{
    "voice": {
        "language": "es",
        "tts_voice": "es-HN-CarlosNeural",
        "stt_model": "small",
        "activation_key": "ctrl+alt+shift+j",
        "once_key": "ctrl+alt+shift+j",
    },
    "llm": {
        "model": "gemini-1.5-flash",
        "max_history_turns": 20,
        "temperature": 0.7
    },
    "memory": {
        "enabled": true,
        "semantic_search": false,
        "db_path": "jarvis_memory.db"
    },
    "gui": {
        "theme": "dark",
        "window_title": "JARVIS - Asistente Personal",
        "window_size": [900, 700]
    },
    "audio": {
        "sample_rate": 16000,
        "max_record_seconds": 15,
        "silence_threshold": 500
    }
}
```

### 7.4 `utils/logger.py`
Configuracion de logging con archivos rotativos.

---

## FASE 8: Testing y Pulido (Prioridad Media)

### 8.1 Test manual de cada tool
Probar individualmente cada tool del sistema.

### 8.2 Test del pipeline completo
Hablar con JARVIS y verificar que:
- Transcribe correctamente
- Gemini elige la tool correcta
- La tool se ejecuta
- La respuesta se genera
- El audio se reproduce
- La memoria se guarda

### 8.3 Ajustes de latencia
- Optimizar modelo STT
- Streaming de TTS
- Respuestas mas cortas de Gemini

### 8.4 Manejo de errores
- que pasa si no hay internet
- que pasa si Gemini falla
- que pasa si el microfono no funciona
- que pasa si una tool falla

---

## FASE 9: Features Futuros (Low Priority)

### 9.1 Wake Word con openWakeWord
- Entrenar modelo "Hey JARVIS" o detectar palmadas
- Activacion por voz en lugar de teclado

### 9.2 Bussqueda semantica con ChromaDB
- Buscar en conversaciones pasadas por significado
- "Recuerda algo sobre Python que me ensenaste"

### 9.3 Notificaciones proactivas avanzadas
- Recordatorios programados
- Alertas de calendario
- Seguimiento de proyectos

### 9.4 Modo nocturno
- Solo escuchar cuando le hablan fuerte
- No hablar de vuelta (solo mostrar texto)

---

## Orden de Implementacion Recomendado

```
FASE 0 (Setup) -> FASE 1 (Gemini) -> FASE 2 (Tools) -> FASE 3 (Memoria)
    -> FASE 4 (Audio) -> FASE 6 (Orquestador) -> FASE 5 (GUI)
    -> FASE 7 (Main) -> FASE 8 (Testing) -> FASE 9 (Futuro)
```

**Justificacion**: Primero el cerebro (Gemini + tools), luego la memoria, luego audio, despues el orquestador que conecta todo, la GUI, y finalmente testing.
