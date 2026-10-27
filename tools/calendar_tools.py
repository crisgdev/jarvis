import os
import re
import datetime
import json

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from config import get_config, BASE_DIR
from brain.tools_executor import register_tool

SCOPES = ["https://www.googleapis.com/auth/calendar"]
CREDENTIALS_FILE = BASE_DIR / "credentials.json"
TOKEN_FILE = BASE_DIR / "token.json"


def _get_timezone() -> str:
    return get_config().get("calendar", {}).get("timezone", "America/Lima")


def _dt_has_offset(dt: str) -> bool:
    return bool(re.search(r"[+-]\d{2}:\d{2}$", dt.strip()))


def _event_body(
    summary: str,
    start_datetime: str,
    end_datetime: str,
    description: str = "",
    timezone: str = "",
    recurrence: list = None,
) -> dict:
    tz = timezone or _get_timezone()

    def _part(dt: str) -> dict:
        if _dt_has_offset(dt) or len(dt.strip()) == 10:
            return {"dateTime": dt}
        return {"dateTime": dt, "timeZone": tz}

    body = {
        "summary": summary,
        "description": description,
        "start": _part(start_datetime),
        "end": _part(end_datetime),
    }
    if recurrence:
        body["recurrence"] = recurrence
    return body


def _compute_until(until_date: str, is_all_day: bool, tz: str) -> str:
    """Convierte '2026-10-15' a la parte UNTIL de la RRULE.

    Eventos de dia completo: hasta el dia 15 inclusive (YYYYMMDD).
    Eventos con hora: fin del dia local 15/10 23:59:59 en UTC (YYYYMMDDTHHMMSSZ).
    """
    d = datetime.date.fromisoformat(str(until_date).strip()[:10])
    if is_all_day:
        return d.strftime("%Y%m%d")
    from zoneinfo import ZoneInfo
    from datetime import timezone as dt_tz

    dt_local = datetime.datetime.combine(d, datetime.time(23, 59, 59))
    dt_utc = dt_local.replace(tzinfo=ZoneInfo(tz)).astimezone(dt_tz.utc)
    return dt_utc.strftime("%Y%m%dT%H%M%SZ")


def _build_recurrence(
    recurrence: str,
    recurrence_until: str,
    is_all_day: bool,
) -> list | None:
    """Arma la lista 'recurrence' para Google Calendar.

    recurrence: RRULE sin UNTIL, ej 'RRULE:FREQ=WEEKLY;BYDAY=TU'.
    recurrence_until: fecha final en formato ISO '2026-10-15'.
    """
    rule = (recurrence or "").strip()
    if not rule:
        return None
    if rule.upper().startswith("RRULE:"):
        rule = rule[len("RRULE:"):]
    parts = [p for p in rule.split(";") if p and not p.upper().startswith("UNTIL=")]
    rule = ";".join(parts)
    until = (recurrence_until or "").strip()
    if until:
        rule = f"{rule};UNTIL={_compute_until(until, is_all_day, _get_timezone())}"
    return [f"RRULE:{rule}"]


def _get_calendar_service():
    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDENTIALS_FILE.exists():
                return None
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_FILE), SCOPES
            )
            creds = flow.run_local_server(port=0)
        TOKEN_FILE.write_text(creds.to_json())
    return build("calendar", "v3", credentials=creds)


def _user_calendar_ids(service) -> list:
    """Calendarios del usuario a consultar: [(id, summary), ...].

    Incluye el principal y los calendarios propios (owner/writer),
    excluyendo festivos (reader) y calendarios de Google.
    Si config 'calendar.include_all_user_calendars' es false, solo el principal.
    """
    cfg = get_config().get("calendar", {})
    if cfg.get("include_all_user_calendars", True) is False:
        return [("primary", None)]

    try:
        items = service.calendarList().list().execute().get("items", [])
    except Exception:
        return [("primary", None)]

    result = []
    for c in items:
        cid = c.get("id")
        summary = c.get("summary") or cid
        if c.get("primary") or cid == "primary":
            result.append((cid, summary))
            continue
        if c.get("accessRole") not in ("owner", "writer"):
            continue
        if "@group.v.calendar.google.com" in str(cid):
            continue
        if "holiday" in summary.lower() or "festivo" in summary.lower():
            continue
        result.append((cid, summary))
    return result or [("primary", None)]


def _resolve_calendar_id(service, name) -> str | None:
    """Resuelve un nombre o id ('mi chamba', 'u', ...) al id real del calendario."""
    name = (name or "").strip()
    if not name:
        return None
    try:
        items = service.calendarList().list().execute().get("items", [])
    except Exception:
        return None
    needle = name.lower()
    primary_id = None
    for c in items:
        if c.get("primary"):
            primary_id = c.get("id")
    if needle in ("primary", "principal", "mi calendario", "mi cuenta", "el principal"):
        return primary_id or "primary"
    for c in items:
        cid = str(c.get("id", ""))
        cname = (c.get("summary") or "").lower()
        if cid == name or cid.lower() == needle or cname == needle:
            return c.get("id")
    for c in items:
        cname = (c.get("summary") or "").lower()
        if needle in cname or cname in needle:
            return c.get("id")
    return None


@register_tool("list_calendars")
def _list_calendars() -> dict:
    """Lista los calendarios del usuario (nombre e id) para ofrecer opciones."""
    service = _get_calendar_service()
    if not service:
        return {"error": "Google Calendar no configurado. Falta credentials.json"}
    try:
        cals = [{"calendar": name, "calendar_id": cid} for cid, name in _user_calendar_ids(service)]
        return {"calendars": cals, "count": len(cals)}
    except Exception as e:
        return {"error": f"Error listando calendarios: {e}"}


def _iso_utc(dt: datetime.datetime) -> str:
    """Convierte una fecha/hora local (naive) a ISO UTC 'YYYY-MM-DDTHH:MM:SSZ'."""
    from datetime import timezone as dt_tz
    from zoneinfo import ZoneInfo

    return (
        dt.replace(tzinfo=ZoneInfo(_get_timezone()))
        .astimezone(dt_tz.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ")
    )


_WEEKDAYS = {
    "MO": "lunes", "TU": "martes", "WE": "miércoles",
    "TH": "jueves", "FR": "viernes", "SA": "sábado", "SU": "domingo",
}
_MONTHS = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]
_FREQ_CADENCE = {
    "DAILY": ("diario", "días"),
    "WEEKLY": ("semanal", "semanas"),
    "MONTHLY": ("mensual", "meses"),
    "YEARLY": ("anual", "años"),
}


def _rrule_human(rule: str) -> str:
    """Convierte una RRULE de Google Calendar a espanol comprensible.

    Ej: 'RRULE:FREQ=WEEKLY;BYDAY=MO,TH;UNTIL=20261016T235959Z'
        -> 'se repite semanal los lunes y jueves, y finaliza el 16
            de octubre de 2026'
    """
    if not rule:
        return "sin repetición"

    parts: dict[str, str] = {}
    for token in (rule.split(":", 1)[-1]).split(";"):
        if "=" in token:
            k, v = token.split("=", 1)
            parts[k] = v

    freq = parts.get("FREQ", "")
    interval = 1
    try:
        interval = int(parts.get("INTERVAL", "1") or 1)
    except ValueError:
        interval = 1

    cadence, plural = _FREQ_CADENCE.get(freq, (freq.lower(), "períodos"))
    if interval > 1:
        cadence = f"cada {interval} {plural}"
    elif freq in _FREQ_CADENCE:
        cadence = _FREQ_CADENCE[freq][0]

    bits = [f"se repite {cadence}"]

    days = [
        _WEEKDAYS.get(d.strip()[-2:], d.strip()[-2:])
        for d in parts.get("BYDAY", "").split(",") if d.strip()
    ]
    if days:
        if len(days) == 1:
            bits.append(f"los {days[0]}")
        else:
            bits.append(f"los {', '.join(days[:-1])} y {days[-1]}")

    count = parts.get("COUNT", "")
    until = parts.get("UNTIL", "").rstrip("Z")
    if count:
        bits.append(f"un total de {count} veces")
    elif until:
        try:
            if len(until) >= 8:
                d = datetime.datetime.strptime(until[:8], "%Y%m%d")
                bits.append(f"y finaliza el {d.day} de {_MONTHS[d.month - 1]} de {d.year}")
            else:
                bits.append(f"y finaliza el {until}")
        except ValueError:
            bits.append(f"y finaliza el {until[:8]}")

    if len(bits) == 1 and freq:
        return rule
    return " ".join(bits)


def _fetch_master_rules(service, cid: str, recurring_ids) -> dict:
    """Obtiene la RRULE de los eventos 'maestros' (series repetidas).

    Con singleEvents=True la API devuelve cada ocurrencia SIN la repeticion;
    la RRULE vive en el evento maestro (recurringEventId). Se resuelve cada
    serie una sola vez, con tope para no disparar llamadas sin fin.
    """
    ids = [rid for rid in dict.fromkeys(recurring_ids) if rid]
    rules: dict[str, list] = {}
    for rid in ids[:20]:
        try:
            master = service.events().get(calendarId=cid, eventId=rid).execute()
            rules[rid] = master.get("recurrence") or []
        except Exception:
            rules[rid] = []
    return rules


@register_tool("get_upcoming_events")
def _get_upcoming_events(days_ahead: int = 30, start_date: str = "", end_date: str = "") -> dict:
    """Eventos próximos. Sin limites de cercania: si el usuario nombra un dia
    o fecha concreta, pasale 'start_date'/'end_date' (YYYY-MM-DD) y se busca
    ese dia exacto sin importar cuán lejos este. Solo con 'days_ahead' no basta
    cuando el dia pedido queda mas alla (los eventos cercanos copan la lista).
    """
    service = _get_calendar_service()
    if not service:
        return {"error": "Google Calendar no configurado. Falta credentials.json"}

    now = datetime.datetime.utcnow()
    cal_ids = _user_calendar_ids(service)
    max_total = get_config().get("calendar", {}).get("max_results", 100)

    def _parse_date(s: str) -> datetime.date:
        return datetime.date.fromisoformat(str(s).strip()[:10])

    if start_date:
        time_min = _iso_utc(datetime.datetime.combine(_parse_date(start_date), datetime.time.min))
    else:
        time_min = now.isoformat() + "Z"

    if end_date:
        time_max = _iso_utc(datetime.datetime.combine(_parse_date(end_date), datetime.time.max))
    else:
        # Incluye el dia completo a days_ahead (timeMax es exclusivo).
        end_day = now + datetime.timedelta(days=max(0, int(days_ahead)))
        time_max = _iso_utc(datetime.datetime.combine(end_day.date(), datetime.time.max))

    try:
        result = []
        for cid, cname in cal_ids:
            try:
                events_result = service.events().list(
                    calendarId=cid,
                    timeMin=time_min,
                    timeMax=time_max,
                    maxResults=50,
                    singleEvents=True,
                    orderBy="startTime",
                ).execute()
            except HttpError:
                continue

            items = events_result.get("items", [])
            masters = _fetch_master_rules(
                service,
                cid,
                (ev.get("recurringEventId") for ev in items),
            )

            for ev in items:
                start = ev["start"].get("dateTime", ev["start"].get("date"))
                end = ev["end"].get("dateTime", ev["end"].get("date"))
                rid = ev.get("recurringEventId")
                rrules = ev.get("recurrence") or masters.get(rid) or []
                rrule = (rrules or [None])[0]
                result.append({
                    "event_id": ev.get("id", ""),
                    "summary": ev.get("summary", "(sin título)"),
                    "start": start,
                    "end": end,
                    "description": ev.get("description", ""),
                    "calendar": cname or cid,
                    "calendar_id": cid,
                    "recurring_event_id": rid or "",
                    "recurrence": rrule or "",
                    "recurrence_text": _rrule_human(rrule) if rrule else "",
                })

        result.sort(key=lambda e: e["start"])
        if max_total and len(result) > max_total:
            result = result[:max_total]

        if not result:
            if start_date:
                return {"events": [], "message": f"No hay eventos el {start_date}"}
            return {"events": [], "message": f"No hay eventos en el periodo solicitado"}

        calendars = sorted({e["calendar"] for e in result})
        return {"events": result, "count": len(result), "calendars": calendars}
    except Exception as e:
        return {"error": f"Error leyendo calendario: {e}"}


@register_tool("create_calendar_event")
def _create_calendar_event(
    summary: str,
    start_datetime: str,
    end_datetime: str,
    description: str = "",
    timezone: str = "",
    calendar: str = "",
    recurrence: str = "",
    recurrence_until: str = "",
) -> dict:
    service = _get_calendar_service()
    if not service:
        return {"error": "Google Calendar no configurado. Falta credentials.json"}

    try:
        cal_id = _resolve_calendar_id(service, calendar)
        if not cal_id:
            cal_id = get_config().get("calendar", {}).get("primary_calendar_id", "primary")
        is_all_day = len(start_datetime.strip()) == 10
        rec = _build_recurrence(recurrence, recurrence_until, is_all_day)
        event = _event_body(
            summary,
            start_datetime,
            end_datetime,
            description,
            timezone,
            recurrence=rec,
        )
        created = service.events().insert(calendarId=cal_id, body=event).execute()
        return {
            "status": "success",
            "message": f"Evento '{summary}' creado",
            "event_id": created.get("id"),
            "start": created.get("start", {}).get("dateTime"),
            "end": created.get("end", {}).get("dateTime"),
            "calendar_id": cal_id,
            "recurrence": (created.get("recurrence") or [None])[0],
        }
    except Exception as e:
        return {"error": f"Error creando evento: {e}"}


def _locate_event(service, cal_ids, event_id: str, summary: str = "") -> tuple:
    """Encuentra (calendar_id, evento) buscando por id real; respalda por hora/titulo."""
    event_id = (event_id or "").strip()
    target = event_id.lower()
    needle = (summary or "").strip().lower()

    for cid, _cname in cal_ids:
        try:
            ev = service.events().get(calendarId=cid, eventId=event_id).execute()
            return cid, ev
        except HttpError as e:
            if e.resp.status != 404:
                raise

    now = datetime.datetime.utcnow()
    for cid, _cname in cal_ids:
        events_result = service.events().list(
            calendarId=cid,
            timeMin=(now - datetime.timedelta(days=365)).isoformat() + "Z",
            timeMax=(now + datetime.timedelta(days=366)).isoformat() + "Z",
            maxResults=250,
            singleEvents=True,
        ).execute()
        for ev in events_result.get("items", []):
            start = ev["start"].get("dateTime", ev["start"].get("date", ""))
            end = ev["end"].get("dateTime", ev["end"].get("date", ""))
            if target and target in (start.lower(), end.lower()):
                return cid, ev
            if needle and needle in (ev.get("summary") or "").lower():
                return cid, ev
    return None, None


@register_tool("update_calendar_event")
def _update_calendar_event(
    event_id: str,
    summary: str = None,
    start_datetime: str = None,
    end_datetime: str = None,
    description: str = None,
    timezone: str = "",
    calendar: str = "",
    recurrence: str = None,
    recurrence_until: str = None,
) -> dict:
    service = _get_calendar_service()
    if not service:
        return {"error": "Google Calendar no configurado. Falta credentials.json"}

    try:
        cal_ids = _user_calendar_ids(service)
        current_cid, current_ev = _locate_event(service, cal_ids, event_id, summary or "")
        if not current_cid:
            return {"error": f"No encontré el evento {event_id!r} en tus calendarios."}

        target_cid = _resolve_calendar_id(service, calendar) if calendar else None
        moved = False
        if target_cid and target_cid != current_cid:
            service.events().move(
                calendarId=current_cid, eventId=event_id, destination=target_cid
            ).execute()
            current_cid = target_cid
            moved = True

        patch = {}
        if summary is not None:
            patch["summary"] = summary
        if description is not None:
            patch["description"] = description
        if start_datetime is not None or end_datetime is not None:
            prev_start = current_ev["start"].get("dateTime", current_ev["start"].get("date"))
            prev_end = current_ev["end"].get("dateTime", current_ev["end"].get("date"))
            body = _event_body(
                patch.get("summary", current_ev.get("summary", "")),
                start_datetime or prev_start,
                end_datetime or prev_end,
                patch.get("description", current_ev.get("description", "")),
                timezone,
            )
            patch["start"] = body["start"]
            patch["end"] = body["end"]
        if recurrence is not None or recurrence_until is not None:
            is_all_day = len(
                (start_datetime or current_ev["start"].get("dateTime", "")).strip()
            ) == 10
            if recurrence is not None and not recurrence.strip():
                patch["recurrence"] = []
            elif recurrence and recurrence.strip():
                rec = _build_recurrence(recurrence, recurrence_until or "", is_all_day)
                if rec:
                    patch["recurrence"] = rec

        if patch:
            service.events().patch(
                calendarId=current_cid, eventId=event_id, body=patch
            ).execute()

        start = patch.get("start", current_ev["start"])
        end = patch.get("end", current_ev["end"])
        rec = patch.get("recurrence", current_ev.get("recurrence"))
        return {
            "status": "success",
            "message": "Evento actualizado",
            "event_id": event_id,
            "calendar_id": current_cid,
            "moved_calendar": moved,
            "summary": patch.get("summary", current_ev.get("summary")),
            "start": start.get("dateTime", start.get("date")),
            "end": end.get("dateTime", end.get("date")),
            "recurrence": (rec or [None])[0],
        }
    except Exception as e:
        return {"error": f"Error actualizando evento: {e}"}


@register_tool("delete_calendar_event")
def _delete_calendar_event(event_id: str, summary: str = "") -> dict:
    service = _get_calendar_service()
    if not service:
        return {"error": "Google Calendar no configurado. Falta credentials.json"}

    def _matches(ev, target: str, needle: str) -> bool:
        start = ev["start"].get("dateTime", ev["start"].get("date", ""))
        end = ev["end"].get("dateTime", ev["end"].get("date", ""))
        if target and target in (start.lower(), end.lower()):
            return True
        title = (ev.get("summary") or "").lower()
        return bool(needle and needle in title)

    try:
        cal_ids = _user_calendar_ids(service)
        target = event_id.strip().lower()
        needle = summary.strip().lower()

        # 1) Intento directo por id real en cada calendario.
        for cid, _cname in cal_ids:
            try:
                service.events().delete(calendarId=cid, eventId=event_id).execute()
                return {"status": "success", "message": "Evento eliminado", "calendar_id": cid}
            except HttpError as e:
                if e.resp.status != 404:
                    raise

        # 2) Respaldo: el id pudo ser una hora en vez del id real.
        #    Buscar en el año completo por hora de inicio/fin o por titulo.
        now = datetime.datetime.utcnow()
        for cid, cname in cal_ids:
            events_result = service.events().list(
                calendarId=cid,
                timeMin=(now - datetime.timedelta(days=365)).isoformat() + "Z",
                timeMax=(now + datetime.timedelta(days=366)).isoformat() + "Z",
                maxResults=250,
                singleEvents=True,
            ).execute()
            for ev in events_result.get("items", []):
                if _matches(ev, target, needle):
                    service.events().delete(calendarId=cid, eventId=ev["id"]).execute()
                    return {
                        "status": "success",
                        "message": f"Evento '{ev.get('summary')}' eliminado",
                        "calendar_id": cid,
                    }
        return {"error": f"No se encontró un evento que coincida con el id {event_id!r}"}
    except Exception as e:
        return {"error": f"Error eliminando evento: {e}"}
