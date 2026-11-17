"""Ferramentas que o LLM pode chamar.

Segurança: o modelo NUNCA escreve SQL nem acessa o banco diretamente. Ele só escolhe entre
as funções abaixo, e cada argumento é validado aqui. Ferramentas de escrita ficam
desligadas, a menos que AI_ALLOW_WRITES=true.
"""
from typing import Any, Callable

from sqlalchemy.orm import Session

from .. import analytics, services
from ..exceptions import DomainError
from ..schemas import MovementCreate

MAX_DIAS = 365
MAX_LIMITE = 20


def _int(args: dict, nome: str, padrao: int, minimo: int, maximo: int) -> int:
    valor = args.get(nome, padrao)
    try:
        valor = int(valor)
    except (TypeError, ValueError):
        raise ValueError(f"'{nome}' deve ser um número inteiro")
    if not minimo <= valor <= maximo:
        raise ValueError(f"'{nome}' deve estar entre {minimo} e {maximo}")
    return valor


def _produto_dict(p) -> dict:
    return {
        "sku": p.sku, "nome": p.nome, "categoria": p.categoria, "quantidade": p.quantidade,
        "estoque_minimo": p.estoque_minimo, "preco_custo": p.preco_custo,
        "preco_venda": p.preco_venda, "estoque_baixo": p.quantidade <= p.estoque_minimo,
    }


# ---------- Implementações (db, args) -> dict ----------
def _buscar_produtos(db: Session, args: dict) -> dict:
    termo = str(args.get("termo", "")).strip()
    if not termo:
        raise ValueError("informe 'termo' para a busca")
    categoria = args.get("categoria")
    produtos = services.list_products(db, categoria=categoria, busca=termo, limit=MAX_LIMITE)
    return {"total": len(produtos), "produtos": [_produto_dict(p) for p in produtos]}


def _consultar_produto(db: Session, args: dict) -> dict:
    sku = str(args.get("sku", "")).strip()
    if not sku:
        raise ValueError("informe o 'sku'")
    produto = services.get_product_by_sku(db, sku)
    if produto is None or not produto.ativo:
        return {"erro": f"Produto com SKU {sku.upper()} não encontrado"}
    return _produto_dict(produto)


def _listar_estoque_baixo(db: Session, args: dict) -> dict:
    itens = analytics.estoque_baixo(db)
    return {"total": len(itens), "produtos": itens}


def _resumo_estoque(db: Session, args: dict) -> dict:
    return analytics.resumo(db)


def _estoque_por_categoria(db: Session, args: dict) -> dict:
    return {"categorias": analytics.por_categoria(db)}


def _mais_vendidos(db: Session, args: dict) -> dict:
    dias = _int(args, "dias", 30, 1, MAX_DIAS)
    limite = _int(args, "limite", 5, 1, MAX_LIMITE)
    return {"dias": dias, "produtos": analytics.mais_vendidos(db, dias, limite)}


def _ranking_vendas(db: Session, args: dict) -> dict:
    dias = _int(args, "dias", 30, 1, MAX_DIAS)
    limite = _int(args, "limite", 5, 1, MAX_LIMITE)
    return analytics.ranking_vendas(db, dias, limite)


def _analise_margem(db: Session, args: dict) -> dict:
    return analytics.analise_margem(db, _int(args, "dias", 30, 1, MAX_DIAS), _int(args, "limite", 5, 1, MAX_LIMITE))


def _produtos_sem_giro(db: Session, args: dict) -> dict:
    dias = _int(args, "dias", 30, 1, MAX_DIAS)
    itens = analytics.sem_giro(db, dias)
    return {"dias": dias, "total": len(itens), "produtos": itens[:MAX_LIMITE]}


def _curva_abc(db: Session, args: dict) -> dict:
    return {"itens": analytics.curva_abc(db)[: MAX_LIMITE * 2]}


def _movimentacao_periodo(db: Session, args: dict) -> dict:
    return analytics.movimentacao_periodo(db, _int(args, "dias", 30, 1, MAX_DIAS))


def _registrar_movimentacao(db: Session, args: dict) -> dict:
    sku = str(args.get("sku", "")).strip()
    produto = services.get_product_by_sku(db, sku)
    if produto is None:
        return {"erro": f"Produto com SKU {sku.upper()} não encontrado"}
    dados = MovementCreate(
        tipo=args.get("tipo"), quantidade=args.get("quantidade"), motivo=args.get("motivo", "Via assistente")
    )
    mov = services.register_movement(db, produto.id, dados)
    return {"ok": True, "tipo": mov.tipo, "saldo_apos": mov.saldo_apos, "sku": produto.sku}


# ---------- Registro: nome -> (função, escrita?, descrição, schema de entrada) ----------
def _schema(props: dict | None = None, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props or {}, "required": required or []}


_DIAS = {"type": "integer", "description": "Janela em dias (1 a 365). Padrão 30."}

REGISTRY: dict[str, dict[str, Any]] = {
    "buscar_produtos": {
        "fn": _buscar_produtos, "write": False,
        "description": "Busca produtos por parte do nome ou SKU, opcionalmente filtrando por categoria.",
        "schema": _schema(
            {"termo": {"type": "string", "description": "Parte do nome ou SKU"},
             "categoria": {"type": "string", "description": "Categoria exata (opcional)"}},
            ["termo"],
        ),
    },
    "consultar_produto": {
        "fn": _consultar_produto, "write": False,
        "description": "Retorna os dados e o saldo atual de um produto pelo SKU exato.",
        "schema": _schema({"sku": {"type": "string", "description": "SKU, ex.: ELE-001"}}, ["sku"]),
    },
    "listar_estoque_baixo": {
        "fn": _listar_estoque_baixo, "write": False,
        "description": "Lista produtos com quantidade igual ou abaixo do estoque mínimo, com sugestão de reposição.",
        "schema": _schema(),
    },
    "resumo_estoque": {
        "fn": _resumo_estoque, "write": False,
        "description": "Visão geral: total de produtos, unidades, valor em estoque, itens em estoque baixo e zerados.",
        "schema": _schema(),
    },
    "estoque_por_categoria": {
        "fn": _estoque_por_categoria, "write": False,
        "description": "Produtos, unidades e valor em estoque agrupados por categoria.",
        "schema": _schema(),
    },
    "mais_vendidos": {
        "fn": _mais_vendidos, "write": False,
        "description": "Produtos com mais unidades saídas no período.",
        "schema": _schema({"dias": _DIAS, "limite": {"type": "integer", "description": "Quantos itens (1 a 20). Padrão 5."}}),
    },
    "ranking_vendas": {
        "fn": _ranking_vendas, "write": False,
        "description": (
            "Ranking de vendas (unidades saídas) no período: devolve os MAIS vendidos e os MENOS vendidos, "
            "incluindo produtos com zero vendas. Use para perguntas sobre mais/menos vendidos, "
            "'o produto que mais vende', 'o que menos sai'."
        ),
        "schema": _schema({"dias": _DIAS, "limite": {"type": "integer", "description": "Quantos itens por lista (1 a 20). Padrão 5."}}),
    },
    "analise_margem": {
        "fn": _analise_margem, "write": False,
        "description": (
            "Cruza margem de lucro (preço de venda x custo) com volume de vendas e classifica os produtos em: "
            "manter, testar_aumento (vende bem com margem baixa), testar_promocao (margem alta, vende pouco) "
            "e revisar. Use para perguntas sobre preço, margem, lucro, markup ou equilíbrio entre venda e custo."
        ),
        "schema": _schema({"dias": _DIAS, "limite": {"type": "integer", "description": "Itens por grupo (1 a 20). Padrão 5."}}),
    },
    "produtos_sem_giro": {
        "fn": _produtos_sem_giro, "write": False,
        "description": "Produtos com estoque que não tiveram nenhuma saída no período (capital parado).",
        "schema": _schema({"dias": _DIAS}),
    },
    "curva_abc": {
        "fn": _curva_abc, "write": False,
        "description": "Classificação ABC dos produtos pelo valor em estoque.",
        "schema": _schema(),
    },
    "movimentacao_periodo": {
        "fn": _movimentacao_periodo, "write": False,
        "description": "Total de entradas, saídas e ajustes no período.",
        "schema": _schema({"dias": _DIAS}),
    },
    "registrar_movimentacao": {
        "fn": _registrar_movimentacao, "write": True,
        "description": "Registra entrada, saída ou ajuste de estoque. Use SOMENTE se o usuário pediu a operação explicitamente.",
        "schema": _schema(
            {"sku": {"type": "string"},
             "tipo": {"type": "string", "enum": ["entrada", "saida", "ajuste"]},
             "quantidade": {"type": "integer", "description": "Em 'ajuste', é o novo saldo"},
             "motivo": {"type": "string"}},
            ["sku", "tipo", "quantidade"],
        ),
    },
}


def available_tools(allow_writes: bool) -> dict[str, dict[str, Any]]:
    return {n: t for n, t in REGISTRY.items() if allow_writes or not t["write"]}


def anthropic_specs(allow_writes: bool) -> list[dict]:
    return [
        {"name": n, "description": t["description"], "input_schema": t["schema"]}
        for n, t in available_tools(allow_writes).items()
    ]


def ollama_specs(allow_writes: bool) -> list[dict]:
    return [
        {"type": "function", "function": {"name": n, "description": t["description"], "parameters": t["schema"]}}
        for n, t in available_tools(allow_writes).items()
    ]


def run_tool(db: Session, nome: str, args: dict | None, allow_writes: bool) -> dict:
    """Executa uma ferramenta; qualquer erro vira um dicionário {'erro': ...} para o modelo ler."""
    tool: Callable | None = available_tools(allow_writes).get(nome)
    if tool is None:
        return {"erro": f"Ferramenta '{nome}' não disponível"}
    try:
        return tool["fn"](db, args or {})
    except (ValueError, DomainError) as exc:
        db.rollback()
        return {"erro": getattr(exc, "message", None) or str(exc)}
    except Exception:  # não vaza detalhes internos para o modelo
        db.rollback()
        return {"erro": "Falha interna ao executar a ferramenta"}
