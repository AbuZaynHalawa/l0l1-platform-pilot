"""Mail provider interface — same swap pattern as storage.py.

MAIL_BACKEND=console (default): logs what would be sent, marks announcements
"simulated" — safe for early testing, nothing leaves the machine.
MAIL_BACKEND=graph: sends real mail via Microsoft Graph, from your own
Microsoft account, once graph_auth is connected (Mail.Send delegated scope).
"""
import base64
import os
from abc import ABC, abstractmethod

# (filename, content bytes, content-type) -- the shape every provider below
# and every caller into announcements.py agrees on for attachments.
Attachment = tuple[str, bytes, str]


class MailProvider(ABC):
    @abstractmethod
    def send_mail(self, to: list[str], subject: str, body_html: str,
                   attachments: list[Attachment] | None = None) -> str:
        """Returns a status string: 'sent' | 'simulated' | 'failed'."""


class ConsoleMailProvider(MailProvider):
    def send_mail(self, to: list[str], subject: str, body_html: str,
                   attachments: list[Attachment] | None = None) -> str:
        att_note = f"\nAttachments: {', '.join(a[0] for a in attachments)}" if attachments else ""
        print(f"\n[SIMULATED EMAIL] To: {', '.join(to)}\nSubject: {subject}{att_note}\n{body_html}\n")
        return "simulated"


class GraphMailProvider(MailProvider):
    def __init__(self):
        from . import graph_auth
        self.graph_auth = graph_auth

    def send_mail(self, to: list[str], subject: str, body_html: str,
                   attachments: list[Attachment] | None = None) -> str:
        import httpx
        token = self.graph_auth.get_token()
        url = "https://graph.microsoft.com/v1.0/me/sendMail"
        message = {
            "subject": subject,
            "body": {"contentType": "HTML", "content": body_html},
            "toRecipients": [{"emailAddress": {"address": addr}} for addr in to],
        }
        if attachments:
            message["attachments"] = [
                {
                    "@odata.type": "#microsoft.graph.fileAttachment",
                    "name": filename,
                    "contentType": content_type,
                    "contentBytes": base64.b64encode(content).decode("ascii"),
                }
                for filename, content, content_type in attachments
            ]
        payload = {"message": message, "saveToSentItems": "true"}
        r = httpx.post(url, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, json=payload)
        return "sent" if r.status_code in (200, 202) else "failed"


def get_mail_provider() -> MailProvider:
    backend = os.environ.get("MAIL_BACKEND", "console")
    if backend == "graph":
        return GraphMailProvider()
    return ConsoleMailProvider()
