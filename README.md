# JARVIS - Asistente de Voz Personal

JARVIS es un asistente de voz personal en Python, inspirado en el JARVIS de Iron Man. Hablas en español y él ejecuta tareas reales en tu PC: abrir aplicaciones, buscar en internet, gestionar emails y calendario, recordar información, capturar la pantalla, controlar teclado/ratón, programar delegando en OpenCode, e incluso atenderte por Telegram. Incluye GUI completa con CustomTkinter.

## Stack tecnológico

| Componente | Librería | Estado |
|---|---|---|
| Lenguaje | Python 3.14 | ✅ |
| IA / Cerebro | Google Gemini API (Flash) | ✅ |
| Speech-to-Text | faster-whisper (small/turbo/medium/large-v3) | ✅ |
| Text-to-Speech | edge-tts (neural, español) | ✅ |
| Activación | Ctrl+Alt+Shift+J (una consulta) + ESPACIO manteniendo (push-to-talk en la GUI) + bandeja del sistema | ✅ |
| GUI | CustomTkinter | ✅ |
| Memoria | SQLite (persistente) + búsqueda semántica opcional (ChromaDB) | ✅ |
| Navegador | webbrowser + duckduckgo-search (sin Playwright) | ✅ |
| Email | yagmail (Gmail SMTP) | ✅ |
| Calendar | Google Calendar API (OAuth2) | ✅ |
| Automatización PC | psutil + subprocess | ✅ |
| Teclado/Ratón/Ventanas | pyautogui + pyperclip + pygetwindow | ✅ |
| Audio | sounddevice (captura) + pygame (reproducción) | ✅ |
| Chat (Telegram) | python-telegram-bot | ✅ |
| Programación | OpenCode (API HTTP local, `opencode serve`) | ✅ |

## Estructura del proyecto

```
Jarvis/
├── main.py                 # Entry point
├── config.py / config.json # Configuración
├── core/                   # Orquestador (JARVIS), eventos, confirmaciones por voz
├── services/               # Audio, STT, TTS, wake_word, telegram_bot
├── brain/                  # Gemini + definiciones/ejecución de tools
├── memory/                 # SQLite, contexto, búsqueda semántica
├── tools/                  # Tools del sistema, navegador, archivos, email, calendario,
│                           # input/ventanas/pantalla, OpenCode
├── gui/                    # App CustomTkinter, componentes, confirmaciones, bandeja
├── utils/                  # Logger
├── tests/                  # 265 tests (unittest)
├── wake_listener.py        # Companion WOL standalone (Termux/Raspberry)
├── enable_wol.ps1          # Activa Wake-on-LAN en Windows
└── AGENTS.md               # Contexto completo del proyecto
```

## Instalación

```bash
# 1. Crear entorno virtual
python -m venv venv
venv\Scripts\activate

# 2. Instalar dependencias
pip install -r requirements.txt

# 3. Configurar credenciales
cp .env.example .env
# Edita .env con tu GEMINI_API_KEY, GMAIL_USER, GMAIL_APP_PASSWORD, etc.

# 4. (Opcional) Google Calendar: coloca credentials.json en la raíz

# 5. Ejecutar
python main.py
```

## Ejecución

```bash
# Con consola (ver logs en vivo)
python main.py

# En segundo plano (GUI a la bandeja del sistema)
venv\Scripts\pythonw.exe main.py --background

# Solo bot de Telegram (sin GUI ni voz)
python main.py --telegram-only
```

Hotkeys:
- `Ctrl+Alt+Shift+J` → una consulta por voz
- `ESPACIO` (manteniendo en la GUI) → push-to-talk: hablar mientras se suelta

## Tools disponibles para Gemini

Gemini elige automáticamente qué herramienta usar, agrupadas por área:

- **Sistema**: info del sistema, abrir/cerrar apps, volumen, Wake-on-LAN, suspender/reiniciar PC
- **Navegador**: abrir URL, buscar en DuckDuckGo, reproducir video de YouTube, marcadores de Chrome
- **Archivos**: buscar, leer, escribir, eliminar
- **Email**: enviar (con confirmación), leer recientes
- **Calendario**: listar calendarios, ver próximos eventos (todos los calendarios), crear/modificar/eliminar eventos (incluidos repetidos)
- **Memoria**: notas, proyectos, preferencias, olvidar información
- **Pantalla/Teclado/Ratón/Ventanas**: captura de pantalla (Gemini la ve), teclas, clics, scroll, ventanas
- **Código**: ejecutar Python en sandbox; programar delegando en OpenCode (archivos, git, repos, comandos, dependencias, MCP)

## Programación con OpenCode

JARVIS no programa por su cuenta: delega en **OpenCode**, que expone un servidor HTTP local (`opencode serve`). Cuando le pides "crea un repositorio de prueba", JARVIS hace una petición HTTP a la API local de OpenCode, que crea el repo, escribe archivos y hace commit. Para GitHub usa el MCP `github` ya configurado (autenticado con tu cuenta).

## Seguridad

- Las API keys viven en `.env` (gitignored). Nunca se commitean.
- `credentials.json` y `token.json` (Google Calendar) también están gitignored.
- El sistema de permisos clasifica cada acción como `safe` / `moderate` / `dangerous`; las peligrosas (enviar email, apagar PC, ejecutar código) requieren confirmación.
- La base de datos y logs quedan fuera del repositorio.

## Tests

```bash
.\venv\Scripts\python.exe -m unittest discover -s tests -t .
# 265 tests
```

## Más información

Contexto completo del proyecto, decisiones de arquitectura y preferencias del usuario en [`AGENTS.md`](AGENTS.md).

## Licencia

Proyecto personal. Sin licencia definida por ahora.
