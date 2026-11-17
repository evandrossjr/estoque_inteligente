import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app import models  # noqa: F401
from app.ai.assistant import Assistant
from app.config import get_settings
from app.database import Base, get_db, make_engine
from app.main import app
from app.routers.assistant import get_assistant


@pytest.fixture()
def db_session():
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = Session()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture()
def client(db_session):
    def _db():
        yield db_session

    app.dependency_overrides[get_db] = _db
    # força o modo local: os testes não dependem de rede nem de chave de API
    app.dependency_overrides[get_assistant] = lambda: Assistant(get_settings(), provider="local")
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def novo_produto(client, **extra):
    corpo = {
        "sku": "TST-001", "nome": "Produto Teste", "categoria": "Testes",
        "preco_custo": 10.0, "preco_venda": 20.0, "quantidade": 5, "estoque_minimo": 10,
    }
    corpo.update(extra)
    return client.post("/products", json=corpo)


@pytest.fixture()
def catalogo(client):
    """Quatro produtos: um com estoque baixo, um zerado e dois saudáveis."""
    itens = [
        dict(sku="A-1", nome="Mouse", categoria="Eletrônicos", preco_custo=10, preco_venda=20, quantidade=3, estoque_minimo=10),
        dict(sku="A-2", nome="Teclado", categoria="Eletrônicos", preco_custo=50, preco_venda=90, quantidade=40, estoque_minimo=10),
        dict(sku="B-1", nome="Caderno", categoria="Papelaria", preco_custo=5, preco_venda=12, quantidade=0, estoque_minimo=5),
        dict(sku="B-2", nome="Caneta", categoria="Papelaria", preco_custo=1, preco_venda=3, quantidade=100, estoque_minimo=20),
    ]
    return [client.post("/products", json=i).json() for i in itens]
