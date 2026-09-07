"""Sign-in gate for the landing page (landing.js's #hvSigninForm).

Not real per-user authentication -- there's still no session/identity
system behind it (every role/action elsewhere in the app is the existing
self-reported actor_email/actor_role, untouched by this). This is
narrower and explicitly temporary, per Yasser's own framing ("make it
only available for these emails for now"): a single shared password
gates the whole platform to a fixed, named list of people, replacing the
previous "type anything, get in" dummy sign-in. Checked server-side (not
just in landing.js) so the allowlist/password aren't just sitting in
public JS for anyone to read past.

The real SSO/Entra ID replacement this was always meant to lead to is
tracked in memory ([[project_l0l1_prelaunch_suggestions]] item 1) --
this endpoint is the stopgap, not that.
"""
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Case-insensitive on the email; the password is one shared secret for
# everyone on the list, not per-person -- simplest thing that satisfies
# "these six people only, for now," not a real credential store.
_ALLOWED_EMAILS = {
    "mahmoud.qazaq@algihaz.com",
    "yasser.halawa@algihaz.com",
    "mohammad.alqaq@algihaz.com",
    "hala.almajali@algihaz.com",
    "hasan.khaled@algihaz.com",
    "l0l1guest@algihaz.com",
}
_SHARED_PASSWORD = "L0-L1-Access"


class LoginPayload(BaseModel):
    email: str
    password: str


@router.post("/login")
def login(payload: LoginPayload):
    email = (payload.email or "").strip().lower()
    ok = email in _ALLOWED_EMAILS and payload.password == _SHARED_PASSWORD
    # Deliberately the same generic message either way -- doesn't confirm
    # or deny whether a given email is on the list.
    return {"ok": ok, "error": None if ok else "Incorrect email or password."}
