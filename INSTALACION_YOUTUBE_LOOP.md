# Instalación: YouTube Loop (Extensión de Chrome + Servidor Flask)

Esta característica permite poner videos de YouTube en bucle desde JARVIS usando
una extensión de Chrome (Manifest v3) que ejecuta
`document.querySelector('video').loop = true;` directamente en la pestaña de
YouTube. Así se usa tu navegador personal con tu sesión de Google ya iniciada,
sin depender de pyautogui ni del foco de ventana.

## 1. Instalar dependencias de Python

```bash
pip install -r requirements.txt
```

Esto instala **Flask** (servidor que recibe los comandos de JARVIS).

## 2. Instalar la extensión de Chrome

1. Abre Chrome y ve a `chrome://extensions/`
2. Activa el **Modo de desarrollador** (interruptor arriba a la derecha)
3. Haz clic en **Cargar desempaquetada**
4. Selecciona la carpeta `chrome_extension/` de este proyecto
   (ruta completa: `...\jarvis\chrome_extension`)

La extensión aparecerá como "JARVIS YouTube Loop".

## 3. Iniciar el servidor Flask

Desde la raíz del proyecto:

```bash
python services/youtube_loop_server.py
```

El servidor escuchará en `http://127.0.0.1:5050`.

Puedes dejarlo corriendo en una terminal aparte, o configurarlo para que se
inicie automáticamente con JARVIS.

## 4. Usarlo con JARVIS

Reinicia JARVIS y prueba:

- **"pon el video en bucle"** → activa el bucle en el video de YouTube que
  ya esté abierto en una pestaña.
- **"pon X video en bucle"** → busca el video "X" en YouTube, lo abre y
  activa el bucle.

## Solución de problemas

| Problema | Solución |
|----------|----------|
| "No pude contactar con el servidor Flask" | Inicia `python services/youtube_loop_server.py` |
| "No hay pestaña de YouTube abierta" | Abre YouTube en Chrome antes de pedir el bucle |
| La extensión no aparece | Verifica que cargaste la carpeta correcta en `chrome://extensions/` |
| El bucle no se activa | Asegúrate de que el servidor Flask esté corriendo y la extensión instalada |

## Estructura de archivos

```
jarvis/
├── services/
│   └── youtube_loop_server.py   # Servidor Flask (endpoint /loop y /status)
├── chrome_extension/
│   ├── manifest.json            # Manifest v3 de la extensión
│   └── background.js            # Service worker (polling + executeScript)
├── requirements.txt             # Incluye flask>=3.0.0
└── INSTALACION_YOUTUBE_LOOP.md  # Este archivo
```
