"""Microsoft Graph auth — lets the app act as you (upload to your OneDrive,
send mail as you) without you logging in every time it runs.

Setup (one-time, done by the project owner, not by any end tester):
1. Register an app at https://portal.azure.com -> Azure Active Directory ->
   App registrations -> New registration. Any Microsoft account can do this,
   no company approval needed for a personal/individual app registration.
2. Under "API permissions", add Microsoft Graph *delegated* permissions:
   Files.ReadWrite, Mail.Send, User.Read, offline_access. Click "Grant admin
   consent" if you're able to (or just "Accept" the consent prompt in step 4
   if your tenant allows user consent — Algihaz's tenant may or may not; if
   the consent screen is blocked, that's the one step that needs an IT admin).
3. Under "Certificates & secrets", create a client secret and copy its value.
4. Set these environment variables (a .env file locally, or the hosting
   platform's env var settings once deployed):
     GRAPH_CLIENT_ID, GRAPH_CLIENT_SECRET, GRAPH_TENANT_ID
5. Run `python -m app.backend.providers.graph_auth` once from a terminal —
   it walks you through a one-time device-code sign-in and prints a
   GRAPH_REFRESH_TOKEN value to also add to your env vars. After that, the
   app renews its own access token automatically; you never sign in again.
"""
import os
import time
import msal

CLIENT_ID = os.environ.get("GRAPH_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("GRAPH_CLIENT_SECRET", "")
TENANT_ID = os.environ.get("GRAPH_TENANT_ID", "common")
REFRESH_TOKEN = os.environ.get("GRAPH_REFRESH_TOKEN", "")
SCOPES = ["Files.ReadWrite", "Mail.Send", "User.Read"]

AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"

_cached_token = {"value": None, "expires_at": 0}


def _app():
    return msal.ConfidentialClientApplication(
        CLIENT_ID, authority=AUTHORITY, client_credential=CLIENT_SECRET
    )


def get_token() -> str:
    """Returns a valid access token, refreshing via the stored refresh token
    when needed. Raises a clear error if Graph auth hasn't been set up yet —
    the app still runs fine without it (storage/mail just fall back to the
    local/console providers), this is only called when STORAGE_BACKEND or
    MAIL_BACKEND is explicitly set to the real Graph-backed provider.
    """
    now = time.time()
    if _cached_token["value"] and _cached_token["expires_at"] > now + 60:
        return _cached_token["value"]

    if not (CLIENT_ID and CLIENT_SECRET and REFRESH_TOKEN):
        raise RuntimeError(
            "Microsoft Graph isn't connected yet. Set GRAPH_CLIENT_ID, "
            "GRAPH_CLIENT_SECRET, GRAPH_TENANT_ID and GRAPH_REFRESH_TOKEN "
            "(see the setup steps at the top of graph_auth.py), or leave "
            "STORAGE_BACKEND/MAIL_BACKEND unset to keep using the local "
            "stand-ins while you get that set up."
        )

    result = _app().acquire_token_by_refresh_token(REFRESH_TOKEN, scopes=SCOPES)
    if "access_token" not in result:
        raise RuntimeError(f"Graph token refresh failed: {result.get('error_description', result)}")
    _cached_token["value"] = result["access_token"]
    _cached_token["expires_at"] = now + result.get("expires_in", 3600)
    return _cached_token["value"]


def _bootstrap_device_code():
    """Interactive one-time setup — run this file directly to use it."""
    app = msal.PublicClientApplication(CLIENT_ID, authority=AUTHORITY)
    flow = app.initiate_device_flow(scopes=SCOPES)
    if "user_code" not in flow:
        raise RuntimeError(f"Could not start device flow: {flow}")
    print(flow["message"])
    result = app.acquire_token_by_device_flow(flow)
    if "refresh_token" in result:
        print("\nSuccess. Add this to your environment variables:\n")
        print(f"GRAPH_REFRESH_TOKEN={result['refresh_token']}")
    else:
        print(f"Failed: {result.get('error_description', result)}")


if __name__ == "__main__":
    _bootstrap_device_code()
