"""OAuth clients (Google). Registered only when the user clicks Login with Google.

Importing this module must not talk to accounts.google.com — that used to
happen at process start via server_metadata_url and looked like an OAuth launch.
"""
from authlib.integrations.starlette_client import OAuth

from backend.core.config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET

oauth = OAuth()
_google_ready = False


def google_configured() -> bool:
    return bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)


def ensure_google() -> bool:
    """Bind the Google client on first use. Safe to call repeatedly."""
    global _google_ready
    if _google_ready:
        return True
    if not google_configured():
        return False
    oauth.register(
        name="google",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )
    _google_ready = True
    return True
