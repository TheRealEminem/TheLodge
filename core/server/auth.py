"""Optional sign-in, for when the app is reachable by other machines.

Local use (the default) needs no login. Set <PREFIX>_ACCESS_TOKEN to a long random string and every API call
then requires it: the browser signs in once and gets an HttpOnly session cookie derived from the token (the
token itself is never stored in the browser).
"""
import hashlib
import hmac
import time

from fastapi import Request, WebSocket

from . import config

TOKEN = config.env("ACCESS_TOKEN", "") or ""
COOKIE = f"{config.APP_ID}_session"
MAX_AGE = 60 * 60 * 24 * 30
OPEN_PATHS = {"/api/auth", "/api/login", "/api/logout", "/api/app"}


def required() -> bool:
    return bool(TOKEN)


def _session_value() -> str:
    return hmac.new(TOKEN.encode(), f"{config.APP_ID}-session-v1".encode(), hashlib.sha256).hexdigest()


def check_token(candidate: str) -> bool:
    ok = bool(TOKEN) and hmac.compare_digest(candidate.encode(), TOKEN.encode())
    if not ok:
        time.sleep(0.6)  # slow down guessing
    return ok


def is_authorized(conn: Request | WebSocket) -> bool:
    if not TOKEN:
        return True
    cookie = conn.cookies.get(COOKIE, "")
    if cookie and hmac.compare_digest(cookie, _session_value()):
        return True
    bearer = conn.headers.get("authorization", "")
    return bearer.startswith("Bearer ") and hmac.compare_digest(bearer[7:].encode(), TOKEN.encode())


def cookie_kwargs(request: Request) -> dict:
    secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    return {"key": COOKIE, "value": _session_value(), "max_age": MAX_AGE, "httponly": True,
            "samesite": "strict", "secure": secure, "path": "/"}
