"""Camada de serviço: regras de negócio do estoque (sem nada de HTTP aqui)."""
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .exceptions import BusinessRuleError, ConflictError, NotFoundError
from .models import Product, StockMovement
from .schemas import MovementCreate, ProductCreate, ProductUpdate


# ---------- Produtos ----------
def get_product(db: Session, product_id: int) -> Product:
    product = db.get(Product, product_id)
    if product is None:
        raise NotFoundError(f"Produto {product_id} não encontrado")
    return product


def get_product_by_sku(db: Session, sku: str) -> Product | None:
    return db.scalar(select(Product).where(Product.sku == sku.strip().upper()))


def create_product(db: Session, data: ProductCreate) -> Product:
    sku = data.sku.upper()
    if get_product_by_sku(db, sku):
        raise ConflictError(f"Já existe um produto com o SKU {sku}")

    product = Product(
        sku=sku,
        nome=data.nome,
        categoria=data.categoria,
        preco_custo=data.preco_custo,
        preco_venda=data.preco_venda,
        estoque_minimo=data.estoque_minimo,
        quantidade=data.quantidade,
    )
    db.add(product)
    db.flush()  # gera o id para registrar o estoque inicial
    if data.quantidade > 0:
        db.add(
            StockMovement(
                product_id=product.id,
                tipo="entrada",
                quantidade=data.quantidade,
                saldo_apos=data.quantidade,
                motivo="Estoque inicial",
            )
        )
    db.commit()
    return product


def list_products(
    db: Session,
    categoria: str | None = None,
    busca: str | None = None,
    baixo_estoque: bool = False,
    incluir_inativos: bool = False,
    skip: int = 0,
    limit: int = 100,
) -> list[Product]:
    stmt = select(Product).order_by(Product.nome)
    if not incluir_inativos:
        stmt = stmt.where(Product.ativo.is_(True))
    if categoria:
        stmt = stmt.where(Product.categoria.ilike(categoria.strip()))
    if busca:
        like = f"%{busca.strip()}%"
        stmt = stmt.where(or_(Product.nome.ilike(like), Product.sku.ilike(like)))
    if baixo_estoque:
        stmt = stmt.where(Product.quantidade <= Product.estoque_minimo)
    return list(db.scalars(stmt.offset(skip).limit(limit)))


def update_product(db: Session, product_id: int, data: ProductUpdate) -> Product:
    product = get_product(db, product_id)
    changes = data.model_dump(exclude_unset=True, exclude_none=True)
    for field, value in changes.items():
        setattr(product, field, value)
    if product.preco_venda < product.preco_custo:
        db.rollback()
        raise BusinessRuleError("preco_venda não pode ser menor que preco_custo")
    db.commit()
    return product


def deactivate_product(db: Session, product_id: int) -> None:
    """Exclusão lógica: preserva o histórico de movimentações."""
    product = get_product(db, product_id)
    product.ativo = False
    db.commit()


# ---------- Movimentações ----------
def register_movement(db: Session, product_id: int, data: MovementCreate) -> StockMovement:
    product = get_product(db, product_id)
    if not product.ativo:
        raise BusinessRuleError("Produto inativo: não aceita movimentações")

    if data.tipo == "entrada":
        novo_saldo = product.quantidade + data.quantidade
    elif data.tipo == "saida":
        if data.quantidade > product.quantidade:
            raise BusinessRuleError(
                f"Estoque insuficiente: disponível {product.quantidade}, solicitado {data.quantidade}"
            )
        novo_saldo = product.quantidade - data.quantidade
    else:  # ajuste: define o saldo absoluto (ex.: após inventário)
        novo_saldo = data.quantidade

    product.quantidade = novo_saldo
    movement = StockMovement(
        product_id=product.id,
        tipo=data.tipo,
        quantidade=data.quantidade,
        saldo_apos=novo_saldo,
        motivo=data.motivo,
    )
    db.add(movement)
    db.commit()
    return movement


def list_movements(db: Session, product_id: int | None = None, limit: int = 100) -> list[StockMovement]:
    stmt = select(StockMovement).order_by(StockMovement.criado_em.desc(), StockMovement.id.desc())
    if product_id is not None:
        get_product(db, product_id)  # 404 se não existir
        stmt = stmt.where(StockMovement.product_id == product_id)
    return list(db.scalars(stmt.limit(limit)))
