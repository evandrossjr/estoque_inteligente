from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from .. import services
from ..database import get_db
from ..schemas import MovementCreate, MovementOut, ProductCreate, ProductOut, ProductUpdate

router = APIRouter(prefix="/products", tags=["Produtos"])


@router.post("", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
def criar_produto(data: ProductCreate, db: Session = Depends(get_db)):
    return services.create_product(db, data)


@router.get("", response_model=list[ProductOut])
def listar_produtos(
    categoria: str | None = None,
    busca: str | None = Query(default=None, description="Parte do nome ou SKU"),
    baixo_estoque: bool = False,
    incluir_inativos: bool = False,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    return services.list_products(db, categoria, busca, baixo_estoque, incluir_inativos, skip, limit)


@router.get("/{product_id}", response_model=ProductOut)
def obter_produto(product_id: int, db: Session = Depends(get_db)):
    return services.get_product(db, product_id)


@router.put("/{product_id}", response_model=ProductOut)
def atualizar_produto(product_id: int, data: ProductUpdate, db: Session = Depends(get_db)):
    return services.update_product(db, product_id, data)


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
def desativar_produto(product_id: int, db: Session = Depends(get_db)):
    """Exclusão lógica: o produto some das listagens, mas o histórico é preservado."""
    services.deactivate_product(db, product_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{product_id}/movements", response_model=MovementOut, status_code=status.HTTP_201_CREATED)
def registrar_movimentacao(product_id: int, data: MovementCreate, db: Session = Depends(get_db)):
    return services.register_movement(db, product_id, data)


@router.get("/{product_id}/movements", response_model=list[MovementOut])
def historico_produto(product_id: int, limit: int = Query(default=100, ge=1, le=500), db: Session = Depends(get_db)):
    return services.list_movements(db, product_id, limit)
