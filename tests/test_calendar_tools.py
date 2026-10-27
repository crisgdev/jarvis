import datetime
import unittest
from unittest.mock import patch

from googleapiclient.errors import HttpError

from tools import calendar_tools as ct

PRIMARY_ID = "cristopherguevara2006@gmail.com"
U_ID = "u@group.calendar.google.com"
HOLIDAY_ID = "es.pe#holiday@group.v.calendar.google.com"

CAL_PRIMARY = {"id": PRIMARY_ID, "summary": "Mi cuenta", "primary": True, "accessRole": "owner"}
CAL_U = {"id": U_ID, "summary": "u", "accessRole": "owner"}
CAL_HOLIDAY = {"id": HOLIDAY_ID, "summary": "Festivos en Peru", "accessRole": "reader"}


class _Resp404:
    status = 404
    reason = "Not Found"


class _Ok:
    def __init__(self, data=None):
        self.data = data if data is not None else {}

    def execute(self):
        return self.data


class FakeEventsAPI:
    def __init__(self, by_cal, raise_404_on_delete=False):
        self.by_cal = by_cal
        self.raise_404_on_delete = raise_404_on_delete
        self.deleted = []
        self.inserted = []
        self.patched = []
        self.moved = []

    def list(self, **kw):
        return _Ok({"items": self.by_cal.get(kw.get("calendarId"), [])})

    def get(self, **kw):
        cid = kw.get("calendarId")
        eid = kw.get("eventId")
        for e in self.by_cal.get(cid, []):
            if e["id"] == eid:
                return _Ok(e)
        raise HttpError(_Resp404(), b"not found", uri="https://www.googleapis.com/calendar/v3/")

    def insert(self, **kw):
        body = dict(kw.get("body", {}))
        self.inserted.append((kw.get("calendarId"), body))
        return _Ok({**body, "id": "new_event_id"})

    def patch(self, **kw):
        cid = kw.get("calendarId")
        eid = kw.get("eventId")
        body = dict(kw.get("body", {}))
        self.patched.append((cid, eid, body))
        ev = next((e for e in self.by_cal.get(cid, []) if e["id"] == eid), None)
        if ev is None:
            raise HttpError(_Resp404(), b"not found", uri="https://www.googleapis.com/calendar/v3/")
        ev.update(body)
        return _Ok(ev)

    def move(self, **kw):
        old = kw.get("calendarId")
        eid = kw.get("eventId")
        dest = kw.get("destination")
        self.moved.append((old, eid, dest))
        ev = next((e for e in self.by_cal.get(old, []) if e["id"] == eid), None)
        if ev is None:
            raise HttpError(_Resp404(), b"not found", uri="https://www.googleapis.com/calendar/v3/")
        self.by_cal[old].remove(ev)
        self.by_cal.setdefault(dest, []).append(ev)
        return _Ok(ev)

    def delete(self, **kw):
        cid = kw.get("calendarId")
        eid = kw.get("eventId")
        self.deleted.append((cid, eid))
        known = {e["id"] for e in self.by_cal.get(cid, [])}
        if self.raise_404_on_delete and eid not in known:
            raise HttpError(_Resp404(), b"not found", uri="https://www.googleapis.com/calendar/v3/")
        return _Ok()


class FakeService:
    def __init__(self, cals, events_by_cal, raise_404_on_delete=False):
        self.cals = cals
        self.events_api = FakeEventsAPI(events_by_cal, raise_404_on_delete)

    def calendarList(self):
        cals = self.cals

        class _CL:
            def list(self):
                return _Ok({"items": cals})

        return _CL()

    def events(self):
        return self.events_api


def _ev(ev_id, start, end, summary):
    return {"id": ev_id, "summary": summary, "start": {"dateTime": start}, "end": {"dateTime": end}}


class CalendarBodyTest(unittest.TestCase):
    def test_date_time_gets_config_timezone(self):
        body = ct._event_body("Estudiar", "2026-09-21T18:00:00", "2026-09-21T19:00:00")
        self.assertEqual(body["start"], {"dateTime": "2026-09-21T18:00:00", "timeZone": "America/Lima"})
        self.assertEqual(body["end"]["timeZone"], "America/Lima")

    def test_offset_datetime_kept_verbatim(self):
        body = ct._event_body("X", "2026-09-21T18:00:00-05:00", "2026-09-21T19:00:00-05:00")
        self.assertEqual(body["start"], {"dateTime": "2026-09-21T18:00:00-05:00"})
        self.assertNotIn("timeZone", body["start"])

    def test_explicit_timezone_overrides_config(self):
        body = ct._event_body("X", "2026-09-21T18:00:00", "2026-09-21T19:00:00", timezone="America/Bogota")
        self.assertEqual(body["start"]["timeZone"], "America/Bogota")

    def test_all_day_date_has_no_timezone(self):
        body = ct._event_body("Dia completo", "2026-09-25", "2026-09-26")
        self.assertEqual(body["start"], {"dateTime": "2026-09-25"})

    def test_body_includes_recurrence(self):
        body = ct._event_body(
            "Clase", "2026-10-06T07:00:00", "2026-10-06T08:00:00",
            recurrence=["RRULE:FREQ=WEEKLY;BYDAY=TU"],
        )
        self.assertEqual(body["recurrence"], ["RRULE:FREQ=WEEKLY;BYDAY=TU"])


class RecurrenceTest(unittest.TestCase):
    def test_weekly_rule_without_until(self):
        self.assertEqual(
            ct._build_recurrence("RRULE:FREQ=WEEKLY;BYDAY=TU", "", False),
            ["RRULE:FREQ=WEEKLY;BYDAY=TU"],
        )

    def test_weekly_rule_with_until_timed_converts_to_utc(self):
        rule = ct._build_recurrence("RRULE:FREQ=WEEKLY;BYDAY=TU", "2026-10-15", False)
        self.assertEqual(rule, ["RRULE:FREQ=WEEKLY;BYDAY=TU;UNTIL=20261016T045959Z"])

    def test_until_all_day_keeps_date(self):
        rule = ct._build_recurrence("RRULE:FREQ=DAILY", "2026-10-15", True)
        self.assertEqual(rule, ["RRULE:FREQ=DAILY;UNTIL=20261015"])

    def test_strips_existing_until_from_rule(self):
        rule = ct._build_recurrence("RRULE:FREQ=MONTHLY;UNTIL=20260101T000000Z", "2026-10-15", True)
        self.assertEqual(rule, ["RRULE:FREQ=MONTHLY;UNTIL=20261015"])

    def test_no_recurrence_returns_none(self):
        self.assertIsNone(ct._build_recurrence("", "", False))


class UserCalendarIdsTest(unittest.TestCase):
    def test_includes_owner_and_primary_excludes_holidays(self):
        svc = FakeService([CAL_PRIMARY, CAL_U, CAL_HOLIDAY], {})
        result = ct._user_calendar_ids(svc)
        self.assertEqual(result, [(PRIMARY_ID, "Mi cuenta"), (U_ID, "u")])

    def test_only_primary_when_disabled_in_config(self):
        svc = FakeService([CAL_PRIMARY, CAL_U], {})
        with patch(
            "tools.calendar_tools.get_config",
            return_value={"calendar": {"include_all_user_calendars": False}},
        ):
            result = ct._user_calendar_ids(svc)
        self.assertEqual(result, [("primary", None)])


class UpcomingEventsTest(unittest.TestCase):
    def test_list_calendars_returns_names(self):
        svc = FakeService([CAL_PRIMARY, CAL_U, CAL_HOLIDAY], {})
        with patch("tools.calendar_tools._get_calendar_service", return_value=svc):
            res = ct._list_calendars()
        self.assertEqual(res["count"], 2)
        self.assertEqual(
            res["calendars"],
            [{"calendar": "Mi cuenta", "calendar_id": PRIMARY_ID}, {"calendar": "u", "calendar_id": U_ID}],
        )

    def test_merges_calendars_with_names(self):
        now = datetime.datetime.utcnow()
        day2 = (now + datetime.timedelta(days=2)).isoformat()
        day3 = (now + datetime.timedelta(days=3)).isoformat()
        day4 = (now + datetime.timedelta(days=4)).isoformat()
        events = {
            PRIMARY_ID: [_ev("p1", day3, day3, "comida")],
            U_ID: [_ev("u1", day2, day2, "clase"), _ev("u2", day4, day4, "tarea")],
        }
        svc = FakeService([CAL_PRIMARY, CAL_U], events)
        with patch("tools.calendar_tools._get_calendar_service", return_value=svc):
            res = ct._get_upcoming_events(days_ahead=7)

        self.assertEqual(res["count"], 3)
        self.assertEqual([e["summary"] for e in res["events"]], ["clase", "comida", "tarea"])
        self.assertEqual(res["events"][0]["calendar"], "u")
        self.assertEqual(res["events"][0]["calendar_id"], U_ID)
        self.assertEqual(res["events"][1]["calendar"], "Mi cuenta")
        self.assertIn("u", res["calendars"])
        self.assertIn("Mi cuenta", res["calendars"])

    def test_no_events_message(self):
        svc = FakeService([CAL_PRIMARY], {})
        with patch("tools.calendar_tools._get_calendar_service", return_value=svc):
            res = ct._get_upcoming_events(days_ahead=7)
        self.assertEqual(res["events"], [])

    def test_recurring_instance_gets_master_rrule(self):
        # una ocurrencia de serie repetida resuelve la RRULE del maestro
        now = datetime.datetime.utcnow()
        day = (now + datetime.timedelta(days=2)).isoformat()
        master = {
            "id": "serie1",
            "summary": "push",
            "recurrence": ["RRULE:FREQ=WEEKLY;BYDAY=MO,TH;UNTIL=20261016T235959Z"],
            "start": {"dateTime": day},
            "end": {"dateTime": day},
        }
        inst = {
            "id": "occ1",
            "summary": "push",
            "recurringEventId": "serie1",
            "start": {"dateTime": day},
            "end": {"dateTime": day},
        }
        svc = FakeService([CAL_PRIMARY], {PRIMARY_ID: [master, inst]})
        with patch("tools.calendar_tools._get_calendar_service", return_value=svc):
            res = ct._get_upcoming_events(days_ahead=7)

        ev = next(e for e in res["events"] if e["event_id"] == "occ1")
        self.assertEqual(ev["recurring_event_id"], "serie1")
        self.assertEqual(ev["recurrence"], "RRULE:FREQ=WEEKLY;BYDAY=MO,TH;UNTIL=20261016T235959Z")
        self.assertIn("lunes y jueves", ev["recurrence_text"])
        self.assertIn("16 de octubre", ev["recurrence_text"])

    def test_instance_with_own_recurrence(self):
        # la primera ocurrencia puede traer la RRULE consigo
        now = datetime.datetime.utcnow()
        day = (now + datetime.timedelta(days=1)).isoformat()
        direct = {
            "id": "master1",
            "summary": "clase",
            "recurrence": ["RRULE:FREQ=WEEKLY;BYDAY=TU;UNTIL=20261015"],
            "start": {"dateTime": day},
            "end": {"dateTime": day},
        }
        svc = FakeService([CAL_PRIMARY], {PRIMARY_ID: [direct]})
        with patch("tools.calendar_tools._get_calendar_service", return_value=svc):
            res = ct._get_upcoming_events(days_ahead=7)
        self.assertIn("martes", res["events"][0]["recurrence_text"])


class RruleHumanTest(unittest.TestCase):
    def test_weekly_multi_day_until_datetime(self):
        text = ct._rrule_human("RRULE:FREQ=WEEKLY;BYDAY=MO,TH;UNTIL=20261016T235959Z")
        self.assertIn("lunes y jueves", text)
        self.assertIn("16 de octubre", text)

    def test_weekly_single_day_until_date(self):
        text = ct._rrule_human("RRULE:FREQ=WEEKLY;BYDAY=TU;UNTIL=20261015")
        self.assertIn("martes", text)
        self.assertIn("15 de octubre", text)

    def test_interval_and_count(self):
        text = ct._rrule_human("RRULE:FREQ=DAILY;INTERVAL=2;COUNT=10")
        self.assertIn("cada 2 d", text)
        self.assertIn("10 veces", text)

    def test_empty_rule(self):
        self.assertEqual(ct._rrule_human(""), "sin repetición")


class CreateEventTest(unittest.TestCase):
    def test_resolves_calendar_name(self):
        svc = FakeService([CAL_PRIMARY, CAL_U], {})
        with patch("tools.calendar_tools._get_calendar_service", return_value=svc):
            res = ct._create_calendar_event("X", "2026-09-25T18:00:00", "2026-09-25T19:00:00", calendar="u")

        self.assertEqual(res["status"], "success")
        self.assertEqual(res["calendar_id"], U_ID)
        self.assertEqual(svc.events_api.inserted[0][0], U_ID)

    def test_defaults_to_primary_calendar(self):
        svc = FakeService([CAL_PRIMARY, CAL_U], {})
        with patch("tools.calendar_tools._get_calendar_service", return_value=svc):
            res = ct._create_calendar_event("X", "2026-09-25T18:00:00", "2026-09-25T19:00:00")

        self.assertEqual(res["calendar_id"], "primary")
        self.assertEqual(svc.events_api.inserted[0][0], "primary")

    def test_recurring_event_inserts_rrule(self):
        svc = FakeService([CAL_PRIMARY], {})
        with patch("tools.calendar_tools._get_calendar_service", return_value=svc):
            res = ct._create_calendar_event(
                "Gym",
                "2026-10-06T07:00:00",
                "2026-10-06T08:00:00",
                recurrence="RRULE:FREQ=WEEKLY;BYDAY=TU",
                recurrence_until="2026-10-15",
            )

        inserted_body = svc.events_api.inserted[0][1]
        self.assertEqual(
            inserted_body["recurrence"],
            ["RRULE:FREQ=WEEKLY;BYDAY=TU;UNTIL=20261016T045959Z"],
        )
        self.assertEqual(res["recurrence"], "RRULE:FREQ=WEEKLY;BYDAY=TU;UNTIL=20261016T045959Z")


class UpdateEventTest(unittest.TestCase):
    def test_update_title_time_and_recurrence(self):
        events = {
            PRIMARY_ID: [_ev("e1", "2026-10-06T07:00:00-05:00", "2026-10-06T08:00:00-05:00", "Gym")],
        }
        svc = FakeService([CAL_PRIMARY, CAL_U], events)
        with patch("tools.calendar_tools._get_calendar_service", return_value=svc):
            res = ct._update_calendar_event(
                event_id="e1",
                summary="Cardio",
                start_datetime="2026-10-06T18:00:00",
                end_datetime="2026-10-06T19:00:00",
                recurrence="RRULE:FREQ=WEEKLY;BYDAY=TU",
                recurrence_until="2026-11-01",
            )
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["summary"], "Cardio")
        self.assertEqual(svc.events_api.patched[0][0], PRIMARY_ID)
        patch_body = svc.events_api.patched[0][2]
        self.assertEqual(patch_body["summary"], "Cardio")
        self.assertEqual(patch_body["start"]["dateTime"], "2026-10-06T18:00:00")
        self.assertIn("RRULE:FREQ=WEEKLY;BYDAY=TU", patch_body["recurrence"][0])

    def test_move_to_another_calendar(self):
        events = {
            U_ID: [_ev("e2", "2026-10-06T10:00:00-05:00", "2026-10-06T11:00:00-05:00", "Clase")],
        }
        svc = FakeService([CAL_PRIMARY, CAL_U], events)
        with patch("tools.calendar_tools._get_calendar_service", return_value=svc):
            res = ct._update_calendar_event(event_id="e2", calendar="primary")
        self.assertEqual(res["status"], "success")
        self.assertTrue(res["moved_calendar"])
        self.assertEqual(svc.events_api.moved[0], (U_ID, "e2", PRIMARY_ID))

    def test_remove_recurrence_with_empty_rule(self):
        events = {
            PRIMARY_ID: [
                {
                    "id": "e3",
                    "summary": "T",
                    "start": {"dateTime": "2026-10-06T10:00:00-05:00"},
                    "end": {"dateTime": "2026-10-06T11:00:00-05:00"},
                    "recurrence": ["RRULE:FREQ=WEEKLY;BYDAY=TU"],
                }
            ],
        }
        svc = FakeService([CAL_PRIMARY, CAL_U], events)
        with patch("tools.calendar_tools._get_calendar_service", return_value=svc):
            res = ct._update_calendar_event(event_id="e3", recurrence="")
        self.assertEqual(res["status"], "success")
        self.assertEqual(svc.events_api.patched[0][2]["recurrence"], [])

    def test_unknown_event_returns_error(self):
        svc = FakeService([CAL_PRIMARY, CAL_U], {})
        with patch("tools.calendar_tools._get_calendar_service", return_value=svc):
            res = ct._update_calendar_event(event_id="no_existe")
        self.assertIn("error", res)


class DeleteEventTest(unittest.TestCase):
    def test_direct_delete_by_real_id(self):
        svc = FakeService(
            [CAL_PRIMARY, CAL_U],
            {PRIMARY_ID: [_ev("real1", "2026-09-30T10:00:00-05:00", "2026-09-30T11:00:00-05:00", "X")]},
        )
        with patch("tools.calendar_tools._get_calendar_service", return_value=svc):
            res = ct._delete_calendar_event(event_id="real1")

        self.assertEqual(res["status"], "success")
        self.assertIn((PRIMARY_ID, "real1"), svc.events_api.deleted)

    def test_fallback_finds_event_in_secondary_calendar(self):
        target = "2026-09-30T10:00:00-05:00"
        events = {U_ID: [_ev("u_real", target, "2026-09-30T11:00:00-05:00", "desayuno")]}
        svc = FakeService([CAL_PRIMARY, CAL_U], events, raise_404_on_delete=True)
        with patch("tools.calendar_tools._get_calendar_service", return_value=svc):
            res = ct._delete_calendar_event(event_id=target)

        self.assertEqual(res["status"], "success")
        self.assertEqual(res["calendar_id"], U_ID)
        self.assertIn((U_ID, "u_real"), svc.events_api.deleted)


if __name__ == "__main__":
    unittest.main()