import os
import imaplib
import email
from email.header import decode_header

import yagmail

from config import get_env
from brain.tools_executor import register_tool


@register_tool("send_email")
def _send_email(to: str, subject: str, body: str) -> dict:
    gmail_user = get_env("GMAIL_USER")
    gmail_pass = get_env("GMAIL_APP_PASSWORD")
    if not gmail_user or not gmail_pass:
        return {"error": "Gmail no configurado. Falta GMAIL_USER o GMAIL_APP_PASSWORD en .env"}

    try:
        yag = yagmail.SMTP(gmail_user, gmail_pass)
        yag.send(to=to, subject=subject, contents=body)
        return {"status": "success", "message": f"Email enviado a {to}"}
    except Exception as e:
        return {"error": f"Error enviando email: {e}"}


@register_tool("read_recent_emails")
def _read_recent_emails(count: int = 5) -> dict:
    gmail_user = get_env("GMAIL_USER")
    gmail_pass = get_env("GMAIL_APP_PASSWORD")
    if not gmail_user or not gmail_pass:
        return {"error": "Gmail no configurado. Falta GMAIL_USER o GMAIL_APP_PASSWORD en .env"}

    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(gmail_user, gmail_pass)
        mail.select("INBOX")

        _, data = mail.search(None, "ALL")
        mail_ids = data[0].split()
        recent_ids = mail_ids[-count:]

        emails = []
        for mid in reversed(recent_ids):
            _, msg_data = mail.fetch(mid, "(RFC822)")
            msg = email.message_from_bytes(msg_data[0][1])

            subject = msg["Subject"] or "(sin asunto)"
            decoded = decode_header(subject)
            subject_text = ""
            for part, enc in decoded:
                if isinstance(part, bytes):
                    subject_text += part.decode(enc or "utf-8", errors="replace")
                else:
                    subject_text += part

            from_addr = msg["From"] or ""
            date = msg["Date"] or ""

            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        body = part.get_payload(decode=True).decode("utf-8", errors="replace")[:200]
                        break
            else:
                body = msg.get_payload(decode=True).decode("utf-8", errors="replace")[:200]

            emails.append({
                "from": from_addr,
                "subject": subject_text,
                "date": date,
                "preview": body.strip(),
            })

        mail.logout()
        return {"emails": emails, "count": len(emails)}
    except Exception as e:
        return {"error": f"Error leyendo emails: {e}"}
