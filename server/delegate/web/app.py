from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException
from starlette.middleware.sessions import SessionMiddleware

from ..config import get_settings
from ..db import init_db, new_session
from . import routes_admin, routes_api, routes_auth, routes_pages
from .deps import LoginRequired, current_user, render


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title="Delegate", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url="/api/openapi.json")
    app.add_middleware(SessionMiddleware, secret_key=s.secret_key, session_cookie="delegate_session",
                       max_age=s.session_max_age, same_site="lax", https_only=s.cookie_secure)
    app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
    app.include_router(routes_api.router)
    app.include_router(routes_auth.router)
    app.include_router(routes_pages.router)
    app.include_router(routes_admin.router)

    @app.get("/healthz", include_in_schema=False)
    def healthz():
        return {"ok": True}

    @app.exception_handler(LoginRequired)
    async def _login_required(request: Request, _exc: LoginRequired):
        return RedirectResponse(f"/login?next={request.url.path}", status_code=303)

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
    uvicorn.run(create_app(), host=os.environ.get("DELEGATE_HOST", "0.0.0.0"),
                port=int(os.environ.get("DELEGATE_PORT", "8000")), proxy_headers=True, forwarded_allow_ips="*")


if __name__ == "__main__":
    main()
