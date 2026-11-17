import httpx
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..ai.assistant import Assistant
from ..config import get_settings
from ..database import get_db
from ..schemas import AskRequest, AskResponse

router = APIRouter(prefix="/assistant", tags=["Assistente IA"])


def get_assistant() -> Assistant:
    return Assistant()


@router.post("/ask", response_model=AskResponse)
def perguntar(body: AskRequest, db: Session = Depends(get_db), assistant: Assistant = Depends(get_assistant)):
    """Pergunte em linguagem natural, ex.: 'Quais produtos estão com estoque baixo?'"""
    return assistant.ask(db, body.pergunta)


@router.get("/status")
def status():
    """Diagnóstico: qual motor o assistente vai usar e se o Ollama está acessível. Não expõe a chave."""
    s = get_settings()
    efetivo = Assistant(s).provider
    info: dict = {
        "provedor_configurado": s.llm_provider,
        "provedor_efetivo": efetivo,
        "anthropic_chave_definida": bool(s.anthropic_api_key),
        "anthropic_modelo": s.anthropic_model,
        "ollama_host": s.ollama_host,
        "ollama_modelo": s.ollama_model,
        "escrita_pela_ia": s.ai_allow_writes,
    }
    if efetivo == "ollama":
        try:
            r = httpx.get(f"{s.ollama_host.rstrip('/')}/api/tags", timeout=3)
            r.raise_for_status()
            instalados = [m["name"] for m in r.json().get("models", [])]
            info["ollama"] = {
                "acessivel": True,
                "modelos_instalados": instalados,
                "modelo_encontrado": s.ollama_model in instalados or f"{s.ollama_model}:latest" in instalados,
            }
        except Exception as exc:
            info["ollama"] = {"acessivel": False, "erro": type(exc).__name__}
    return info
