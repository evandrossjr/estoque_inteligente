from .conftest import novo_produto


def test_criar_produto_normaliza_sku_e_registra_estoque_inicial(client):
    r = novo_produto(client, sku=" tst-001 ")
    assert r.status_code == 201
    dados = r.json()
    assert dados["sku"] == "TST-001"
    assert dados["quantidade"] == 5

    historico = client.get(f"/products/{dados['id']}/movements").json()
    assert len(historico) == 1
    assert historico[0]["tipo"] == "entrada" and historico[0]["motivo"] == "Estoque inicial"


def test_sku_duplicado_retorna_409(client):
    novo_produto(client)
    r = novo_produto(client, sku="tst-001")
    assert r.status_code == 409


def test_validacoes_de_entrada(client):
    assert novo_produto(client, preco_custo=-1).status_code == 422
    assert novo_produto(client, quantidade=-3).status_code == 422
    assert novo_produto(client, nome="   ").status_code == 422
    # regra de negócio: venda abaixo do custo
    r = novo_produto(client, preco_custo=50, preco_venda=10)
    assert r.status_code == 422


def test_listar_com_filtros(client, catalogo):
    assert len(client.get("/products").json()) == 4
    assert len(client.get("/products", params={"categoria": "papelaria"}).json()) == 2
    assert [p["sku"] for p in client.get("/products", params={"busca": "mouse"}).json()] == ["A-1"]
    baixos = {p["sku"] for p in client.get("/products", params={"baixo_estoque": True}).json()}
    assert baixos == {"A-1", "B-1"}


def test_obter_inexistente_retorna_404(client):
    r = client.get("/products/999")
    assert r.status_code == 404
    assert "não encontrado" in r.json()["detail"]


def test_atualizar_parcialmente(client):
    pid = novo_produto(client).json()["id"]
    r = client.put(f"/products/{pid}", json={"nome": "Novo Nome", "estoque_minimo": 3})
    assert r.status_code == 200
    assert r.json()["nome"] == "Novo Nome" and r.json()["estoque_minimo"] == 3
    assert r.json()["quantidade"] == 5  # quantidade só muda por movimentação


def test_atualizar_preco_abaixo_do_custo_e_rejeitado(client):
    pid = novo_produto(client).json()["id"]
    r = client.put(f"/products/{pid}", json={"preco_venda": 1})
    assert r.status_code == 422
    assert client.get(f"/products/{pid}").json()["preco_venda"] == 20.0  # nada foi gravado


def test_desativar_preserva_historico_e_esconde_da_lista(client):
    pid = novo_produto(client).json()["id"]
    assert client.delete(f"/products/{pid}").status_code == 204
    assert client.get("/products").json() == []
    assert len(client.get("/products", params={"incluir_inativos": True}).json()) == 1
    assert len(client.get(f"/products/{pid}/movements").json()) == 1
