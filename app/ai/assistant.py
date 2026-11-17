"""Assistente de estoque em linguagem natural.

Três modos, todos usando as MESMAS ferramentas de app/ai/tools.py:
  - anthropic: Claude (API) com tool use
  - ollama:    modelo local via Ollama (precisa de um modelo com suporte a tools, ex.: llama3.1)
  - local:     interpretador por regras, sem LLM (funciona offline e nos testes)

Se o LLM falhar (sem rede, chave inválida...), o assistente cai para o modo local
e devolve um aviso, em vez de quebrar a API.
"""
import json
import re
import unicodedata
from typing import Any

import httpx
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from .tools import anthropic_specs, ollama_specs, run_tool

MAX_STEPS = 5

SYSTEM_PROMPT = """\
Você é o assistente de estoque de uma empresa. Responda sempre em português do Brasil.

REGRAS
1. Use as ferramentas para obter qualquer dado de estoque. Nunca invente produtos, SKUs, quantidades ou valores.
2. Se a ferramenta não trouxer o dado pedido, diga isso claramente em vez de supor.
3. Operações que alteram o estoque (entrada, saída, ajuste) só podem ser feitas quando o usuário pedir de forma explícita e informar SKU, tipo e quantidade. Na dúvida, pergunte.
4. Seja direto: comece pela resposta e, se houver vários itens, use lista curta (no máximo 10 itens).
5. Valores monetários em reais (R$). Cite o SKU ao mencionar um produto.
6. Responda apenas sobre estoque. Para outros assuntos, explique educadamente que não pode ajudar.
7. Perguntas sobre preço, margem ou lucro: use analise_margem e deixe claro que as sugestões são hipóteses a testar, pois não há histórico de preços para medir o efeito de uma mudança.
"""


class AssistantError(Exception):
    pass


# ---------------------------------------------------------------- utilidades
def _json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def _norm(texto: str) -> str:
    """minúsculas e sem acentos, para casar palavras-chave."""
    sem_acento = "".join(c for c in unicodedata.normalize("NFD", texto.lower()) if unicodedata.category(c) != "Mn")
    return sem_acento


def _brl(valor: float) -> str:
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


# ---------------------------------------------------------------- formatação local
def _fmt_lista(titulo: str, linhas: list[str], vazio: str) -> str:
    if not linhas:
        return vazio
    return titulo + "\n" + "\n".join(f"- {l}" for l in linhas[:10])


def _formatar(ferramenta: str, r: dict) -> str:
    if "erro" in r:
        return r["erro"]
    if ferramenta == "listar_estoque_baixo":
        linhas = [
            f"{p['sku']} {p['nome']}: {p['quantidade']} un. (mínimo {p['estoque_minimo']}), repor ~{int(p['sugestao_reposicao'])}"
            for p in r["produtos"]
        ]
        return _fmt_lista(f"{r['total']} produto(s) com estoque baixo:", linhas, "Nenhum produto com estoque baixo.")
    if ferramenta == "resumo_estoque":
        return (
            f"Resumo do estoque: {r['total_produtos']} produtos ativos, {r['total_unidades']} unidades, "
            f"valor a custo {_brl(r['valor_estoque_custo'])} e a preço de venda {_brl(r['valor_estoque_venda'])}. "
            f"{r['produtos_estoque_baixo']} com estoque baixo e {r['produtos_zerados']} zerados."
        )
    if ferramenta == "estoque_por_categoria":
        linhas = [
            f"{c['categoria']}: {c['produtos']} produtos, {int(c['unidades'])} un., {_brl(c['valor_custo'])}"
            for c in r["categorias"]
        ]
        return _fmt_lista("Estoque por categoria:", linhas, "Não há produtos cadastrados.")
    if ferramenta == "mais_vendidos":
        linhas = [f"{p['sku']} {p['nome']}: {int(p['unidades_saidas'])} un." for p in r["produtos"]]
        return _fmt_lista(f"Mais vendidos nos últimos {r['dias']} dias:", linhas, f"Nenhuma saída nos últimos {r['dias']} dias.")
    if ferramenta == "analise_margem":
        if not r["total_produtos"]:
            return "Não há produtos cadastrados."
        titulos = {
            "manter": "Bom equilíbrio (margem e vendas acima da mediana), manter:",
            "testar_aumento": "Vendem bem, mas com margem baixa: teste um pequeno aumento de preço ou renegocie o custo:",
            "testar_promocao": "Margem alta, mas vendem pouco: teste um preço menor ou uma promoção:",
            "revisar": "Margem e vendas baixas: revise custo/preço ou considere descontinuar:",
        }
        partes = [
            f"Margem x vendas nos últimos {r['dias']} dias. Margem mediana {r['margem_mediana_pct']}%, "
            f"vendas mediana {r['vendas_mediana_un']} un., lucro bruto {_brl(r['lucro_bruto_periodo'])} "
            f"(margem realizada {r['margem_realizada_pct']}%)."
        ]
        for chave, titulo in titulos.items():
            itens = r["grupos"].get(chave)
            if itens:
                linhas = [f"{i['sku']} {i['nome']}: margem {i['margem_pct']:.0f}%, {i['unidades_vendidas']} un. vendidas" for i in itens]
                partes.append(_fmt_lista(titulo, linhas, ""))
        partes.append(r["observacao"])
        return "\n".join(partes)
    if ferramenta == "ranking_vendas":
        d = r["dias"]
        if not r["mais"] and not r["menos"]:
            return "Não há produtos cadastrados."
        partes = []
        if r["mais"]:
            linhas = [f"{p['sku']} {p['nome']}: {p['unidades_saidas']} un." for p in r["mais"]]
            partes.append(_fmt_lista(f"Mais vendidos nos últimos {d} dias:", linhas, ""))
        else:
            partes.append(f"Nenhum produto teve saída nos últimos {d} dias.")
        if r["menos"]:
            linhas = [f"{p['sku']} {p['nome']}: {p['unidades_saidas']} un." for p in r["menos"]]
            partes.append(_fmt_lista(f"Menos vendidos nos últimos {d} dias:", linhas, ""))
            if r["sem_venda"] > len(r["menos"]) and r["menos"][0]["unidades_saidas"] == 0:
                partes.append(f"({r['sem_venda']} produtos no total não tiveram nenhuma venda no período.)")
        return "\n".join(partes)
    if ferramenta == "produtos_sem_giro":
        linhas = [f"{p['sku']} {p['nome']}: {int(p['quantidade'])} un. ({_brl(p['valor_parado'])} parados)" for p in r["produtos"]]
        return _fmt_lista(
            f"{r['total']} produto(s) sem saída nos últimos {r['dias']} dias:", linhas,
            f"Todos os produtos com estoque tiveram saída nos últimos {r['dias']} dias.",
        )
    if ferramenta == "curva_abc":
        linhas = [f"[{i['classe']}] {i['sku']} {i['nome']}: {_brl(i['valor'])} ({i['percentual']:.1f}%)" for i in r["itens"]]
        return _fmt_lista("Curva ABC (por valor em estoque):", linhas, "Sem estoque valorizado para classificar.")
    if ferramenta == "consultar_produto":
        situacao = "ESTOQUE BAIXO" if r["estoque_baixo"] else "ok"
        return (
            f"{r['sku']} - {r['nome']} ({r['categoria']}): {r['quantidade']} un. em estoque "
            f"(mínimo {r['estoque_minimo']}, {situacao}). Custo {_brl(r['preco_custo'])}, venda {_brl(r['preco_venda'])}."
        )
    if ferramenta == "buscar_produtos":
        linhas = [f"{p['sku']} {p['nome']}: {p['quantidade']} un." for p in r["produtos"]]
        return _fmt_lista(f"Encontrei {r['total']} produto(s):", linhas, "Não encontrei produtos com esse termo.")
    if ferramenta == "movimentacao_periodo":
        return f"Nos últimos {r['dias']} dias: {r['entradas']} un. de entrada, {r['saidas']} un. de saída e {r['ajustes']} ajuste(s)."
    return _json(r)


STOPWORDS = {
    "qual", "quais", "quanto", "quantos", "tem", "temos", "estoque", "produto", "produtos", "item", "itens",
    "de", "do", "da", "dos", "das", "o", "a", "os", "as", "um", "uma", "no", "na", "em", "para", "por", "me",
    "mostre", "mostra", "liste", "listar", "buscar", "busque", "procure", "tenho", "esta", "estao", "sobre", "que",
    "e", "ha", "existe", "existem", "ver", "saldo", "disponivel", "unidades",
}


def interpretar_local(db: Session, pergunta: str, allow_writes: bool = False) -> tuple[str, list[str]]:
    """Mapeia a pergunta para uma ferramenta por palavras-chave (sem LLM)."""
    texto = _norm(pergunta)
    m = re.search(r"(\d+)\s*dias?", texto)
    dias = int(m.group(1)) if m else 30
    usadas: list[str] = []

    def chamar(nome: str, args: dict | None = None) -> str:
        usadas.append(nome)
        return _formatar(nome, run_tool(db, nome, args, allow_writes))

    tem_sku = re.search(r"\b[A-Za-z]+-\d+\b", pergunta)
    if not tem_sku and (
        any(k in texto for k in ("margem", "lucro", "markup", "precific", "equilibrio"))
        or ("preco" in texto and "custo" in texto)
    ):
        return chamar("analise_margem", {"dias": dias}), usadas
    if tem_sku:  # pergunta com SKU é sobre aquele produto
        return chamar("consultar_produto", {"sku": tem_sku.group(0)}), usadas
    if any(k in texto for k in ("baixo", "acabando", "repor", "reposic", "reabastec", "faltando", "zerad", "minimo")):
        return chamar("listar_estoque_baixo"), usadas
    if any(k in texto for k in ("sem giro", "parado", "encalhad", "nao vend", "sem saida", "sem movimento")):
        return chamar("produtos_sem_giro", {"dias": dias}), usadas
    if any(k in texto for k in ("vend", "mais sai", "menos sai", "maior saida", "menor saida", "giro", "top ")):
        # "o produto..." (singular) pede só 1 item; no plural, o top 5
        singular = bool(re.search(r"\b(o|um|qual)\s+(o\s+)?produto\b", texto))
        qtd = re.search(r"\b(\d+)\s+(produtos|itens)\b", texto)  # "os 3 produtos menos vendidos"
        limite = min(int(qtd.group(1)), 20) if qtd and int(qtd.group(1)) > 0 else (1 if singular else 5)
        args = {"dias": dias, "limite": limite}
        return chamar("ranking_vendas", args), usadas
    if "abc" in texto:
        return chamar("curva_abc"), usadas
    if "categoria" in texto:
        return chamar("estoque_por_categoria"), usadas
    if any(k in texto for k in ("movimenta", "entradas", "saidas")):
        return chamar("movimentacao_periodo", {"dias": dias}), usadas
    if any(k in texto for k in ("resumo", "total", "valor", "visao geral", "panorama", "quantos produtos")):
        return chamar("resumo_estoque"), usadas

    termos = [w for w in re.findall(r"[a-z0-9]+", texto) if w not in STOPWORDS and len(w) > 2]
    for termo in termos:
        resultado = run_tool(db, "buscar_produtos", {"termo": termo}, allow_writes)
        if resultado.get("total"):
            usadas.append("buscar_produtos")
            return _formatar("buscar_produtos", resultado), usadas
    return (
        "Não entendi a pergunta. Tente algo como: 'quais produtos estão com estoque baixo?', "
        "'resumo do estoque', 'mais vendidos nos últimos 30 dias', 'produtos parados' ou informe um SKU.",
        usadas,
    )


# ---------------------------------------------------------------- assistente
class Assistant:
    def __init__(self, settings: Settings | None = None, provider: str | None = None, client: Any = None):
        self.settings = settings or get_settings()
        self.provider = self._resolve_provider(provider or self.settings.llm_provider)
        self._client = client  # permite injetar um cliente falso nos testes

    def _resolve_provider(self, wanted: str) -> str:
        # O LLM é sempre a primeira tentativa. O modo local só é usado como reserva quando o LLM
        # falha, ou se for pedido explicitamente (LLM_PROVIDER=local, usado nos testes).
        if wanted == "local":
            return "local"
        if wanted in ("anthropic", "ollama"):
            return wanted
        return "anthropic" if self.settings.anthropic_api_key else "ollama"  # auto

    def ask(self, db: Session, pergunta: str) -> dict:
        allow = self.settings.ai_allow_writes
        aviso = None
        if self.provider != "local":
            try:
                if self.provider == "anthropic":
                    texto, usadas = self._ask_anthropic(db, pergunta, allow)
                else:
                    texto, usadas = self._ask_ollama(db, pergunta, allow)
                return {"resposta": texto, "ferramentas_usadas": usadas, "modo": self.provider, "aviso": None}
            except Exception as exc:  # rede, chave inválida, limite, resposta inesperada...
                aviso = f"LLM '{self.provider}' indisponível ({type(exc).__name__}); resposta gerada pelo modo local."
        texto, usadas = interpretar_local(db, pergunta, allow)
        return {"resposta": texto, "ferramentas_usadas": usadas, "modo": "local", "aviso": aviso}

    # --- Anthropic (tool use) ---
    def _ask_anthropic(self, db: Session, pergunta: str, allow: bool) -> tuple[str, list[str]]:
        client = self._client
        if client is None:
            import anthropic

            client = anthropic.Anthropic(api_key=self.settings.anthropic_api_key)
        tools = anthropic_specs(allow)
        messages: list[dict] = [{"role": "user", "content": pergunta}]
        usadas: list[str] = []

        for _ in range(MAX_STEPS):
            resp = client.messages.create(
                model=self.settings.anthropic_model,
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                tools=tools,
                messages=messages,
            )
            if resp.stop_reason != "tool_use":
                texto = "".join(b.text for b in resp.content if b.type == "text").strip()
                if not texto:
                    raise AssistantError("resposta vazia do modelo")
                return texto, usadas

            messages.append({"role": "assistant", "content": resp.content})
            resultados = []
            for bloco in resp.content:
                if bloco.type == "tool_use":
                    usadas.append(bloco.name)
                    saida = run_tool(db, bloco.name, bloco.input, allow)
                    resultados.append({"type": "tool_result", "tool_use_id": bloco.id, "content": _json(saida)})
            messages.append({"role": "user", "content": resultados})
        raise AssistantError("limite de passos excedido")

    # --- Ollama (modelo local) ---
    def _ask_ollama(self, db: Session, pergunta: str, allow: bool) -> tuple[str, list[str]]:
        url = f"{self.settings.ollama_host.rstrip('/')}/api/chat"
        tools = ollama_specs(allow)
        messages: list[dict] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": pergunta},
        ]
        usadas: list[str] = []

        for _ in range(MAX_STEPS):
            r = httpx.post(
                url,
                json={"model": self.settings.ollama_model, "messages": messages, "tools": tools, "stream": False},
                timeout=120,  # a 1ª chamada carrega o modelo na memória e pode demorar em CPU
            )
            r.raise_for_status()
            msg = r.json()["message"]
            chamadas = msg.get("tool_calls") or []
            if not chamadas:
                texto = (msg.get("content") or "").strip()
                if not texto:
                    raise AssistantError("resposta vazia do modelo")
                return texto, usadas

            messages.append(msg)
            for chamada in chamadas:
                fn = chamada["function"]
                args = fn.get("arguments") or {}
                if isinstance(args, str):
                    args = json.loads(args)
                usadas.append(fn["name"])
                saida = run_tool(db, fn["name"], args, allow)
                messages.append({"role": "tool", "tool_name": fn["name"], "content": _json(saida)})
        raise AssistantError("limite de passos excedido")
