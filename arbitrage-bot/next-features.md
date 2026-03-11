# Próximas Funcionalidades

---

## USABILIDADE

A maior limitação hoje é que quase tudo exige editar código Python ou o `.env` e reiniciar o bot. Melhorias nessa frente:

- **Painel de configuração em tempo real** — Ajustar min spread, z-score, hold ticks, position size, limites de risco direto no dashboard, sem reiniciar.
- **Notificações** — Alertas via Discord/Telegram quando: kill switch ativado, loss diária atingida, trade grande executado, ou erro de conexão com exchange. Hoje não há como saber o que acontece sem estar olhando o dashboard.
- **Export de dados** — Botão para baixar CSV/PDF dos trades, equity curve e performance mensal. Hoje os dados estão presos no SQLite.
- **Modo mobile** — O dashboard não é responsivo. Adaptá-lo para funcionar bem no celular permitiria monitorar a qualquer momento.
- **Logs visíveis** — Um painel de logs no dashboard mostrando erros, warnings, conexões com exchanges. Hoje os logs só aparecem no terminal.
- **Shutdown gracioso** — Ao fechar o bot, fechar automaticamente todas as posições abertas antes de encerrar, em vez de deixá-las penduradas.

---

## FUNCIONALIDADES DE TRADING

- **Stop Loss e Take Profit por trade** — Hoje o Statistical espera o z-score reverter e o Funding Rate espera N ticks. Se o mercado desabar, não há proteção. Adicionar SL/TP configuráveis evitaria perdas grandes como as de -$8.58 que apareceram no DB.
- **Funding rates reais** — O engine de Funding Rate usa `random.gauss(0.01, 0.03)` como fallback. Conectar ao endpoint real de funding do Binance Futures via CCXT (`fetch_funding_rate()`) daria sinais muito mais confiáveis.
- **Verificação de liquidez** — Antes de executar, consultar a profundidade real do orderbook. Hoje assume bid/ask sem verificar se o volume suporta o trade size.
- **Smart Order Routing** — Em vez de executar sempre na Binance, escolher dinamicamente a exchange com menor fee + melhor preço + maior liquidez para cada trade.
- **Position sizing adaptativo** — Em vez de fixo 5% do balance, escalar com a volatilidade: mercado calmo = posição maior, mercado volátil = posição menor.
- **Máximo de holding time** — O Statistical pode ficar com posição aberta indefinidamente se o z-score não reverter. Adicionar um timeout (ex: fechar após 60 ticks mesmo sem revert).

---

## ANÁLISE E REPORTING

- **Gráfico de drawdown** — Além do equity curve, mostrar o drawdown ao longo do tempo para visualizar períodos de perda.
- **Rolling Sharpe / Profit Factor** — Métricas janeladas (últimas 50 trades, última hora) em vez de apenas acumuladas desde o início.
- **Atribuição de performance** — Entender se o lucro veio de edge real ou apenas do mercado ter subido. Comparar PnL do bot vs buy & hold.
- **Backtesting** — Permitir rodar as estratégias contra dados históricos para otimizar parâmetros antes de usar dinheiro real.
- **Relatório tributário** — Cálculo automático de ganho de capital por período, útil para declaração de IR (especialmente relevante no Brasil com a regra de R$35k/mês).

---

## INFRAESTRUTURA

- **Backup automático do DB** — Se o SQLite corromper, perde-se todo o histórico. Backup periódico para um segundo arquivo.
- **Reconexão automática** — Se a API de uma exchange cair, tentar reconectar automaticamente em vez de simplesmente falhar silenciosamente.
- **Multi-instância** — Rodar bots com configurações diferentes (um conservador, um agressivo) e comparar performance em dashboard unificado.
