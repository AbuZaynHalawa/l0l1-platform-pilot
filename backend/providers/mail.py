"""Mail provider interface — same swap pattern as storage.py.

MAIL_BACKEND=console (default): logs what would be sent, marks announcements
"simulated" — safe for early testing, nothing leaves the machine.
MAIL_BACKEND=graph: sends real mail via Microsoft Graph, from your own
Microsoft account, once graph_auth is connected (Mail.Send delegated scope).
"""
import os
from abc import ABC, abstractmethod


class MailProvider(ABC):
    @abstractmethod
    def send_mail(self, to: list[str], subject: str, body_html: str) -> str:
        """Returns a status string: 'sent' | 'simulated' | 'failed'."""


class ConsoleMailProvider(MailProvider):
    def send_mail(self, to: list[str], subject: str, body_html: str) -> str:
        print(f"\n[SIMULATED EMAIL] To: {', '.join(to)}\nSubject: {subject}\n{body_html}\n")
        return "simulated"


class GraphMailProvider(MailProvider):
    def __init__(self):
        from . import graph_auth
        self.graph_auth = graph_auth

    def send_mail(self, to: list[str], subject: str, body_html: str) -> str:
        import httpx
        token = self.graph_auth.get_token()
        url = "https://graph.microsoft.com/v1.0/me/sendMail"
        payload = {
            "message": {
                "subject": subject,
                "body": {"contentType": "HTML", "content": body_html},
                "toRecipients": [{"emailAddress": {"address": addr}} for addr in to],
            },
            "saveToSentItems": "true",
        }
        r = httpx.post(url, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, json=payload)
        return "sent" if r.status_code in (200, 202) else "failed"


def get_mail_provider() -> MailProvider:
    backend = os.environ.get("MAIL_BACKEND", "console")
    if backend == "graph":
        return GraphMailProvider()
    return ConsoleMailProvider()
