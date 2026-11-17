"""Popula o banco com dados de exemplo: python -m app.seed"""
import random
from datetime import timedelta

from .database import SessionLocal, init_db
from .models import Product, StockMovement, utcnow

CATALOGO = [
    # (sku, nome, categoria, custo, venda, qtd_atual, minimo)
    ("ELE-001", "Mouse sem fio", "Eletrônicos", 25.0, 49.9, 8, 15),
    ("ELE-002", "Teclado mecânico", "Eletrônicos", 120.0, 219.9, 22, 10),
    ("ELE-003", "Fone Bluetooth", "Eletrônicos", 60.0, 129.9, 3, 10),
    ("ELE-004", "Carregador USB-C 20W", "Eletrônicos", 18.0, 39.9, 54, 20),
    ("ELE-005", "Webcam Full HD", "Eletrônicos", 95.0, 179.9, 14, 6),
    ("INF-001", "Cabo HDMI 2m", "Informática", 9.0, 24.9, 80, 30),
    ("INF-002", "Pen drive 64GB", "Informática", 22.0, 44.9, 0, 15),
    ("INF-003", "SSD 480GB", "Informática", 180.0, 289.9, 12, 8),
    ("INF-004", "Hub USB 4 portas", "Informática", 28.0, 59.9, 31, 10),
    ("INF-005", "Mousepad grande", "Informática", 12.0, 34.9, 45, 12),
    ("ESC-001", "Caderno 200 folhas", "Papelaria", 8.0, 18.9, 120, 40),
    ("ESC-002", "Caneta esferográfica (cx 50)", "Papelaria", 20.0, 39.9, 6, 10),
    ("ESC-003", "Papel A4 (resma 500)", "Papelaria", 19.0, 29.9, 95, 50),
    ("ESC-004", "Grampeador de mesa", "Papelaria", 15.0, 32.9, 18, 5),
    ("ESC-005", "Pasta suspensa (cx 25)", "Papelaria", 30.0, 58.9, 9, 8),
    ("LIM-001", "Detergente 500ml", "Limpeza", 1.9, 3.9, 200, 80),
    ("LIM-002", "Desinfetante 2L", "Limpeza", 6.5, 12.9, 24, 40),
    ("LIM-003", "Papel toalha (pct 2)", "Limpeza", 5.0, 9.9, 70, 30),
    ("LIM-004", "Saco de lixo 100L (pct 10)", "Limpeza", 8.0, 15.9, 42, 25),
    ("MOV-001", "Cadeira de escritório", "Móveis", 280.0, 499.0, 7, 4),
    ("MOV-002", "Mesa de reunião", "Móveis", 650.0, 1190.0, 2, 2),
    ("MOV-003", "Armário arquivo 4 gavetas", "Móveis", 420.0, 769.0, 5, 3),
    ("MOV-004", "Suporte para monitor", "Móveis", 45.0, 89.9, 26, 8),
]

# Produtos que ficam sem nenhuma saída (para a análise de itens parados)
SEM_SAIDA = {"MOV-003", "ESC-005", "INF-003"}


def seed(reset: bool = False) -> int:
    init_db()
    rng = random.Random(42)
    agora = utcnow()
    with SessionLocal() as db:
        if db.query(Product).count() and not reset:
            return 0
        if reset:
            db.query(StockMovement).delete()
            db.query(Product).delete()
            db.commit()

        for sku, nome, cat, custo, venda, qtd, minimo in CATALOGO:
            p = Product(sku=sku, nome=nome, categoria=cat, preco_custo=custo, preco_venda=venda,
                        quantidade=qtd, estoque_minimo=minimo)
            db.add(p)
            db.flush()

            # histórico: entrada inicial há 90 dias + saídas espalhadas nos últimos 60 dias
            saidas = [] if sku in SEM_SAIDA else [rng.randint(1, 6) for _ in range(rng.randint(4, 12))]
            total_saidas = sum(saidas)
            saldo = qtd + total_saidas
            db.add(StockMovement(product_id=p.id, tipo="entrada", quantidade=saldo, saldo_apos=saldo,
                                 motivo="Estoque inicial", criado_em=agora - timedelta(days=90)))
            # datas em ordem cronológica para que saldo_apos faça sentido no histórico
            datas = sorted((agora - timedelta(days=rng.randint(1, 60), hours=rng.randint(0, 23)) for _ in saidas))
            for qtd_saida, quando in zip(saidas, datas):
                saldo -= qtd_saida
                db.add(StockMovement(product_id=p.id, tipo="saida", quantidade=qtd_saida, saldo_apos=saldo,
                                     motivo="Venda", criado_em=quando))
        db.commit()
    return len(CATALOGO)


if __name__ == "__main__":
    criados = seed()
    print(f"{criados} produtos criados." if criados else "Banco já possui dados; nada a fazer.")
