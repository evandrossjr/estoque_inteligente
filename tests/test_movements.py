from .conftest import novo_produto


def mov(client, pid, tipo, quantidade, motivo=None):
    return client.post(f"/products/{pid}/movements", json={"tipo": tipo, "quantidade": quantidade, "motivo": motivo})


def saldo(client, pid):
    return client.get(f"/products/{pid}").json()["quantidade"]


def test_entrada_e_saida_atualizam_saldo(client):
    pid = novo_produto(client, quantidade=10).json()["id"]
    assert mov(client, pid, "entrada", 5).json()["saldo_apos"] == 15
    assert mov(client, pid, "saida", 4, "Venda").json()["saldo_apos"] == 11
    assert saldo(client, pid) == 11


def test_saida_maior_que_saldo_e_bloqueada(client):
    pid = novo_produto(client, quantidade=3).json()["id"]
    r = mov(client, pid, "saida", 4)
    assert r.status_code == 422
    assert "insuficiente" in r.json()["detail"].lower()
    assert saldo(client, pid) == 3  # saldo intacto


def test_ajuste_define_saldo_absoluto_inclusive_zero(client):
    pid = novo_produto(client, quantidade=10).json()["id"]
    assert mov(client, pid, "ajuste", 7, "Inventário").json()["saldo_apos"] == 7
    assert mov(client, pid, "ajuste", 0).status_code == 201
    assert saldo(client, pid) == 0


def test_quantidade_invalida(client):
    pid = novo_produto(client).json()["id"]
    assert mov(client, pid, "saida", 0).status_code == 422
    assert mov(client, pid, "entrada", -2).status_code == 422
    assert mov(client, pid, "devolucao", 1).status_code == 422


def test_movimentar_produto_inexistente_ou_inativo(client):
    assert mov(client, 999, "entrada", 1).status_code == 404
    pid = novo_produto(client).json()["id"]
    client.delete(f"/products/{pid}")
    assert mov(client, pid, "entrada", 1).status_code == 422


def test_historico_vem_do_mais_recente_para_o_mais_antigo(client):
    pid = novo_produto(client, quantidade=10).json()["id"]
    mov(client, pid, "saida", 1)
    mov(client, pid, "saida", 2)
    tipos = [(m["tipo"], m["quantidade"]) for m in client.get(f"/products/{pid}/movements").json()]
    assert tipos == [("saida", 2), ("saida", 1), ("entrada", 10)]
