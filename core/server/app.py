"""The app's server: the host's own API, every enabled module's API under /api/<module>, and the web app.

Run it with `uvicorn core.server.app:app` from the repository root (scripts/dev does this). One process is
the whole app: on a Mac it's started and supervised by the menu bar app; on a server, by Docker.
"""
import logging
import os
import signal
import threading
import time
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import ai, auth, config, db, events, jobs, links, module, search, settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("core")

CORE_SETTINGS = {"your_name": ""}  # shared by every module: "You" in anything that names people


def _exit_with_parent() -> None:
    """The Mac app starts this server and names itself in <PREFIX>_PARENT_PID. If the app is force-quit or
    crashes, this process is re-parented to launchd; stop instead of lingering on the port."""
    parent = int(config.env("PARENT_PID") or 0)
    if not parent:
        return

    def watch():
        while os.getppid() == parent:
            time.sleep(2)
        os.kill(os.getpid(), signal.SIGTERM)

    threading.Thread(target=watch, daemon=True, name="parent-watch").start()


def setup() -> list[module.Module]:
    """Database, settings and modules: everything except the web server. Tests call this too."""
    db.init()
    settings.declare("core", CORE_SETTINGS)
    ai.declare()
    return module.load(config.enabled_modules())


@asynccontextmanager
async def lifespan(_: FastAPI):
    _exit_with_parent()
    jobs.recover()
    yield


def create_app() -> FastAPI:
    loaded = setup()
    app = FastAPI(title=config.NAME, lifespan=lifespan)

    @app.middleware("http")
    async def require_login(request: Request, call_next):
        path = request.url.path
        if path.startswith("/api/") and path not in auth.OPEN_PATHS and not auth.is_authorized(request):
            return JSONResponse({"detail": "Sign in required"}, status_code=401)
        return await call_next(request)

    app.include_router(core_router, prefix="/api")
    for m in loaded:
        if m.router:
            app.include_router(m.router, prefix=f"/api/{m.id}", tags=[m.name])

    if config.UI_DIR.joinpath("index.html").exists():  # the built web app (absent in development: Vite serves it)
        app.mount("/", StaticFiles(directory=config.UI_DIR, html=True), name="ui")
    return app


# ── The host's own API ────────────────────────────────────────────────

core_router = APIRouter()


class LoginRequest(BaseModel):
    token: str


class JobGo(BaseModel):
    force: bool = False


class LinkBody(BaseModel):
    from_ref: str
    to_ref: str
    kind: str = "related"


@core_router.get("/app")
def app_info():
    """Who this app is and what it's made of; the web app builds its navigation from this."""
    return {"id": config.APP_ID, "name": config.NAME, "tagline": config.IDENTITY.get("tagline", ""),
            "version": config.VERSION, "modules": [{"id": m.id, "name": m.name} for m in module.all_modules()],
            "auth_required": auth.required()}


@core_router.get("/auth")
def auth_status(request: Request):
    return {"required": auth.required(), "ok": auth.is_authorized(request)}


@core_router.post("/login")
def login(body: LoginRequest, request: Request):
    if not auth.required():
        return {"ok": True}
    if not auth.check_token(body.token.strip()):
        raise HTTPException(401, "That access token isn't right")
    response = JSONResponse({"ok": True})
    response.set_cookie(**auth.cookie_kwargs(request))
    return response


@core_router.post("/logout")
def logout():
    response = JSONResponse({"ok": True})
    response.delete_cookie(auth.COOKIE, path="/")
    return response


@core_router.post("/shutdown", status_code=202)
def shutdown():
    """Quit from the web app (Settings → App). The Mac app quits itself instead, through its bridge."""
    threading.Timer(0.3, lambda: os.kill(os.getpid(), signal.SIGTERM)).start()
    return {"ok": True}


@core_router.get("/changes")
def changes(since: int = 0):
    """Polled by the web app: a counter that moves whenever any module publishes an event."""
    return events.changes(since)


@core_router.get("/settings")
def get_settings():
    return settings.public()


@core_router.put("/settings")
def put_settings(changes: dict):
    try:
        out = settings.update(changes)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    events.publish("core.settings.changed", {"keys": list(changes)})
    return out


@core_router.get("/ai/providers")
async def ai_providers():
    return await run_in_threadpool(ai.providers)


@core_router.get("/ai/providers/{pid}/models")
async def ai_models(pid: str):
    if pid not in ai.PROVIDERS:
        raise HTTPException(404, "No such provider")
    try:
        return {"models": await run_in_threadpool(ai.list_models, pid)}
    except ai.AIError as e:
        raise HTTPException(502, str(e)) from e


@core_router.post("/ai/providers/{pid}/test")
async def ai_test(pid: str):
    if pid not in ai.PROVIDERS:
        raise HTTPException(404, "No such provider")
    try:
        return {"message": await run_in_threadpool(ai.test, pid)}
    except ai.AIError as e:
        raise HTTPException(502, str(e)) from e


@core_router.get("/search")
def search_all(q: str = "", limit: int = 8):
    return search.search(q, limit)


@core_router.get("/links")
def get_links(ref: str):
    return links.linked(ref)


@core_router.post("/links", status_code=201)
def add_link(body: LinkBody):
    for r in (body.from_ref, body.to_ref):
        if not module.describe(r):
            raise HTTPException(404, f"Nothing called {r}")
    links.add(body.from_ref, body.to_ref, body.kind)
    return {"ok": True}


@core_router.delete("/links", status_code=204)
def delete_link(from_ref: str, to_ref: str, kind: str | None = None):
    links.remove(from_ref, to_ref, kind)


@core_router.post("/jobs/{job_id}/go", status_code=202)
def job_go(job_id: str, body: JobGo):
    jobs.go(job_id, force=body.force)
    return {"ok": True}


@core_router.post("/jobs/{job_id}/retry", status_code=202)
def job_retry(job_id: str):
    jobs.retry(job_id)
    return {"ok": True}


app = create_app()
