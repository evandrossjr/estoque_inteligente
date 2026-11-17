"""Relatórios e análises com Pandas sobre os dados do banco."""
from datetime import timedelta

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Product, StockMovement, utcnow

PRODUCT_COLS = ["id", "sku", "nome", "categoria", "preco_custo", "preco_venda", "quantidade", "estoque_minimo"]
MOVEMENT_COLS = ["product_id", "tipo", "quantidade", "criado_em"]


def products_df(db: Session) -> pd.DataFrame:
    """DataFrame com os produtos ativos."""
    rows = db.scalars(select(Product).where(Product.ativo.is_(True))).all()
    df = pd.DataFrame(
        [{c: getattr(p, c) for c in PRODUCT_COLS} for p in rows], columns=PRODUCT_COLS
    )
    return df


def movements_df(db: Session, dias: int) -> pd.DataFrame:
    """DataFrame com as movimentações dos últimos `dias` dias."""
    desde = utcnow() - timedelta(days=dias)
    rows = db.scalars(select(StockMovement).where(StockMovement.criado_em >= desde)).all()
    return pd.DataFrame(
        [{c: getattr(m, c) for c in MOVEMENT_COLS} for m in rows], columns=MOVEMENT_COLS
    )


def _records(df: pd.DataFrame) -> list[dict]:
    return df.round(2).to_dict("records")


def resumo(db: Session) -> dict:
    df = products_df(db)
    if df.empty:
        return {
            "total_produtos": 0, "total_unidades": 0, "valor_estoque_custo": 0.0,
            "valor_estoque_venda": 0.0, "produtos_estoque_baixo": 0, "produtos_zerados": 0,
        }
    return {
        "total_produtos": int(len(df)),
        "total_unidades": int(df["quantidade"].sum()),
        "valor_estoque_custo": round(float((df["quantidade"] * df["preco_custo"]).sum()), 2),
        "valor_estoque_venda": round(float((df["quantidade"] * df["preco_venda"]).sum()), 2),
        "produtos_estoque_baixo": int((df["quantidade"] <= df["estoque_minimo"]).sum()),
        "produtos_zerados": int((df["quantidade"] == 0).sum()),
    }


def estoque_baixo(db: Session) -> list[dict]:
    """Produtos com quantidade <= estoque mínimo, do mais crítico ao menos."""
    df = products_df(db)
    if df.empty:
        return []
    low = df[df["quantidade"] <= df["estoque_minimo"]].copy()
    low["sugestao_reposicao"] = (low["estoque_minimo"] * 2 - low["quantidade"]).clip(lower=0)
    low["deficit"] = low["estoque_minimo"] - low["quantidade"]
    low = low.sort_values(["deficit", "nome"], ascending=[False, True])
    return _records(low[["sku", "nome", "categoria", "quantidade", "estoque_minimo", "sugestao_reposicao"]])


def por_categoria(db: Session) -> list[dict]:
    df = products_df(db)
    if df.empty:
        return []
    df["valor_custo"] = df["quantidade"] * df["preco_custo"]
    grouped = (
        df.groupby("categoria")
        .agg(produtos=("id", "count"), unidades=("quantidade", "sum"), valor_custo=("valor_custo", "sum"))
        .reset_index()
        .sort_values("valor_custo", ascending=False)
    )
    return _records(grouped)


def mais_vendidos(db: Session, dias: int = 30, limite: int = 5) -> list[dict]:
    """Produtos com mais saídas no período."""
    mov = movements_df(db, dias)
    saidas = mov[mov["tipo"] == "saida"]
    if saidas.empty:
        return []
    total = saidas.groupby("product_id", as_index=False)["quantidade"].sum()
    total = total.rename(columns={"quantidade": "unidades_saidas"})
    prods = products_df(db)[["id", "sku", "nome", "categoria"]]
    merged = total.merge(prods, left_on="product_id", right_on="id").sort_values(
        "unidades_saidas", ascending=False
    )
    return _records(merged[["sku", "nome", "categoria", "unidades_saidas"]].head(limite))


def ranking_vendas(db: Session, dias: int = 30, limite: int = 5) -> dict:
    """Mais e menos vendidos do período. Produtos sem nenhuma saída entram como 0 em 'menos'."""
    prods = products_df(db)[["id", "sku", "nome", "categoria"]]
    if prods.empty:
        return {"dias": dias, "mais": [], "menos": [], "sem_venda": 0}
    mov = movements_df(db, dias)
    saidas = mov[mov["tipo"] == "saida"].groupby("product_id")["quantidade"].sum()
    prods["unidades_saidas"] = prods["id"].map(saidas).fillna(0).astype(int)
    cols = ["sku", "nome", "categoria", "unidades_saidas"]
    mais = prods[prods["unidades_saidas"] > 0].sort_values(["unidades_saidas", "nome"], ascending=[False, True])
    menos = prods.sort_values(["unidades_saidas", "nome"], ascending=[True, True])
    return {
        "dias": dias,
        "mais": _records(mais[cols].head(limite)),
        "menos": _records(menos[cols].head(limite)),
        "sem_venda": int((prods["unidades_saidas"] == 0).sum()),
    }


def analise_margem(db: Session, dias: int = 30, limite: int = 5) -> dict:
    """Cruza margem de lucro com volume de vendas e separa os produtos em 4 grupos.

    A comparação é feita contra a MEDIANA do próprio catálogo. É uma heurística: sem histórico
    de preços não dá para medir elasticidade, então as sugestões são hipóteses a testar.
    """
    prods = products_df(db)
    if prods.empty:
        return {"dias": dias, "total_produtos": 0, "grupos": {}}
    mov = movements_df(db, dias)
    saidas = mov[mov["tipo"] == "saida"].groupby("product_id")["quantidade"].sum()
    prods["unidades_vendidas"] = prods["id"].map(saidas).fillna(0).astype(int)

    venda, custo = prods["preco_venda"], prods["preco_custo"]
    prods["margem_pct"] = ((venda - custo) / venda * 100).where(venda > 0, 0.0)
    prods["lucro_periodo"] = (venda - custo) * prods["unidades_vendidas"]

    med_margem = float(prods["margem_pct"].median())
    med_vendas = float(prods["unidades_vendidas"].median())
    margem_alta = prods["margem_pct"] >= med_margem
    vendas_altas = (prods["unidades_vendidas"] > 0) & (prods["unidades_vendidas"] >= med_vendas)

    prods["grupo"] = "revisar"
    prods.loc[margem_alta & vendas_altas, "grupo"] = "manter"
    prods.loc[~margem_alta & vendas_altas, "grupo"] = "testar_aumento"
    prods.loc[margem_alta & ~vendas_altas, "grupo"] = "testar_promocao"

    cols = ["sku", "nome", "margem_pct", "unidades_vendidas", "lucro_periodo"]
    grupos = {}
    for nome, g in prods.groupby("grupo"):
        ordenado = g.sort_values("lucro_periodo", ascending=False) if nome in ("manter", "testar_aumento") else g.sort_values("margem_pct", ascending=False)
        grupos[nome] = _records(ordenado[cols].head(limite))
    receita = float((venda * prods["unidades_vendidas"]).sum())
    lucro = float(prods["lucro_periodo"].sum())
    return {
        "dias": dias,
        "total_produtos": int(len(prods)),
        "margem_mediana_pct": round(med_margem, 1),
        "vendas_mediana_un": round(med_vendas, 1),
        "lucro_bruto_periodo": round(lucro, 2),
        "margem_realizada_pct": round(lucro / receita * 100, 1) if receita else 0.0,
        "grupos": grupos,
        "observacao": "Heurística baseada nas medianas do catálogo; sem histórico de preços, trate as sugestões como testes.",
    }


def sem_giro(db: Session, dias: int = 30) -> list[dict]:
    """Produtos com estoque, mas sem nenhuma saída no período (capital parado)."""
    prods = products_df(db)
    if prods.empty:
        return []
    mov = movements_df(db, dias)
    com_saida = set(mov.loc[mov["tipo"] == "saida", "product_id"])
    parados = prods[(prods["quantidade"] > 0) & (~prods["id"].isin(com_saida))].copy()
    parados["valor_parado"] = parados["quantidade"] * parados["preco_custo"]
    parados = parados.sort_values("valor_parado", ascending=False)
    return _records(parados[["sku", "nome", "categoria", "quantidade", "valor_parado"]])


def curva_abc(db: Session) -> list[dict]:
    """Classifica produtos pelo valor em estoque: A (até 80%), B (até 95%), C (resto)."""
    df = products_df(db)
    if df.empty:
        return []
    df["valor"] = df["quantidade"] * df["preco_custo"]
    df = df[df["valor"] > 0].sort_values("valor", ascending=False).copy()
    if df.empty:
        return []
    df["percentual"] = df["valor"] / df["valor"].sum() * 100
    df["acumulado"] = df["percentual"].cumsum()
    # classifica pelo acumulado ANTES do item, para o 1º item sempre cair em A
    anterior = df["acumulado"] - df["percentual"]
    df["classe"] = anterior.apply(lambda a: "A" if a < 80 else ("B" if a < 95 else "C"))
    return _records(df[["sku", "nome", "valor", "percentual", "classe"]])


def movimentacao_periodo(db: Session, dias: int = 30) -> dict:
    mov = movements_df(db, dias)
    if mov.empty:
        return {"dias": dias, "entradas": 0, "saidas": 0, "ajustes": 0}
    contagem = mov.groupby("tipo")["quantidade"].sum()
    return {
        "dias": dias,
        "entradas": int(contagem.get("entrada", 0)),
        "saidas": int(contagem.get("saida", 0)),
        "ajustes": int((mov["tipo"] == "ajuste").sum()),
    }


def exportar_csv(db: Session) -> str:
    df = products_df(db)
    if not df.empty:
        df["valor_custo_total"] = (df["quantidade"] * df["preco_custo"]).round(2)
        df["estoque_baixo"] = df["quantidade"] <= df["estoque_minimo"]
    return df.to_csv(index=False)
