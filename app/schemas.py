"""Schemas Pydantic: validação de entrada e formato de saída da API."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _limpa(texto: str) -> str:
    texto = texto.strip()
    if not texto:
        raise ValueError("não pode ser vazio")
    return texto


class ProductBase(BaseModel):
    sku: str = Field(min_length=1, max_length=40, examples=["ELE-001"])
    nome: str = Field(min_length=1, max_length=120, examples=["Mouse sem fio"])
    categoria: str = Field(min_length=1, max_length=60, examples=["Eletrônicos"])
    preco_custo: float = Field(ge=0, examples=[25.0])
    preco_venda: float = Field(ge=0, examples=[49.9])
    estoque_minimo: int = Field(default=0, ge=0, examples=[10])

    @field_validator("sku", "nome", "categoria")
    @classmethod
    def _textos(cls, v: str) -> str:
        return _limpa(v)


class ProductCreate(ProductBase):
    quantidade: int = Field(default=0, ge=0, examples=[50], description="Estoque inicial")

    @model_validator(mode="after")
    def _preco_coerente(self):
        if self.preco_venda < self.preco_custo:
            raise ValueError("preco_venda não pode ser menor que preco_custo")
        return self


class ProductUpdate(BaseModel):
    """Atualização parcial. A quantidade só muda por movimentação."""

    nome: str | None = Field(default=None, min_length=1, max_length=120)
    categoria: str | None = Field(default=None, min_length=1, max_length=60)
    preco_custo: float | None = Field(default=None, ge=0)
    preco_venda: float | None = Field(default=None, ge=0)
    estoque_minimo: int | None = Field(default=None, ge=0)

    @field_validator("nome", "categoria")
    @classmethod
    def _textos(cls, v: str | None) -> str | None:
        return None if v is None else _limpa(v)


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sku: str
    nome: str
    categoria: str
    preco_custo: float
    preco_venda: float
    quantidade: int
    estoque_minimo: int
    ativo: bool
    criado_em: datetime
    atualizado_em: datetime


class MovementCreate(BaseModel):
    tipo: Literal["entrada", "saida", "ajuste"]
    quantidade: int = Field(ge=0, description="Em 'ajuste', é o novo saldo do produto")
    motivo: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _quantidade_por_tipo(self):
        if self.tipo in ("entrada", "saida") and self.quantidade <= 0:
            raise ValueError("quantidade deve ser maior que zero em entrada/saida")
        return self


class MovementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    tipo: str
    quantidade: int
    saldo_apos: int
    motivo: str | None
    criado_em: datetime


class AskRequest(BaseModel):
    pergunta: str = Field(min_length=3, max_length=500, examples=["Quais produtos estão com estoque baixo?"])

    @field_validator("pergunta")
    @classmethod
    def _strip(cls, v: str) -> str:
        return _limpa(v)


class AskResponse(BaseModel):
    resposta: str
    ferramentas_usadas: list[str]
    modo: Literal["anthropic", "ollama", "local"]
    aviso: str | None = None
