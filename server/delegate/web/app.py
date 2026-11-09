from __future__ import annotations

import logging
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException
from starlette.middleware.sessions import SessionMiddleware

from .. import billing
from ..config import ensure_data_dirs, get_settings
from ..db import init_db, new_session
from . import routes_admin, routes_api, routes_auth, routes_console, routes_pages
from .deps import LoginRequired, current_user, render

log = logging.getLogger("delegate.web")


def _console_dist() -> Path | None:
    candidates = [
        Path(os.environ["DELEGATE_CONSOLE_DIST"]) if os.environ.get("DELEGATE_CONSOLE_DIST") else None,
        Path(__file__).resolve().parents[3] / "web" / "dist",
        Path("/app/web/dist"),
    ]
    for path in candidates:
        if path is not None and (path / "index.html").is_file():
            return path
    return None


def _serve_console(app: FastAPI, dist: Path) -> None:
    """Serve the built console, including paths the SPA does not map to files."""
    root = dist.resolve()

    @app.get("/app", include_in_schema=False)
    @app.get("/app/{rest:path}", include_in_schema=False)
    def console_spa(rest: str = ""):
        if rest:
            candidate = (root / rest).resolve()
            if candidate.is_file() and (candidate == root or root in candidate.parents):
                return FileResponse(candidate)
        return FileResponse(root / "index.html")


def _bootstrap_sidecar() -> None:
    try:
        billing.bootstrap()
        log.info("new-api sidecar ready")
    except Exception as exc:  # noqa: BLE001 - the site works (read-only) without the sidecar
        log.error("new-api bootstrap failed (will retry on demand): %s", exc)


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_data_dirs()
    init_db()
    threading.Thread(target=_bootstrap_sidecar, daemon=True).start()
    yield


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title="Delegate", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url="/api/openapi.json")
    app.add_middleware(
        SessionMiddleware,
        secret_key=s.secret_key,
        session_cookie="delegate_session",
        max_age=s.session_max_age,
        same_site="lax",
        https_only=s.cookie_secure,
    )
    app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
    app.include_router(routes_api.router)
    app.include_router(routes_console.router)
    app.include_router(routes_auth.router)
    app.include_router(routes_pages.router)
    app.include_router(routes_admin.router)
    console_dist = _console_dist()
    if console_dist is not None:
        _serve_console(app, console_dist)

    @app.get("/healthz", include_in_schema=False)
    def healthz():
        return {"ok": True}

    @app.exception_handler(LoginRequired)
    async def _login_required(request: Request, _exc: LoginRequired):
        return RedirectResponse(f"/login?next={request.url.path}", status_code=303)

    @app.exception_handler(billing.BillingError)
    async def _billing_error(request: Request, exc: billing.BillingError):
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": str(exc)}, status_code=exc.status_code)
        return render(request, "error.html", status_code=exc.status_code, message=str(exc))

    @app.exception_handler(HTTPException)
    async def _http_error(request: Request, exc: HTTPException):
        if request.url.path.startswith("/api/") or request.headers.get("accept", "").startswith("application/json"):
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)
        user = None
        if "session" in request.scope:
            with new_session() as db:
                user = current_user(request, db)
        return render(request, "error.html", user, status_code=exc.status_code, message=str(exc.detail))

    return app


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    uvicorn.run(
        create_app(),
        host=os.environ.get("DELEGATE_HOST", "0.0.0.0"),
        port=int(os.environ.get("DELEGATE_PORT", "8000")),
        proxy_headers=True,
        forwarded_allow_ips="*",
    )


if __name__ == "__main__":
    main()
