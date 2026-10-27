from google.genai import types


def _schema(type_: types.Type, properties=None, required=None, description=None, enum=None):
    return types.Schema(
        type=type_,
        properties=properties or {},
        required=required or [],
        description=description,
        enum=enum,
    )


TOOLS = [
    # ── Sistema ──
    types.FunctionDeclaration(
        name="get_system_info",
        description="Obtiene informacion del sistema: hora, fecha, CPU, RAM, disco, bateria.",
        parameters=_schema(
            types.Type.OBJECT,
            properties={
                "info_type": _schema(
                    types.Type.STRING,
                    description="Tipo de info: 'all', 'time', 'date', 'cpu', 'memory', 'disk', 'battery'",
                    enum=["all", "time", "date", "cpu", "memory", "disk", "battery"],
                ),
            },
            required=["info_type"],
        ),
    ),
    types.FunctionDeclaration(
        name="open_application",
        description=(
            "Abre CUALQUIER aplicacion, juego o programa instalado en la PC, "
            "accesos directos del escritorio o menu inicio, carpetas (descargas, "
            "documentos, escritorio, etc.) o un sitio web conocido (google, youtube, "
            "github, gmail, netflix). Usa SIEMPRE esta herramienta cuando el usuario "
            "pida abrir algo, aunque no reconozcas el nombre (ejemplo: 'abre pokemon "
            "reloaded', 'abre geometry dash'): JARVIS lo busca en la PC. NUNCA uses "
            "search_file ni search_web para abrir aplicaciones."
        ),
        parameters=_schema(
            types.Type.OBJECT,
            properties={
                "app_name": _schema(
                    types.Type.STRING,
                    description="Nombre de la app o sitio web a abrir, ej: google, youtube, chrome, spotify",
                ),
            },
            required=["app_name"],
        ),
    ),
    types.FunctionDeclaration(
        name="close_application",
        description="Cierra una aplicacion que esta corriendo.",
        parameters=_schema(
            types.Type.OBJECT,
            properties={
                "app_name": _schema(
                    types.Type.STRING,
                    description="Nombre de la app a cerrar, o 'all' para cerrar todas",
                ),
            },
            required=["app_name"],
        ),
    ),
    types.FunctionDeclaration(
        name="control_volume",
        description="Controla el volumen del sistema.",
        parameters=_schema(
            types.Type.OBJECT,
            properties={
                "action": _schema(
                    types.Type.STRING,
                    description="Accion: 'up', 'down', 'mute', 'unmute', 'set'",
                    enum=["up", "down", "mute", "unmute", "set"],
                ),
                "level": _schema(
                    types.Type.INTEGER,
                    description="Nivel de volumen (0-100), solo necesario si action es 'set'",
                ),
            },
            required=["action"],
        ),
    ),
    types.FunctionDeclaration(
        name="wake_on_lan",
        description=(
            "Enciende por red (Wake-on-LAN) una PC apagada de la red local. "
            "Usa la MAC guardada en config.json (wol.mac) si el usuario no da una."
        ),
        parameters=_schema(
            types.Type.OBJECT,
            properties={
                "mac": _schema(
                    types.Type.STRING,
                    description="Direccion MAC de la PC a encender (opcional)",
                ),
            },
        ),
    ),
    types.FunctionDeclaration(
        name="shutdown_pc",
        description=(
            "Suspende o apaga la PC. Por defecto (mode omitido) la SUSPENDE, dejandola "
            "dormida para poder encenderla luego con wake-on-LAN desde el celular. "
            "Usa mode='off' SOLO cuando el usuario pida explicitamente 'apagado real', "
            "'apagar del todo' o 'quitar energia'. Accion peligrosa que requiere confirmacion."
        ),
        parameters=_schema(
            types.Type.OBJECT,
            properties={
                "mode": _schema(
                    types.Type.STRING,
                    description="'sleep' (default, suspende) o 'off' (apagado real)",
                    enum=["sleep", "off"],
                ),
            },
        ),
    ),
    types.FunctionDeclaration(
        name="restart_pc",
        description="Reinicia la PC. Accion peligrosa que requiere confirmacion.",
        parameters=_schema(types.Type.OBJECT, properties={}),
    ),

    # ── Navegador ──
    types.FunctionDeclaration(
        name="browse_url",
        description=(
            "Abre una pagina web en el navegador. Acepta una URL completa "
            "(https://...) o un nombre de sitio como 'google' o 'youtube.com'."
        ),
        parameters=_schema(
            types.Type.OBJECT,
            properties={
                "url": _schema(types.Type.STRING, description="URL o nombre de sitio a abrir"),
            },
            required=["url"],
        ),
    ),
    types.FunctionDeclaration(
        name="search_web",
        description="Busca informacion en Google y retorna los resultados.",
        parameters=_schema(
            types.Type.OBJECT,
            properties={
                "query": _schema(types.Type.STRING, description="Texto de la busqueda"),
            },
            required=["query"],
        ),
    ),
    types.FunctionDeclaration(
        name="play_youtube_video",
        description=(
            "Abre en el navegador un video de YouTube buscandolo por nombre. "
            "Usa SIEMPRE esta herramienta cuando el usuario pida ver, reproducir, "
            "poner o entrar a un video de YouTube (ej: 'pon X en youtube', "
            "'mira el video de Y'). No la uses para solo buscar informacion."
        ),
        parameters=_schema(
            types.Type.OBJECT,
            properties={
                "query": _schema(
                    types.Type.STRING,
                    description="Nombre del video a abrir (ej: 'lofi hip hop radio') o URL de YouTube",
                ),
            },
            required=["query"],
        ),
    ),

    types.FunctionDeclaration(
        name="list_bookmarks",
        description=(
            "Lista los marcadores (barra de marcadores) de Chrome del usuario: "
            "carpetas y paginas guardadas. Usala cuando pregunte que tiene en "
            "favoritos/guardado, o para ver el contenido de una carpeta antes de "
            "abrirla. Sin argumentos devuelve el nivel superior de la barra; con "
            "'folder' devuelve el contenido de esa carpeta."
        ),
        parameters=_schema(
            types.Type.OBJECT,
            properties={
                "folder": _schema(
                    types.Type.STRING,
                    description=(
                        "Carpeta de marcadores a listar. Usa la ruta con '/' para "
                        "subcarpetas (ej: 'pkmn', 'pkmn/relo'). Vacio = barra de marcadores."
                    ),
                ),
            },
        ),
    ),
    types.FunctionDeclaration(
        name="open_bookmark",
        description=(
            "Abre una pagina guardada en los marcadores de Chrome por su nombre, o "
            "abre TODAS las paginas de una carpeta de marcadores. Usala SIEMPRE "
            "cuando el usuario pida entrar a un favorito, marcador, o a una carpeta "
            "de la barra de marcadores (ej: 'abre mi carpeta pkmn', 'entra a "
            "excalidraw', 'abre los marcadores de ingles'). No reemplaza a "
            "browse_url para URLs sueltas."
        ),
        parameters=_schema(
            types.Type.OBJECT,
            properties={
                "name": _schema(
                    types.Type.STRING,
                    description=(
                        "Nombre de la pagina o carpeta guardada (ej: 'excalidraw', "
                        "'presentaciones IA', 'pkmn/relo'). No hace falta la URL."
                    ),
                ),
                "max_tabs": _schema(
                    types.Type.INTEGER,
                    description="Maximo de paginas a abrir cuando es una carpeta (default 8)",
                ),
            },
            required=["name"],
        ),
    ),

    # ── Archivos ──
    types.FunctionDeclaration(
        name="search_file",
        description="Busca un archivo por nombre en la PC.",
        parameters=_schema(
            types.Type.OBJECT,
            properties={
                "filename": _schema(types.Type.STRING, description="Nombre del archivo a buscar"),
            },
            required=["filename"],
        ),
    ),
    types.FunctionDeclaration(
        name="read_file",
        description="Lee el contenido de un archivo de texto.",
        parameters=_schema(
            types.Type.OBJECT,
            properties={
                "filepath": _schema(types.Type.STRING, description="Ruta completa del archivo"),
            },
            required=["filepath"],
        ),
    ),
    types.FunctionDeclaration(
        name="write_file",
        description="Crea o escribe contenido en un archivo. Puede sobrescribir o agregar al final.",
        parameters=_schema(
            types.Type.OBJECT,
            properties={
                "filepath": _schema(types.Type.STRING, description="Ruta completa del archivo a escribir"),
                "content": _schema(types.Type.STRING, description="Contenido a escribir en el archivo"),
                "mode": _schema(
                    types.Type.STRING,
                    description="Modo: 'write' sobrescribe, 'append' agrega al final",
                    enum=["write", "append"],
                ),
            },
            required=["filepath", "content"],
        ),
    ),
    types.FunctionDeclaration(
        name="delete_file",
        description="Elimina un archivo. No elimina carpetas por seguridad.",
        parameters=_schema(
            types.Type.OBJECT,
            properties={
                "filepath": _schema(types.Type.STRING, description="Ruta completa del archivo a eliminar"),
            },
            required=["filepath"],
        ),
    ),

    # ── Email ──
    types.FunctionDeclaration(
        name="send_email",
        description="Envia un email Gmail. Accion peligrosa que requiere confirmacion.",
        parameters=_schema(
            types.Type.OBJECT,
            properties={
                "to": _schema(types.Type.STRING, description="Direccion de email destino"),
                "subject": _schema(types.Type.STRING, description="Asunto del email"),
                "body": _schema(types.Type.STRING, description="Cuerpo del email"),
            },
            required=["to", "subject", "body"],
        ),
    ),
    types.FunctionDeclaration(
        name="read_recent_emails",
        description="Lee los ultimos emails recibidos.",
        parameters=_schema(
            types.Type.OBJECT,
            properties={
                "count": _schema(
                    types.Type.INTEGER,
                    description="Numero de emails a leer (default 5)",
                ),
            },
        ),
    ),

    # ── Calendario ──
    types.FunctionDeclaration(
        name="get_upcoming_events",
        description=(
            "Obtiene los proximos eventos del calendario del usuario. Busca en "
            "TODOS los calendarios de la cuenta (el principal y los separados "
            "como 'u', 'c', 'mi chamba', etc.) y cada evento indica en cual "
            "esta con 'calendar'. Devuelve 'event_id' (ID real de Google), "
            "titulo, inicio y fin. Cada evento repetido incluye 'recurrence' "
            "(la RRULE) y 'recurrence_text' en espanol (ej. 'se repite semanal "
            "los lunes y jueves, y finaliza el 16 de octubre de 2026'). "
            "Si el usuario pregunta COMO se repite un evento (que dias, cada "
            "cuanto, hasta cuando o cuantas veces), lee 'recurrence_text'. "
            "Usa 'event_id' para eliminar eventos. "
            "Antes de borrar, usa esta herramienta para conseguir los ids reales. "
            "NO hay limite de cercania: si el usuario nombra un dia o fecha "
            "concreta (ej: 'lunes 28', 'el 7 de octubre', 'la semana del 2 de "
            "noviembre'), pasa 'start_date' (y 'end_date' si pide un rango o "
            "varios dias) con la fecha exacta YYYY-MM-DD. Usa 'days_ahead' solo "
            "para periodos generales como 'esta semana' o 'los proximos dias'."
        ),
        parameters=_schema(
            types.Type.OBJECT,
            properties={
                "days_ahead": _schema(
                    types.Type.INTEGER,
                    description="Dias hacia adelante (default 30). Preferible usar start_date/end_date para fechas concretas.",
                ),
                "start_date": _schema(
                    types.Type.STRING,
                    description="Fecha exacta de inicio en formato YYYY-MM-DD (ej: '2026-09-28'). Usala cuando el usuario nombre un dia/fecha concreto.",
                ),
                "end_date": _schema(
                    types.Type.STRING,
                    description="Fecha exacta de fin en formato YYYY-MM-DD (inclusive). Opcional; agregala si el usuario pide un rango o varios dias.",
                ),
            },
        ),
    ),
    types.FunctionDeclaration(
        name="list_calendars",
        description=(
            "Lista los calendarios del usuario (nombre e id) para saber donde "
            "puede guardarse un evento. Usala cuando el usuario quiera crear un "
            "evento y no te indique el calendario, para ofrecerle opciones."
        ),
        parameters=_schema(types.Type.OBJECT, properties={}),
    ),
    types.FunctionDeclaration(
        name="create_calendar_event",
        description=(
            "Crea un evento en el calendario. Pasale las fechas en la zona "
            "horaria local del usuario (configurada como America/Lima). Si el "
            "usuario dice 'a las 6', usa 18:00 como inicio. Si el usuario "
            "indica un calendario (ej: 'guardalo en mi calendario de la uni', "
            "'en mi chamba'), pasalo en 'calendar'. "
            "Para eventos REPETIDOS usa 'recurrence' con la RRULE sin el "
            "UNTIL (ej: todos los martes -> 'RRULE:FREQ=WEEKLY;BYDAY=TU', "
            "todos los dias -> 'RRULE:FREQ=DAILY', cada mes -> "
            "'RRULE:FREQ=MONTHLY') y 'recurrence_until' con la fecha final "
            "(ej: '2026-10-15'). Si no hay repeticion, dejales vacio/omitilos."
        ),
        parameters=_schema(
            types.Type.OBJECT,
            properties={
                "summary": _schema(types.Type.STRING, description="Titulo del evento"),
                "start_datetime": _schema(
                    types.Type.STRING,
                    description="Fecha/hora inicio formato ISO: 2026-08-25T10:00:00",
                ),
                "end_datetime": _schema(
                    types.Type.STRING,
                    description="Fecha/hora fin formato ISO: 2026-08-25T11:00:00",
                ),
                "timezone": _schema(
                    types.Type.STRING,
                    description="Zona horaria opcional, ej: America/Lima (default: configurada)",
                ),
                "description": _schema(types.Type.STRING, description="Descripcion opcional del evento"),
                "calendar": _schema(
                    types.Type.STRING,
                    description="Calendario donde crear: nombre o id (ej: 'mi chamba', 'u', 'repaso cursos UC'). Opcional; si no se indica usa el principal.",
                ),
                "recurrence": _schema(
                    types.Type.STRING,
                    description="Regla de repeticion RRULE SIN 'UNTIL' (ej: 'RRULE:FREQ=WEEKLY;BYDAY=TU'). Vacio si no se repite.",
                ),
                "recurrence_until": _schema(
                    types.Type.STRING,
                    description="Fecha final de la repeticion en ISO '2026-10-15'. Opcional.",
                ),
            },
            required=["summary", "start_datetime", "end_datetime"],
        ),
    ),
    types.FunctionDeclaration(
        name="update_calendar_event",
        description=(
            "Modifica un evento EXISTENTE del calendario. Usa SIEMPRE el "
            "'event_id' real que devuelve get_upcoming_events. Puede cambiar: "
            "'summary' (titulo), 'start_datetime'/'end_datetime' (dia y hora, "
            "juntos para duracion), 'calendar' (mover a otro calendario: nombre "
            "o id), y la repeticion con 'recurrence'/'recurrence_until' (pasa "
            "recurrence vacio para QUITAR la repeticion). Solo envia lo que se "
            "quiere modificar; lo demas se conserva."
        ),
        parameters=_schema(
            types.Type.OBJECT,
            properties={
                "event_id": _schema(
                    types.Type.STRING,
                    description="ID real del evento (de get_upcoming_events). Obligatorio.",
                ),
                "summary": _schema(types.Type.STRING, description="Nuevo titulo (opcional)"),
                "start_datetime": _schema(
                    types.Type.STRING,
                    description="Nueva fecha/hora inicio ISO (opcional)",
                ),
                "end_datetime": _schema(
                    types.Type.STRING,
                    description="Nueva fecha/hora fin ISO (opcional)",
                ),
                "timezone": _schema(
                    types.Type.STRING,
                    description="Zona horaria opcional, ej: America/Lima",
                ),
                "description": _schema(types.Type.STRING, description="Nueva descripcion (opcional)"),
                "calendar": _schema(
                    types.Type.STRING,
                    description="Calendario destino para mover el evento: nombre o id (opcional)",
                ),
                "recurrence": _schema(
                    types.Type.STRING,
                    description="Nueva RRULE de repeticion (opcional; vacio para quitar repeticion)",
                ),
                "recurrence_until": _schema(
                    types.Type.STRING,
                    description="Nueva fecha fin de repeticion ISO (opcional)",
                ),
            },
            required=["event_id"],
        ),
    ),
    types.FunctionDeclaration(
        name="delete_calendar_event",
        description=(
            "Elimina un evento del calendario. Usa SIEMPRE el 'event_id' "
            "real devuelto por get_upcoming_events. Busca en todos los "
            "calendarios de la cuenta. Accion peligrosa."
        ),
        parameters=_schema(
            types.Type.OBJECT,
            properties={
                "event_id": _schema(types.Type.STRING, description="ID real del evento (de get_upcoming_events)"),
                "summary": _schema(types.Type.STRING, description="Titulo del evento como respaldo opcional"),
            },
            required=["event_id"],
        ),
    ),

    # ── Memoria ──
    types.FunctionDeclaration(
        name="save_note",
        description="Guarda una nota importante en la memoria de JARVIS.",
        parameters=_schema(
            types.Type.OBJECT,
            properties={
                "content": _schema(types.Type.STRING, description="Contenido de la nota"),
                "category": _schema(
                    types.Type.STRING,
                    description="Categoria: 'general', 'idea', 'task', 'reminder'",
                    enum=["general", "idea", "task", "reminder"],
                ),
            },
            required=["content"],
        ),
    ),
    types.FunctionDeclaration(
        name="recall_information",
        description="Busca en la memoria pasada de JARVIS.",
        parameters=_schema(
            types.Type.OBJECT,
            properties={
                "query": _schema(types.Type.STRING, description="Texto a buscar en la memoria"),
            },
            required=["query"],
        ),
    ),
    types.FunctionDeclaration(
        name="forget_information",
        description=(
            "Borra de la memoria persistente (SQLite) las notas que mencionen "
            "'keywords'. Usala cuando el usuario diga que olvide/elimine/borre "
            "algo que le hayas guardado (edad, datos, notas). En 'keywords' "
            "pasale TANTO el concepto como las palabras que queden en la nota "
            "(ej: 'edad', 'anios'/'años', '19'). Devuelve lo eliminado."
        ),
        parameters=_schema(
            types.Type.OBJECT,
            properties={
                "keywords": _schema(
                    types.Type.STRING,
                    description="Palabras del tema a olvidar, ej: 'edad anios 19'",
                ),
            },
            required=["keywords"],
        ),
    ),
    types.FunctionDeclaration(
        name="create_project",
        description="Crea un nuevo proyecto en la memoria.",
        parameters=_schema(
            types.Type.OBJECT,
            properties={
                "name": _schema(types.Type.STRING, description="Nombre del proyecto"),
                "description": _schema(types.Type.STRING, description="Descripcion del proyecto"),
            },
            required=["name"],
        ),
    ),
    types.FunctionDeclaration(
        name="add_project_note",
        description="Agrega una nota a un proyecto existente.",
        parameters=_schema(
            types.Type.OBJECT,
            properties={
                "project_name": _schema(types.Type.STRING, description="Nombre del proyecto"),
                "content": _schema(types.Type.STRING, description="Contenido de la nota"),
            },
            required=["project_name", "content"],
        ),
    ),
    types.FunctionDeclaration(
        name="get_project_info",
        description="Obtiene informacion y notas de un proyecto.",
        parameters=_schema(
            types.Type.OBJECT,
            properties={
                "project_name": _schema(types.Type.STRING, description="Nombre del proyecto"),
            },
            required=["project_name"],
        ),
    ),
    types.FunctionDeclaration(
        name="list_projects",
        description="Lista todos los proyectos activos.",
        parameters=_schema(types.Type.OBJECT, properties={}),
    ),
    types.FunctionDeclaration(
        name="update_project_status",
        description="Cambia el estado de un proyecto.",
        parameters=_schema(
            types.Type.OBJECT,
            properties={
                "project_name": _schema(types.Type.STRING, description="Nombre del proyecto"),
                "status": _schema(
                    types.Type.STRING,
                    description="Nuevo estado: 'active', 'paused', 'completed', 'archived'",
                    enum=["active", "paused", "completed", "archived"],
                ),
            },
            required=["project_name", "status"],
        ),
    ),

    # ── Pantalla, teclado, raton y ventanas ──
    types.FunctionDeclaration(
        name="take_screenshot",
        description=(
            "Captura la pantalla de la PC y TU la recibes como imagen real, "
            "para que puedas VER lo que hay en pantalla y describirlo "
            "(titulos, textos, botones, errores). Usala cuando el usuario "
            "pregunte 'que hay en mi pantalla', 'que ves', 'lee mi pantalla', "
            "'que dice este error' o quiera actuar sobre lo que ve. "
            "Opcionalmente 'region' recorta a 'x,y,w,h'."
        ),
        parameters=_schema(
            types.Type.OBJECT,
            properties={
                "region": _schema(
                    types.Type.STRING,
                    description="Region a capturar 'x,y,w,h' o 'full' (default: toda la pantalla)",
                ),
                "max_width": _schema(
                    types.Type.INTEGER,
                    description="Ancho maximo en pixeles de la imagen (default: 1280)",
                ),
            },
        ),
    ),
    types.FunctionDeclaration(
        name="press_key",
        description=(
            "Pulsa una tecla o combinacion de teclas en la PC. Funciona con "
            "CUALQUIER tecla: letras, numeros, enter, escape, tab, espacio, "
            "flechas, f1-f24, y combinaciones como 'ctrl+c', 'ctrl+shift+j' "
            "o 'alt+f4'. En 'window' puedes indicar el titulo de la ventana "
            "donde debe ir la pulsacion; si lo omites va a la ventana enfocada."
        ),
        parameters=_schema(
            types.Type.OBJECT,
            properties={
                "key": _schema(
                    types.Type.STRING,
                    description="Tecla o combinacion: 'i', 'enter', 'escape', 'ctrl+c', 'ctrl+shift+j'",
                ),
                "presses": _schema(
                    types.Type.INTEGER,
                    description="Cuantas veces repetir la pulsacion (default: 1)",
                ),
                "window": _schema(
                    types.Type.STRING,
                    description="Titulo de la ventana donde pulsar (opcional, ej: 'chrome')",
                ),
            },
            required=["key"],
        ),
    ),
    types.FunctionDeclaration(
        name="type_text",
        description=(
            "Escribe un texto en la PC (en la ventana enfocada, o en la que "
            "indiques en 'window'). No pulsa Enter al final."
        ),
        parameters=_schema(
            types.Type.OBJECT,
            properties={
                "text": _schema(types.Type.STRING, description="Texto a escribir"),
                "window": _schema(
                    types.Type.STRING,
                    description="Titulo de la ventana donde escribir (opcional)",
                ),
            },
            required=["text"],
        ),
    ),
    types.FunctionDeclaration(
        name="click",
        description=(
            "Haz clic con el raton. Si das x e y, hace clic en esa posicion "
            "de la pantalla; si no, hace clic donde este el puntero."
        ),
        parameters=_schema(
            types.Type.OBJECT,
            properties={
                "x": _schema(types.Type.INTEGER, description="Posicion X en pantalla (opcional)"),
                "y": _schema(types.Type.INTEGER, description="Posicion Y en pantalla (opcional)"),
                "button": _schema(
                    types.Type.STRING,
                    description="Boton del raton: 'left', 'right', 'middle'",
                    enum=["left", "right", "middle"],
                ),
                "clicks": _schema(types.Type.INTEGER, description="Numero de clics (default: 1)"),
                "window": _schema(
                    types.Type.STRING,
                    description="Titulo de la ventana donde hacer clic (opcional)",
                ),
            },
        ),
    ),
    types.FunctionDeclaration(
        name="scroll",
        description="Haz scroll con la rueda del raton.",
        parameters=_schema(
            types.Type.OBJECT,
            properties={
                "direction": _schema(
                    types.Type.STRING,
                    description="Direccion del scroll",
                    enum=["up", "down", "left", "right"],
                ),
                "amount": _schema(types.Type.INTEGER, description="Cuantas lineas (default: 3)"),
            },
            required=["direction"],
        ),
    ),
    types.FunctionDeclaration(
        name="move_mouse",
        description="Mueve el puntero del raton a una posicion de la pantalla.",
        parameters=_schema(
            types.Type.OBJECT,
            properties={
                "x": _schema(types.Type.INTEGER, description="Posicion X"),
                "y": _schema(types.Type.INTEGER, description="Posicion Y"),
            },
            required=["x", "y"],
        ),
    ),
    types.FunctionDeclaration(
        name="get_mouse_position",
        description="Devuelve la posicion actual del puntero del raton y el tamano de la pantalla.",
        parameters=_schema(types.Type.OBJECT, properties={}),
    ),
    types.FunctionDeclaration(
        name="list_windows",
        description=(
            "Lista las ventanas abiertas en la PC, con su titulo, posicion y "
            "tamano. La ventana activa va primera. Usala para saber que "
            "programa esta abierto cuando el usuario dice 'cierra eso'."
        ),
        parameters=_schema(
            types.Type.OBJECT,
            properties={
                "limit": _schema(types.Type.INTEGER, description="Maximo de ventanas (default: 25)"),
            },
        ),
    ),
    types.FunctionDeclaration(
        name="get_active_window",
        description="Devuelve la ventana que esta enfocada (en primer plano) ahora mismo.",
        parameters=_schema(types.Type.OBJECT, properties={}),
    ),
    types.FunctionDeclaration(
        name="activate_window",
        description=(
            "Pone una ventana en primer plano y le da el foco, para poder "
            "escribir o pulsar teclas en ella. Busca por coincidencia parcial "
            "del titulo."
        ),
        parameters=_schema(
            types.Type.OBJECT,
            properties={
                "title": _schema(types.Type.STRING, description="Titulo (o parte) de la ventana"),
            },
            required=["title"],
        ),
    ),
    types.FunctionDeclaration(
        name="close_window",
        description=(
            "Cierra una ventana. Si pasas 'title' cierra esa ventana; si lo "
            "omites, cierra la ventana que esta enfocada ahora mismo."
        ),
        parameters=_schema(
            types.Type.OBJECT,
            properties={
                "title": _schema(
                    types.Type.STRING,
                    description="Titulo de la ventana a cerrar (opcional)",
                ),
            },
        ),
    ),
    types.FunctionDeclaration(
        name="minimize_window",
        description="Minimiza una ventana por titulo, o la ventana enfocada si no se indica.",
        parameters=_schema(
            types.Type.OBJECT,
            properties={
                "title": _schema(types.Type.STRING, description="Titulo de la ventana (opcional)"),
            },
        ),
    ),
    types.FunctionDeclaration(
        name="maximize_window",
        description="Maximiza una ventana por titulo, o la ventana enfocada si no se indica.",
        parameters=_schema(
            types.Type.OBJECT,
            properties={
                "title": _schema(types.Type.STRING, description="Titulo de la ventana (opcional)"),
            },
        ),
    ),

    # ── Codigo ──
    types.FunctionDeclaration(
        name="run_python_code",
        description="Ejecuta codigo Python en un sandbox seguro. Accion peligrosa.",
        parameters=_schema(
            types.Type.OBJECT,
            properties={
                "code": _schema(types.Type.STRING, description="Codigo Python a ejecutar"),
                "description": _schema(types.Type.STRING, description="Que hace el codigo"),
            },
            required=["code", "description"],
        ),
    ),

    # Programacion con OpenCode (agente externo via API HTTP local)
    types.FunctionDeclaration(
        name="opencode_code",
        description=(
            "Delega una tarea de PROGRAMACION a OpenCode, un agente que trabaja "
            "de verdad en la PC: crea y modifica archivos de proyectos, escribe "
            "codigo, ejecuta comandos, instala dependencias, usa git, crea "
            "repositorios, monta servidores. Usala SIEMPRE que el usuario pida "
            "programar, crear un proyecto o repositorio, arreglar codigo, "
            "refactorizar, instalar o configurar algo de desarrollo. NO escribas "
            "el codigo tu mismo ni uses write_file para proyectos completos. "
            "Devuelve 'answer' (que hizo, resumelo en 1-2 frases), 'tools', "
            "'files_changed' y 'session_id'. Para cosas de GitHub (crear "
            "repositorio, subir codigo, issues, pull requests) incluye en 'task' "
            "la orden de usar el servidor MCP 'github' (no el comando 'gh')."
        ),
        parameters=_schema(
            types.Type.OBJECT,
            properties={
                "task": _schema(
                    types.Type.STRING,
                    description=(
                        "Objetivo completo y concreto en espanol: que crear o "
                        "cambiar, con que nombres, en que carpeta. Menciona todo "
                        "lo que el usuario pidio."
                    ),
                ),
                "directory": _schema(
                    types.Type.STRING,
                    description=(
                        "Carpeta del proyecto donde trabajar (absoluta). Si el "
                        "usuario no la menciona, dejalo vacio."
                    ),
                ),
                "background": _schema(
                    types.Type.BOOLEAN,
                    description=(
                        "true para tareas largas: devuelve el session_id al "
                        "instante y luego se consulta con opencode_result."
                    ),
                ),
            },
            required=["task"],
        ),
    ),
    types.FunctionDeclaration(
        name="opencode_result",
        description=(
            "Recoge el resultado de una tarea que opencode_code dejo corriendo "
            "(status='running'). Pasa el session_id que te devolvio."
        ),
        parameters=_schema(
            types.Type.OBJECT,
            properties={
                "session_id": _schema(
                    types.Type.STRING, description="session_id de la tarea"
                ),
                "wait_seconds": _schema(
                    types.Type.INTEGER,
                    description="Segundos maximos a esperar (0 = lo configurado)",
                ),
            },
            required=["session_id"],
        ),
    ),
    types.FunctionDeclaration(
        name="opencode_sessions",
        description="Lista las tareas de programacion recientes de OpenCode con su estado.",
        parameters=_schema(
            types.Type.OBJECT,
            properties={
                "limit": _schema(
                    types.Type.INTEGER, description="Cuantas sesiones mostrar (max 10)"
                ),
            },
        ),
    ),
    types.FunctionDeclaration(
        name="opencode_mcp",
        description=(
            "Gestiona los servidores MCP de OpenCode: list (ver cuales hay y su "
            "estado), add (agregar uno remoto con 'url' o local con 'command'), "
            "remove, connect y disconnect."
        ),
        parameters=_schema(
            types.Type.OBJECT,
            properties={
                "action": _schema(
                    types.Type.STRING,
                    description="Que hacer con los MCP",
                    enum=["list", "add", "remove", "connect", "disconnect"],
                ),
                "server": _schema(
                    types.Type.STRING, description="Nombre del servidor MCP"
                ),
                "url": _schema(
                    types.Type.STRING,
                    description="URL del MCP remoto (para action=add)",
                ),
                "command": _schema(
                    types.Type.STRING,
                    description="Comando del MCP local, ej: 'npx -y @paquete/mcp'",
                ),
            },
            required=["action"],
        ),
    ),
]

GEMINI_TOOL = types.Tool(function_declarations=TOOLS)
