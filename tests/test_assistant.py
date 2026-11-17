import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.ai.assistant import Assistant
from app.ai.tools import available_tools, run_tool
from app.config import get_settings


def perguntar(client, texto):
    return client.post("/assistant/ask", json={"pergunta": texto})


# ---------- modo local (sem LLM) via API ----------
def test_pergunta_estoque_baixo(client, catalogo):
    r = perguntar(client, "Quais produtos estão com estoque baixo?").json()
    assert r["modo"] == "local"
    assert r["ferramentas_usadas"] == ["listar_estoque_baixo"]
    assert "A-1" in r["resposta"] and "B-1" in r["resposta"]
    assert "A-2" not in r["resposta"]


def test_pergunta_resumo_e_categoria(client, catalogo):
    r = perguntar(client, "me dá um resumo do estoque").json()
    assert "4 produtos" in r["resposta"] and "2.130,00" in r["resposta"]
    r = perguntar(client, "estoque por categoria").json()
    assert "Eletrônicos" in r["resposta"] and "Papelaria" in r["resposta"]


def test_pergunta_por_sku_e_por_nome(client, catalogo):
    r = perguntar(client, "quanto tem do A-2?").json()
    assert r["ferramentas_usadas"] == ["consultar_produto"]
    assert "40 un." in r["resposta"]

    r = perguntar(client, "tem caneta?").json()
    assert r["ferramentas_usadas"] == ["buscar_produtos"]
    assert "B-2" in r["resposta"]


def test_pergunta_nao_entendida_orienta_o_usuario(client, catalogo):
    r = perguntar(client, "qual a capital da França?").json()
    assert r["ferramentas_usadas"] == []
    assert "Não entendi" in r["resposta"]


def test_pergunta_com_dias(client, catalogo):
    r = perguntar(client, "produtos parados há 15 dias").json()
    assert "15 dias" in r["resposta"]


def test_pergunta_mais_e_menos_vendido(client, catalogo):
    def saida(sku_id, qtd):
        client.post(f"/products/{sku_id}/movements", json={"tipo": "saida", "quantidade": qtd})

    saida(catalogo[1]["id"], 10)  # A-2 Teclado
    saida(catalogo[3]["id"], 30)  # B-2 Caneta
    saida(catalogo[0]["id"], 1)   # A-1 Mouse

    r = perguntar(client, "qual o produto com mais e com menos vendas?").json()
    assert r["ferramentas_usadas"] == ["ranking_vendas"]
    mais, menos = r["resposta"].split("Menos vendidos")
    assert "B-2" in mais and "A-2" not in mais  # singular: só 1 item
    assert "B-1" in menos  # Caderno: zero vendas, entra como o menos vendido

    r = perguntar(client, "quais os 3 produtos menos vendidos?").json()
    assert r["ferramentas_usadas"] == ["ranking_vendas"]
    assert "Menos vendidos" in r["resposta"]
    menos = r["resposta"].split("Menos vendidos")[1]
    assert menos.count("- ") == 3  # respeita o "3 produtos"


def test_ranking_vendas_inclui_zero_e_endpoint(client, catalogo):
    client.post(f"/products/{catalogo[3]['id']}/movements", json={"tipo": "saida", "quantidade": 5})
    r = client.get("/reports/sales-ranking", params={"limite": 2}).json()
    assert [p["sku"] for p in r["mais"]] == ["B-2"]
    assert [p["unidades_saidas"] for p in r["menos"]] == [0, 0]
    assert r["sem_venda"] == 3


def test_pergunta_sobre_preco_e_custo_vai_para_margem_e_nao_para_vendas(client, catalogo):
    q = "me ajude a encontrar o melhor equilíbrio entre preço de venda e preço de custo"
    r = perguntar(client, q).json()
    assert r["ferramentas_usadas"] == ["analise_margem"]
    assert "Margem x vendas" in r["resposta"]
    # com SKU, a pergunta continua sendo uma consulta ao produto
    r = perguntar(client, "qual o preço de venda do A-2?").json()
    assert r["ferramentas_usadas"] == ["consultar_produto"]


def test_pergunta_invalida_retorna_422(client):
    assert perguntar(client, "").status_code == 422
    assert perguntar(client, "ab").status_code == 422
    assert perguntar(client, "x" * 501).status_code == 422


# ---------- segurança das ferramentas ----------
def test_escrita_desligada_por_padrao(db_session):
    assert "registrar_movimentacao" not in available_tools(allow_writes=False)
    r = run_tool(db_session, "registrar_movimentacao", {"sku": "A-1", "tipo": "saida", "quantidade": 1}, False)
    assert "não disponível" in r["erro"]


def test_ferramenta_desconhecida_e_argumentos_invalidos(db_session):
    assert "erro" in run_tool(db_session, "drop_table", {}, False)
    assert "erro" in run_tool(db_session, "mais_vendidos", {"dias": "abc"}, False)
    assert "erro" in run_tool(db_session, "mais_vendidos", {"dias": 100000}, False)
    assert "erro" in run_tool(db_session, "buscar_produtos", {"termo": "  "}, False)


def test_escrita_ligada_valida_regras_de_negocio(client, catalogo, db_session):
    r = run_tool(db_session, "registrar_movimentacao", {"sku": "a-1", "tipo": "saida", "quantidade": 2}, True)
    assert r["ok"] and r["saldo_apos"] == 1
    r = run_tool(db_session, "registrar_movimentacao", {"sku": "A-1", "tipo": "saida", "quantidade": 50}, True)
    assert "insuficiente" in r["erro"].lower()
    r = run_tool(db_session, "registrar_movimentacao", {"sku": "A-1", "tipo": "doar", "quantidade": 1}, True)
    assert "erro" in r


# ---------- modo LLM com cliente falso (testa o laço de tool use) ----------
def _resp(stop, *blocos):
    return SimpleNamespace(stop_reason=stop, content=list(blocos))


class FakeAnthropic:
    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.chamadas = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.chamadas.append(kwargs)
        return self.respostas.pop(0)


def test_laco_de_tool_use_do_claude(client, catalogo, db_session):
    fake = FakeAnthropic([
        _resp("tool_use", SimpleNamespace(type="tool_use", id="t1", name="listar_estoque_baixo", input={})),
        _resp("end_turn", SimpleNamespace(type="text", text="Repor Mouse (A-1) e Caderno (B-1).")),
    ])
    settings = replace(get_settings(), anthropic_api_key="x", llm_provider="anthropic")
    r = Assistant(settings, client=fake).ask(db_session, "o que repor?")

    assert r["modo"] == "anthropic" and r["aviso"] is None
    assert r["ferramentas_usadas"] == ["listar_estoque_baixo"]
    assert "Mouse" in r["resposta"]

    # o resultado da ferramenta voltou para o modelo na 2ª chamada
    ultima = fake.chamadas[1]["messages"][-1]
    resultado = json.loads(ultima["content"][0]["content"])
    assert resultado["total"] == 2
    # a ferramenta de escrita não foi oferecida ao modelo
    assert "registrar_movimentacao" not in [t["name"] for t in fake.chamadas[0]["tools"]]
    assert "estoque" in fake.chamadas[0]["system"].lower()


def test_falha_do_llm_cai_para_modo_local_com_aviso(client, catalogo, db_session):
    class Quebrado:
        messages = SimpleNamespace(create=lambda **kw: (_ for _ in ()).throw(ConnectionError("sem rede")))

    settings = replace(get_settings(), anthropic_api_key="x", llm_provider="anthropic")
    r = Assistant(settings, client=Quebrado()).ask(db_session, "resumo do estoque")
    assert r["modo"] == "local"
    assert "ConnectionError" in r["aviso"]
    assert "4 produtos" in r["resposta"]


def test_modo_auto_sempre_tenta_o_llm_primeiro():
    base = replace(get_settings(), llm_provider="auto")
    assert Assistant(replace(base, anthropic_api_key="abc")).provider == "anthropic"
    # sem chave da Anthropic, o auto usa o Ollama (nunca pula direto para o modo local)
    assert Assistant(replace(base, anthropic_api_key="")).provider == "ollama"
    # valor desconhecido também cai no auto; só "local" explícito desliga o LLM
    assert Assistant(replace(base, llm_provider="qualquer", anthropic_api_key="")).provider == "ollama"
    assert Assistant(replace(base, llm_provider="local")).provider == "local"


def test_ollama_fora_do_ar_responde_pelo_local_com_aviso(client, catalogo, db_session, monkeypatch):
    def fora(*a, **k):
        raise ConnectionError("ollama desligado")

    monkeypatch.setattr("app.ai.assistant.httpx.post", fora)
    settings = replace(get_settings(), llm_provider="auto", anthropic_api_key="")
    r = Assistant(settings).ask(db_session, "resumo do estoque")
    assert r["modo"] == "local"  # reserva
    assert "ConnectionError" in r["aviso"]  # e o motivo fica visível


def test_status_mostra_provedor_e_checa_ollama(client, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen2.5:3b")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "segredo")

    class Resp:
        def raise_for_status(self): pass
        def json(self): return {"models": [{"name": "qwen2.5:3b"}]}

    monkeypatch.setattr("app.routers.assistant.httpx.get", lambda *a, **k: Resp())
    r = client.get("/assistant/status").json()
    assert r["provedor_efetivo"] == "ollama"
    assert r["ollama"] == {"acessivel": True, "modelos_instalados": ["qwen2.5:3b"], "modelo_encontrado": True}
    assert "segredo" not in str(r)  # a chave nunca é exposta

    def fora(*a, **k):
        raise ConnectionError("desligado")

    monkeypatch.setattr("app.routers.assistant.httpx.get", fora)
    assert client.get("/assistant/status").json()["ollama"] == {"acessivel": False, "erro": "ConnectionError"}


def test_modelo_que_nunca_para_de_chamar_ferramentas_e_interrompido(client, catalogo, db_session):
    loop = lambda: _resp("tool_use", SimpleNamespace(type="tool_use", id="t", name="resumo_estoque", input={}))
    fake = FakeAnthropic([loop() for _ in range(10)])
    settings = replace(get_settings(), anthropic_api_key="x", llm_provider="anthropic")
    r = Assistant(settings, client=fake).ask(db_session, "resumo")
    assert r["modo"] == "local" and "limite de passos" in r["aviso"] or "AssistantError" in r["aviso"]
    assert len(fake.chamadas) == 5
