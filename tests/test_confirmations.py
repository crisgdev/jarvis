import unittest

from core.confirmations import (
    DANGEROUS_TOOL_LABELS,
    confirmation_request,
    confirmation_to_message,
)
from brain.tools_executor import RISK_LEVELS


class ConfirmationsTest(unittest.TestCase):
    def test_all_dangerous_tools_have_labels(self):
        dangerous = {k for k, v in RISK_LEVELS.items() if v == "dangerous"}
        self.assertTrue(dangerous)
        self.assertEqual(set(DANGEROUS_TOOL_LABELS), dangerous)

    def test_confirmation_request_formats_email(self):
        title, message = confirmation_request(
            "send_email", {"to": "a@b.com", "subject": "Prueba"}
        )
        self.assertEqual(title, "Enviar email")
        self.assertIn("a@b.com", message)
        self.assertIn("Prueba", message)

    def test_confirmation_request_default_title(self):
        title, message = confirmation_request("unknown_tool", {})
        self.assertEqual(title, "unknown_tool")
        self.assertIn("peligrosa", message)

    def test_confirmation_to_message_markdown(self):
        msg = confirmation_to_message("send_email", {"to": "a@b.com", "subject": "Hi"})
        self.assertIn("*Enviar email*", msg)
        self.assertIn("a@b.com", msg)
        self.assertIn("¿Confirmas", msg)

    def test_delete_event_with_summary(self):
        title, message = confirmation_request(
            "delete_calendar_event", {"event_id": "x", "summary": "push"}
        )
        self.assertEqual(title, "Eliminar evento")
        self.assertIn("push", message)

    def test_delete_event_without_summary(self):
        title, message = confirmation_request("delete_calendar_event", {"event_id": "x"})
        self.assertEqual(title, "Eliminar evento")
        self.assertIn("evento", message)
        self.assertNotIn("{summary}", message)


if __name__ == "__main__":
    unittest.main()