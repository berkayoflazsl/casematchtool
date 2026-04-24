from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.db import close_pool, get_pool
from app.schemas import SearchRequest, SearchResponse
from app.services import ingestion as inj
from app.services import search as searchsvc


@asynccontextmanager
async def lifespan(_: FastAPI):
    await get_pool()
    yield
    await close_pool()


app = FastAPI(title="CaseMatch-style MVP (UK FCL + pgvector)", lifespan=lifespan)
_static = Path(__file__).resolve().parent / "static"
if _static.is_dir():
    app.mount("/static", StaticFiles(directory=str(_static)), name="static")


@app.get("/health")
async def health() -> dict:
    s = get_settings()
    p = await get_pool()
    async with p.acquire() as c:
        n = await c.fetchval("SELECT count(*)::int FROM cases")
        nc = await c.fetchval("SELECT count(*)::int FROM case_chunks")
    return {
        "ok": True,
        "cases": n,
        "case_chunks": nc,
        "database_url_host": s.database_url.split("@")[-1] if "@" in s.database_url else "",
    }


@app.post("/v1/search", response_model=SearchResponse)
async def v1_search(req: Request, body: SearchRequest) -> SearchResponse:
    pool = await get_pool()
    ip = req.client.host if req.client else None
    return await searchsvc.run_search(pool, body, client_ip=ip)


@app.get("/")
async def index():
    p = _static / "index.html"
    if p.is_file():
        return FileResponse(p, media_type="text/html; charset=utf-8")
    return HTMLResponse(
        "<p>App running. <a href='/docs'>OpenAPI</a> · <a href='/health'>Health</a></p>"
    )
