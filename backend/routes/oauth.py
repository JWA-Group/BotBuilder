"""Настройка OAuth-клиентов (Google и др.)."""
from authlib.integrations.starlette_client import OAuth

# Берём из config (там уже загружен .env через main)
from backend.core.config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET

oauth = OAuth()
if GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET:
    oauth.register(
        name="google",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )
