"""Modelos ORM (tabelas do banco relacional)."""
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    """UTC sem fuso (naive), para ser compatível com o SQLite."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    nome: Mapped[str] = mapped_column(String(120), index=True)
    categoria: Mapped[str] = mapped_column(String(60), index=True)
    preco_custo: Mapped[float] = mapped_column(Float, default=0.0)
    preco_venda: Mapped[float] = mapped_column(Float, default=0.0)
    quantidade: Mapped[int] = mapped_column(Integer, default=0)
    estoque_minimo: Mapped[int] = mapped_column(Integer, default=0)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    atualizado_em: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    movimentacoes: Mapped[list["StockMovement"]] = relationship(back_populates="produto")


class StockMovement(Base):
    __tablename__ = "stock_movements"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    tipo: Mapped[str] = mapped_column(String(10))  # entrada | saida | ajuste
    quantidade: Mapped[int] = mapped_column(Integer)  # em ajuste, é o novo saldo
    saldo_apos: Mapped[int] = mapped_column(Integer)
    motivo: Mapped[str | None] = mapped_column(String(200), nullable=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)

    produto: Mapped[Product] = relationship(back_populates="movimentacoes")
