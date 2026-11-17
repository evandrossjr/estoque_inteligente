import pytest

from app.config import normalize_ollama_host


@pytest.mark.parametrize(
    "entrada, esperado",
    [
        (None, "http://127.0.0.1:11434"),
        ("", "http://127.0.0.1:11434"),
        ("http://localhost:11434", "http://127.0.0.1:11434"),  # evita o IPv6 do "localhost" no Windows
        ("0.0.0.0:11434", "http://127.0.0.1:11434"),  # valor usado pelo próprio Ollama, sem http://
        ("127.0.0.1", "http://127.0.0.1:11434"),  # sem porta
        ("http://[::]:11434", "http://127.0.0.1:11434"),
        ("http://192.168.0.10:11434", "http://192.168.0.10:11434"),  # host remoto é mantido
        ("https://ollama.exemplo.com:8443", "https://ollama.exemplo.com:8443"),
        ("http://host:porta-invalida", "http://127.0.0.1:11434"),
    ],
)
def test_normalize_ollama_host(entrada, esperado):
    assert normalize_ollama_host(entrada) == esperado
