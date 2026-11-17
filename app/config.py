"""Configurações lidas de variáveis de ambiente (ou do arquivo .env)."""
import os
from dataclasses import dataclass
from urllib.parse import urlsplit

from dotenv import load_dotenv

load_dotenv()


def normalize_ollama_host(raw: str | None) -> str:
    """Devolve uma URL utilizável a partir de OLLAMA_HOST.

    O próprio Ollama também lê OLLAMA_HOST (ex.: "0.0.0.0:11434", sem http://) para decidir onde
    escutar, e no Windows "localhost" pode resolver para IPv6 enquanto o Ollama escuta em IPv4.
    Por isso: adiciona o esquema e a porta que faltam e troca endereços de loopback/curinga por 127.0.0.1.
    """
    raw = (raw or "").strip() or "127.0.0.1:11434"
    if "://" not in raw:
        raw = "http://" + raw
    try:
        parts = urlsplit(raw)
        host = parts.hostname or "127.0.0.1"
        port = parts.port or 11434
    except ValueError:
        return "http://127.0.0.1:11434"
    if host in ("0.0.0.0", "localhost", "::", "::1"):
        host = "127.0.0.1"
    if ":" in host:  # IPv6 literal precisa de colchetes na URL
        host = f"[{host}]"
    return f"{parts.scheme}://{host}:{port}"


@dataclass(frozen=True)
class Settings:
    database_url: str
    llm_provider: str  # auto | anthropic | ollama | local
    anthropic_api_key: str
    anthropic_model: str
    ollama_host: str
    ollama_model: str
    ai_allow_writes: bool


def get_settings() -> Settings:
    """Lê as variáveis a cada chamada, o que facilita trocar valores nos testes."""
    return Settings(
        database_url=os.getenv("DATABASE_URL", "sqlite:///./estoque.db"),
        llm_provider=os.getenv("LLM_PROVIDER", "auto").strip().lower(),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", "").strip(),
        anthropic_model=os.getenv("ANTHROPIC_MODEL", "claude-haiku-5-5"),
        ollama_host=normalize_ollama_host(os.getenv("OLLAMA_HOST")),
        ollama_model=os.getenv("OLLAMA_MODEL", "qwen2.5:3b").strip(),
        ai_allow_writes=os.getenv("AI_ALLOW_WRITES", "false").strip().lower() == "true",
    )
