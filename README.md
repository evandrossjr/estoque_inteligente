# Assistente de Estoque Inteligente

Sistema de gestão de estoque com **API REST (FastAPI)**, **banco relacional (SQLAlchemy + SQLite)**, **relatórios com Pandas** e um **assistente de IA** que responde perguntas em linguagem natural, como "quais produtos estão com estoque baixo?".

Projeto final do curso de Python, IA e Data Science (proposta 3: sistema de estoque com IA).

## Objetivo

Substituir a consulta manual a planilhas por um sistema em que o responsável pelo estoque:

- cadastra, consulta, atualiza e desativa produtos (CRUD);
- registra entradas, saídas e ajustes, com histórico completo;
- identifica produtos com estoque reduzido e quanto repor;
- emite relatórios (resumo, categorias, mais vendidos, itens parados, curva ABC, CSV);
- faz perguntas em português ao assistente e recebe respostas baseadas nos dados reais.

## Tecnologias

| Camada | Tecnologia |
|---|---|
| API | FastAPI + Uvicorn |
| Validação | Pydantic v2 |
| Banco | SQLAlchemy 2 (SQLite; PostgreSQL/MySQL via `DATABASE_URL`) |
| Análises | Pandas |
| IA | Claude (API Anthropic, com *tool use*), Ollama (modelo local) ou modo local por regras |
| Testes | Pytest + TestClient |
| Extras | Interface web simples, Docker |

## Arquitetura

```
Requisição ─▶ routers/ ─▶ services.py ─▶ models.py ─▶ banco
                 │             (regras de negócio)
                 ├──────────▶ analytics.py (Pandas)
                 └─▶ ai/assistant.py ─▶ ai/tools.py ─▶ services / analytics
```

| Arquivo | Responsabilidade |
|---|---|
| `app/routers/` | Endpoints HTTP (só recebem e devolvem dados) |
| `app/schemas.py` | Validação de entrada e formato de saída |
| `app/services.py` | Regras de negócio (SKU único, saldo nunca negativo, preço de venda ≥ custo...) |
| `app/models.py` | Tabelas `products` e `stock_movements` |
| `app/analytics.py` | Relatórios com DataFrames do Pandas |
| `app/ai/tools.py` | Ferramentas que a IA pode chamar, com argumentos validados |
| `app/ai/assistant.py` | Prompt do sistema, laço de *tool use* e modo local |
| `app/exceptions.py` + `main.py` | Erros de domínio convertidos em respostas HTTP (404, 409, 422) |

### Como a IA funciona

O modelo **não escreve SQL e não acessa o banco**. Ele recebe uma lista de ferramentas (`listar_estoque_baixo`, `mais_vendidos`, `produtos_sem_giro`, `curva_abc`...), escolhe qual chamar, o sistema executa a ferramenta com os argumentos validados e devolve o resultado, e o modelo redige a resposta em português. O prompt de sistema proíbe inventar dados.

Camadas de proteção:

- ferramentas de **escrita desligadas por padrão** (`AI_ALLOW_WRITES=false`);
- argumentos validados (janelas de 1 a 365 dias, limites de itens, SKU obrigatório);
- erros internos não vazam para o modelo;
- máximo de 5 passos por pergunta;
- se o LLM falhar (sem rede, chave inválida), o assistente **cai para o modo local** e avisa no campo `aviso`.

**O LLM sempre responde primeiro.** No modo `auto` (padrão), o assistente usa o Claude se houver `ANTHROPIC_API_KEY` e, senão, o Ollama (modelo padrão `qwen2.5:3b`). O **modo local** (palavras-chave, sem LLM) é apenas uma reserva: entra quando o LLM falha e a resposta traz o motivo no campo `aviso`. Assim o projeto continua funcionando sem internet e nos testes (`LLM_PROVIDER=local` desliga o LLM de propósito).

## Instalação e execução

Requer Python 3.11 ou superior.

```bash
git clone <url-do-repositorio>
cd estoque-inteligente

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env             # opcional; sem chave usa o modo local
python -m app.seed               # cria 23 produtos de exemplo com histórico
uvicorn app.main:app --reload
```

Acesse:

- Interface web: http://localhost:8000/app/
- Documentação interativa (Swagger): http://localhost:8000/docs

### Ativando o LLM

**Claude (Anthropic):** preencha `ANTHROPIC_API_KEY` no `.env`. O modelo padrão é `claude-haiku-5-5` (altere em `ANTHROPIC_MODEL`).

**Ollama (local e gratuito):**

```bash
ollama pull qwen2.5:3b          # ou llama3.1 (modelos com suporte a tools)
# no .env:
LLM_PROVIDER=ollama
OLLAMA_MODEL=qwen2.5:3b
```

**Como saber qual motor está em uso:** o campo `modo` da resposta de `/assistant/ask` mostra `anthropic`, `ollama` ou `local` (se houver `aviso`, o LLM falhou e o modo local assumiu). O endpoint `GET /assistant/status` mostra o provedor efetivo e, no caso do Ollama, se ele está acessível e se o modelo está instalado.

### Docker

```bash
docker build -t estoque-inteligente .
docker run -p 8000:8000 --env-file .env estoque-inteligente
```

## Endpoints

| Método | Rota | Descrição |
|---|---|---|
| POST | `/products` | Cadastra produto (com estoque inicial opcional) |
| GET | `/products` | Lista com filtros: `categoria`, `busca`, `baixo_estoque`, `incluir_inativos`, `skip`, `limit` |
| GET / PUT | `/products/{id}` | Consulta / atualiza (parcial) |
| DELETE | `/products/{id}` | Desativa (exclusão lógica, preserva histórico) |
| POST | `/products/{id}/movements` | Entrada, saída ou ajuste de estoque |
| GET | `/products/{id}/movements` | Histórico do produto |
| GET | `/reports/summary` | Totais e valor do estoque |
| GET | `/reports/low-stock` | Estoque baixo, com sugestão de reposição |
| GET | `/reports/by-category` | Agrupado por categoria |
| GET | `/reports/top-sellers?dias=30&limite=5` | Mais vendidos |
| GET | `/reports/sales-ranking?dias=30&limite=5` | Mais e menos vendidos (inclui itens com zero vendas) |
| GET | `/reports/margin?dias=30` | Margem x vendas: grupos manter, testar aumento, testar promoção, revisar |
| GET | `/reports/no-movement?dias=30` | Itens parados |
| GET | `/reports/abc` | Curva ABC |
| GET | `/reports/movements?dias=30` | Entradas, saídas e ajustes no período |
| GET | `/reports/export.csv` | Exporta o estoque em CSV |
| POST | `/assistant/ask` | Pergunta em linguagem natural |
| GET | `/assistant/status` | Diagnóstico: provedor em uso e saúde do Ollama |

### Exemplo

```bash
curl -X POST localhost:8000/assistant/ask \
  -H "Content-Type: application/json" \
  -d '{"pergunta": "Quais produtos estão com estoque baixo?"}'
```

```json
{
  "resposta": "6 produto(s) com estoque baixo:\n- LIM-002 Desinfetante 2L: 24 un. (mínimo 40), repor ~56\n...",
  "ferramentas_usadas": ["listar_estoque_baixo"],
  "modo": "local",
  "aviso": null
}
```

Outras perguntas que funcionam: "resumo do estoque", "mais vendidos nos últimos 60 dias", "qual o produto com mais e com menos vendas?", "os 3 produtos menos vendidos", "produtos parados", "curva ABC", "estoque por categoria", "quanto tem do ELE-001?", "tem mouse?".

## Regras de negócio

- SKU único (guardado em maiúsculas).
- Preço de venda não pode ser menor que o de custo.
- A quantidade só muda por movimentação, nunca por edição direta.
- Saída maior que o saldo é bloqueada (o estoque nunca fica negativo).
- Ajuste define o saldo absoluto (útil após inventário).
- Produto desativado não aceita movimentações e some das listagens e relatórios.
- Estoque baixo = quantidade ≤ estoque mínimo. Sugestão de reposição = 2 × mínimo − quantidade.

## Testes

```bash
pytest
```

São 52 testes, cobrindo CRUD, validações, regras de negócio, relatórios com valores calculados à mão, a segurança das ferramentas de IA, o laço de *tool use* com um cliente falso e o fallback quando o LLM falha. Nenhum teste usa rede.

## Limitações e melhorias futuras

- Preços em `float`; em produção, usar `Decimal`/`Numeric`.
- Sem autenticação; adicionar OAuth2/JWT antes de expor a API.
- O modo local entende um conjunto fixo de perguntas; o LLM cobre perguntas mais livres.
- Evoluções possíveis: previsão de demanda (Machine Learning), alertas por e-mail/Telegram, migrações com Alembic, multi-armazém, importação de NF-e.
