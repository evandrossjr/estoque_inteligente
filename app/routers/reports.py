from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from .. import analytics
from ..database import get_db

router = APIRouter(prefix="/reports", tags=["Relatórios"])


@router.get("/summary")
def resumo(db: Session = Depends(get_db)):
    return analytics.resumo(db)


@router.get("/low-stock")
def estoque_baixo(db: Session = Depends(get_db)):
    return analytics.estoque_baixo(db)


@router.get("/by-category")
def por_categoria(db: Session = Depends(get_db)):
    return analytics.por_categoria(db)


@router.get("/top-sellers")
def mais_vendidos(
    dias: int = Query(default=30, ge=1, le=365),
    limite: int = Query(default=5, ge=1, le=50),
    db: Session = Depends(get_db),
):
    return analytics.mais_vendidos(db, dias, limite)


@router.get("/sales-ranking")
def ranking_vendas(
    dias: int = Query(default=30, ge=1, le=365),
    limite: int = Query(default=5, ge=1, le=50),
    db: Session = Depends(get_db),
):
    """Mais e menos vendidos do período (inclui produtos com zero vendas)."""
    return analytics.ranking_vendas(db, dias, limite)


@router.get("/margin")
def analise_margem(
    dias: int = Query(default=30, ge=1, le=365),
    limite: int = Query(default=5, ge=1, le=50),
    db: Session = Depends(get_db),
):
    """Margem de lucro x volume de vendas, com grupos de ação (manter, testar aumento, testar promoção, revisar)."""
    return analytics.analise_margem(db, dias, limite)


@router.get("/no-movement")
def sem_giro(dias: int = Query(default=30, ge=1, le=365), db: Session = Depends(get_db)):
    return analytics.sem_giro(db, dias)


@router.get("/abc")
def curva_abc(db: Session = Depends(get_db)):
    return analytics.curva_abc(db)


@router.get("/movements")
def movimentacao_periodo(dias: int = Query(default=30, ge=1, le=365), db: Session = Depends(get_db)):
    return analytics.movimentacao_periodo(db, dias)


@router.get("/export.csv")
def exportar(db: Session = Depends(get_db)):
    return Response(
        content=analytics.exportar_csv(db),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=estoque.csv"},
    )
