"""Ponto de entrada da API: uvicorn app.main:app --reload"""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .database import init_db
from .exceptions import DomainError
from .routers import assistant, products, reports

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Assistente de Estoque Inteligente",
    description="API de gestão de estoque com relatórios em Pandas e assistente de IA em linguagem natural.",
    version="1.0.0",
    lifespan=lifespan,
)


@app.exception_handler(DomainError)
async def domain_error_handler(request: Request, exc: DomainError):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


app.include_router(products.router)
app.include_router(reports.router)
app.include_router(assistant.router)
app.mount("/app", StaticFiles(directory=STATIC_DIR, html=True), name="app")


@app.get("/", include_in_schema=False)
def raiz():
    return RedirectResponse("/app/")


@app.get("/health", tags=["Sistema"])
def health():
    return {"status": "ok"}
