def saida(client, produtos, sku, qtd):
    pid = next(p["id"] for p in produtos if p["sku"] == sku)
    assert client.post(f"/products/{pid}/movements", json={"tipo": "saida", "quantidade": qtd}).status_code == 201


def test_relatorios_com_banco_vazio(client):
    assert client.get("/reports/summary").json()["total_produtos"] == 0
    for rota in ("low-stock", "by-category", "top-sellers", "no-movement", "abc"):
        assert client.get(f"/reports/{rota}").json() == []


def test_resumo(client, catalogo):
    r = client.get("/reports/summary").json()
    assert r["total_produtos"] == 4
    assert r["total_unidades"] == 143
    # 3*10 + 40*50 + 0*5 + 100*1
    assert r["valor_estoque_custo"] == 2130.0
    assert r["produtos_estoque_baixo"] == 2
    assert r["produtos_zerados"] == 1


def test_estoque_baixo_ordenado_pelo_deficit(client, catalogo):
    itens = client.get("/reports/low-stock").json()
    assert [i["sku"] for i in itens] == ["A-1", "B-1"]  # déficit 7 e 5
    assert itens[0]["sugestao_reposicao"] == 17  # 2*10 - 3


def test_por_categoria(client, catalogo):
    cats = {c["categoria"]: c for c in client.get("/reports/by-category").json()}
    assert cats["Eletrônicos"]["unidades"] == 43
    assert cats["Eletrônicos"]["valor_custo"] == 2030.0
    assert cats["Papelaria"]["produtos"] == 2


def test_mais_vendidos_e_sem_giro(client, catalogo):
    saida(client, catalogo, "A-2", 10)
    saida(client, catalogo, "B-2", 30)
    saida(client, catalogo, "B-2", 5)

    top = client.get("/reports/top-sellers", params={"limite": 2}).json()
    assert [(t["sku"], t["unidades_saidas"]) for t in top] == [("B-2", 35), ("A-2", 10)]

    parados = {p["sku"] for p in client.get("/reports/no-movement").json()}
    assert parados == {"A-1"}  # B-1 está zerado, então não conta; A-2 e B-2 tiveram saída


def test_analise_margem_classifica_os_quatro_grupos(client, catalogo):
    saida(client, catalogo, "A-1", 3)   # Mouse: margem 50% (abaixo da mediana), vende
    saida(client, catalogo, "B-2", 30)  # Caneta: margem 66,7% (acima), vende muito
    r = client.get("/reports/margin").json()
    grupo = {i["sku"]: g for g, itens in r["grupos"].items() for i in itens}
    assert grupo == {
        "B-2": "manter",
        "A-1": "testar_aumento",   # vende bem com margem baixa
        "B-1": "testar_promocao",  # margem alta (58%) mas zero vendas
        "A-2": "revisar",          # margem baixa (44%) e zero vendas
    }
    assert r["lucro_bruto_periodo"] == 3 * 10 + 30 * 2  # unidades x (venda - custo)
    assert "heurística" in r["observacao"].lower()


def test_analise_margem_banco_vazio(client):
    assert client.get("/reports/margin").json()["total_produtos"] == 0


def test_curva_abc(client, catalogo):
    abc = client.get("/reports/abc").json()
    assert abc[0]["sku"] == "A-2" and abc[0]["classe"] == "A"
    assert {i["sku"] for i in abc} == {"A-1", "A-2", "B-2"}  # B-1 zerado fica de fora
    assert abs(sum(i["percentual"] for i in abc) - 100) < 0.1


def test_movimentacao_periodo(client, catalogo):
    saida(client, catalogo, "A-2", 7)
    r = client.get("/reports/movements", params={"dias": 7}).json()
    assert r["saidas"] == 7
    assert r["entradas"] == 143  # estoques iniciais


def test_parametros_invalidos_nos_relatorios(client):
    assert client.get("/reports/top-sellers", params={"dias": 0}).status_code == 422
    assert client.get("/reports/no-movement", params={"dias": 9999}).status_code == 422


def test_exportar_csv(client, catalogo):
    r = client.get("/reports/export.csv")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    linhas = r.text.strip().splitlines()
    assert linhas[0].startswith("id,sku,nome")
    assert len(linhas) == 5
