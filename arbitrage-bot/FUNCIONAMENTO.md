# ARBITRAGE NEXUS v3 — Funcionamento completo

Este documento explica **como o bot funciona de ponta a ponta**, desde o bootstrap (`run.bat`/`run.sh`) até coleta de preços, detecção de oportunidades, execução (simulada), persistência em banco, e atualização do dashboard em tempo real.

> **Importante (segurança)**: o repositório contém `.env` e `arbitrage.db` no `git status`. **Não versiona chaves de API nem banco**. Use `.env` local e adicione ao `.gitignore` se ainda não estiver.

## Visão geral (o que roda de verdade)

O entrypoint usado pelos scripts de execução é o **`server.py`**:

- `run.bat` (Windows) e `run.sh` (Linux/macOS) executam `python server.py`.
- `server.py` inicia um servidor HTTP + WebSocket (implementação própria via `socket`), e um loop interno que:
  - atualiza mercado (real via `ccxt` quando possível; senão simulado),
  - roda 5 estratégias (engines) em sequência,
  - registra eventos, trades, equity,
  - transmite o estado para o dashboard.

O dashboard fica em **`http://localhost:8888`** por padrão.

## Componentes e responsabilidades (arquitetura)

Dentro de `server.py`, as peças principais são:

- **Bootstrap / dependências**
  - tenta importar `ccxt`; se não existir, tenta instalar automaticamente;
  - se não houver internet para instalar, o bot segue com **preços simulados**.

- **Configuração (`.env`)**
  - `server.py` lê `arbitrage-bot/.env` e injeta as variáveis em `os.environ`.

- **Mercado (preços)**
  - `RealMarketFetcher`: conecta em múltiplas exchanges via `ccxt` **sem precisar de API keys** (dados públicos) para buscar tickers reais.
  - `MarketSimulator`: gera preços simulados (com ruído, tendência e “shocks”) para manter spreads e permitir arbitragem de teste.
  - `HybridMarket`: usa **real quando possível** e preenche gaps com simulado.

- **Modelo de execução (realismo de trade)**
  - `ExecutionModel`: simula **latência**, **slippage**, **fees**, **falhas aleatórias** e **rate limiting** por exchange.

- **Portfólio**
  - `Portfolio`: controla saldo, P&L, métricas (ROI, drawdown, win rate, Sharpe, profit factor), e mantém histórico de equity/trades.

- **Persistência**
  - `Database`: grava em **SQLite** (`arbitrage.db`) tabelas de trades, equity, oportunidades e sessões.

- **Estratégias (engines)**
  - `CrossExchangeEngine`: arbitragem entre exchanges (buy na menor ask / sell na maior bid).
  - `TriangularEngine`: arbitragem triangular (ciclo em 3 pares numa exchange).
  - `StatisticalEngine`: “pairs trading”/mean reversion via z-score.
  - `FundingRateEngine`: captura prêmio de funding (spot vs perp) de forma simplificada.
  - `DexCexEngine`: discrepância de preço DEX vs CEX (simulada + custo de gas).

- **Servidor (dashboard)**
  - `BotServer`: expõe:
    - `GET /` → `dashboard/index.html`
    - `GET /api/...` → um snapshot do estado (JSON)
    - WebSocket (upgrade HTTP) → pushes de `init` e `update` para o frontend
  - o frontend se conecta no WebSocket e também faz polling REST como fallback.

## Fluxo de execução (passo a passo)

### 1) Inicialização (bootstrap)

1. `run.bat`/`run.sh` muda para o diretório do bot e executa `server.py`.
2. `server.py`:
   - configura logging em arquivo `arbitrage-bot/logs/bot_YYYYmmdd_HHMMSS.log` + stdout;
   - carrega `.env` (se existir);
   - lê variáveis e define defaults (modo, saldo inicial, porta, scan interval, etc.);
   - inicializa `BotServer`.

### 2) Seleção de fonte de dados (real vs simulado)

O bot tenta conectar exchanges via `ccxt` (dados públicos):

- se conectou em pelo menos uma exchange e consegue buscar ticker, o dashboard indicará **REAL**;
- se falhar (sem `ccxt`/sem internet/sem mercados), o bot cai automaticamente em **SIMULATED**.

O `HybridMarket` mantém estatísticas de uso real vs simulado e expõe isso ao dashboard (`data_quality`).

### 3) Loop principal (scanner)

O loop principal roda em uma thread daemon (`_engine_loop`) e repete a cada `SCAN_INTERVAL` segundos:

1. Atualiza preços do simulador (`market.tick()`), para manter movimento constante.
2. Para cada engine:
   - varre oportunidades (`scan_and_execute()`),
   - calcula custos estimados (fees/slippage/withdraw) conforme estratégia,
   - se passou no threshold e no risk-check, tenta “executar”.
3. Atualiza o estado do portfólio (equity curve) e eventos da engine.
4. Publica um `update` via WebSocket para clientes conectados.

## Configuração via `.env` (v3 / `server.py`)

Variáveis efetivamente usadas em `server.py`:

- **`TRADING_MODE`**: `"paper"` (default) ou `"live"`.
  - Na v3 atual, mesmo com `"live"`, a execução é **modelada/simulada** pelo `ExecutionModel` (não envia ordens reais via API keys).
- **`INITIAL_BALANCE`**: saldo inicial (float).
- **`PORT`**: porta do dashboard/API (default `8888`).
- **`SCAN_INTERVAL`**: intervalo do loop (default `0.5`).
- **`AGGRESSIVE`**: `"true"`/`"false"` (default `true`).
  - altera thresholds e limites de risco (mais trades, menor filtro).

O `.env` do repositório também lista chaves `BINANCE_API_KEY`, `BYBIT_API_KEY`, etc., mas **a v3 (`server.py`) não usa essas chaves** para preço (dados públicos) nem para execução real de ordens.

## Estratégias (como cada engine decide e “executa”)

### 1) Cross-Exchange (`cross_exchange`)

Objetivo: encontrar, para um mesmo par (ex.: `BTC/USDT`), uma exchange para comprar barato e outra para vender caro.

Como decide:

- coleta tickers do par em todas as exchanges disponíveis (`get_all_tickers`);
- escolhe:
  - **buy_exchange** = menor `ask`,
  - **sell_exchange** = maior `bid`;
- calcula:
  - `raw_spread = (sell - buy) / buy * 100`;
  - custos estimados:
    - slippage (compra + venda),
    - fees taker (compra + venda),
    - “withdrawal fee” aproximada (convertida para % do trade);
  - `net_spread = raw_spread - est_cost_pct`;
- só considera se `net_spread` > `MIN_SPREAD` (agressivo: menor).

Execução:

- usa o `ExecutionModel.execute_order()` duas vezes (buy e sell),
- aplica drift/latência/slippage/fees,
- abre e fecha trade instantaneamente no `Portfolio`.

### 2) Triangular (`triangular`)

Objetivo: ganhar no ciclo de 3 pares (ex.: `BTC/USDT → ETH/BTC → ETH/USDT`).

Como decide:

- usa preços simulados para os pares “cross” (ex.: `ETH/BTC`) e ticker real/simulado para legs em USDT;
- estima lucro do ciclo, desconta fees e slippage modelados;
- se lucro líquido > `MIN_PROFIT`, vira oportunidade.

Execução:

- modela uma entrada e saída com um lucro “realizado” aleatorizado (para simular fill).

### 3) Statistical (`statistical`)

Objetivo: identificar desvio estatístico entre 2 ativos correlacionados (pairs trading) via z-score do ratio de preços.

Como decide:

- mantém histórico do ratio `last(pa)/last(pb)`;
- calcula média, desvio e z-score;
- entra quando `|z| > Z_ENTRY`, sai quando `|z| < Z_EXIT`.

Execução:

- abre posição (buy ou sell) no ativo A (simplificado) e fecha quando reverte;
- P&L vem da diferença de preço do ativo negociado (modelo simplificado).

### 4) Funding Rate (`funding_rate`)

Objetivo: capturar funding rate de perp (ex.: BTC/USDT swap).

Como decide:

- busca funding via `ccxt` (quando disponível) ou gera via ruído;
- se `|rate| >= MIN_RATE`, registra oportunidade.

Execução:

- abre uma posição “buy” simplificada e fecha após alguns ticks;
- soma um componente extra `funding_pnl` aproximado.

### 5) DEX vs CEX (`dex_cex`)

Objetivo: capturar discrepância de preço entre um DEX e um CEX.

Como decide:

- usa preço do CEX (binance) como base e aplica um offset estocástico para o “DEX price”;
- calcula spread nos dois sentidos;
- desconta:
  - fee DEX + fee CEX,
  - slippage (2 lados),
  - gas cost fixo (`GAS_COST`) como %;
- se `net_spread` > `MIN_SPREAD`, vira oportunidade.

Execução:

- executa buy e sell com `ExecutionModel` nos “venues” `dex` e `binance`,
- desconta gas no fechamento.

## Risk management (o que pode bloquear trades)

O risco depende de `AGGRESSIVE`:

- **Normal**: limites mais restritos (drawdown, open positions, daily loss, cooldown maior).
- **Aggressive**: limites ampliados e thresholds menores, além de cooldown curto.

Checagens principais (`BaseEngine._risk_ok()`):

- máximo de posições abertas (`max_open_positions`);
- limite de perda diária (`max_daily_loss_usd`);
- cooldown após perda (por engine);
- drawdown (aplicado de forma diferente entre normal/agressivo).

## Persistência (SQLite: `arbitrage.db`)

O banco é inicializado automaticamente em um caminho gravável; preferencialmente:

- `arbitrage-bot/arbitrage.db` (no diretório do bot)

Tabelas:

- **`trades`**: histórico de trades (entrada/saída, fees, slippage, latency, pnl, status, modo, `data_source` real/sim).
- **`equity_snapshots`**: snapshots de equity/balance/open_positions.
- **`opportunities`**: oportunidades encontradas (payload em JSON).
- **`sessions`**: metadados da sessão (config, modo, etc.).

## Servidor / API / WebSocket / Dashboard

### Endpoints HTTP

- **`GET /`**: serve `dashboard/index.html`.
- **`GET /api/...`**: retorna o mesmo payload de estado (JSON) que o dashboard usa.
  - Observação: a v3 responde qualquer rota `/api/*` com o estado atual (não separa por recurso).

### WebSocket (tempo real)

O servidor implementa o handshake RFC6455 e mantém clientes conectados:

- ao conectar, envia `{"type":"init","data": ... }`
- continuamente envia `{"type":"update","data": ... }`
- aceita comando:
  - `{"action":"toggle_engine","engine":"cross_exchange"}` para ligar/desligar engine.

### Frontend (dashboard)

`dashboard/index.html`:

- tenta conectar em `ws://<host>/ws`;
- se o WebSocket cair, reconecta; e também faz polling em `GET /api/status` a cada 3s como fallback;
- exibe KPIs (balance, pnl, ROI, win rate, trades, drawdown, runtime, fees, slippage, latency, profit factor, sharpe);
- mostra “Data Source Quality” (percentual real vs simulado) e “AGGRESSIVE” quando ativo;
- permite toggle de engines.

## Logs

Os logs ficam em `arbitrage-bot/logs/` com o padrão:

- `bot_YYYYmmdd_HHMMSS.log`

Eles registram:

- conexão com exchanges reais (`[REAL] ... connected`),
- avisos de rate limit, falha de execução, e erros em engines,
- mensagens periódicas do loop com saldo e número de trades.

## Observações importantes (limites do projeto atual)

- **Execução real de ordens**: a implementação v3 em `server.py` é uma **simulação realista**, não um executor “live” com API keys.
- **Dados reais sem API keys**: os tickers vêm de endpoints públicos via `ccxt` (quando disponível).
- **Agressivo por padrão**: `AGGRESSIVE=true` reduz filtros e aumenta frequência de tentativas.

## Versão alternativa (FastAPI / modular)

Além da v3 monolítica, existe uma implementação modular baseada em FastAPI:

- `main.py` (FastAPI + WebSocket) + `config.py` + `exchange/connector.py` + `engines/*` + `utils/portfolio.py`.
- Essa versão expõe:
  - `GET /api/status`, `GET /api/trades`, `POST /api/engine/{engine}/toggle`, `GET /ws`, etc.

Porém, **os scripts `run.bat`/`run.sh` atuais iniciam `server.py`**, então a operação “real” do bot (como está hoje) é a descrita neste documento.

## Troubleshooting rápido

- **Dashboard não abre**: confirme que o processo está rodando e que `PORT` não está em uso.
- **Sem dados reais**: instale `ccxt` (`pip install ccxt`) e verifique internet; o bot cai em simulação automaticamente.
- **Sem trades**: em modo normal, thresholds podem estar altos; em modo agressivo, ainda pode acontecer se custos estimados superarem o spread.

