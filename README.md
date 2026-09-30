# crypto_gold_trading-bot

A **paper-trading** bot for crypto (BTC) and tokenised gold (PAXG). It reads real
market prices from an exchange's public API and trades **simulated money** with
fees, slippage, stop losses and loss limits applied.

There is no real-money mode. The config rejects anything other than
`mode: paper`, and no code in this repo takes API keys or places exchange
orders. Going live has to be a deliberate code change made after the paper
results earn it (see [Before real money](#before-real-money)).

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python -m tradebot backtest --synthetic   # offline check that everything runs
python -m tradebot backtest --days 365    # replay the last year of real candles
python -m tradebot paper                  # paper trade live prices (Ctrl-C stops)
python -m tradebot status                 # cash, positions, P&L
python -m pytest                          # tests
```

`paper` keeps running until you stop it. For it to trade around the clock,
run it on a machine that stays on (a small VPS, or `tmux`/`screen` on a home
server). Stopping and restarting is safe: the account lives in
`state/paper_account.json` and every fill is appended to `state/trades.csv`.

## Commands

| Command | What it does |
|---|---|
| `backtest [--days N] [--symbol S]` | Downloads history and replays it through the strategy |
| `backtest --csv file.csv` | Same, from a file saved by `fetch` (repeatable, no network) |
| `backtest --synthetic` | Random prices; proves the pipeline runs, says nothing about profit |
| `fetch --symbol S --days N --out file.csv` | Saves candles for offline backtests |
| `paper [--once]` | Live prices, simulated fills. `--once` runs one step (handy for cron) |
| `status` | Shows the paper account |
| `reset --yes` | Deletes the paper account and trade log |

All commands take `--config path.yaml` (default `config.yaml`).

## How it trades

- **Strategy** (`tradebot/strategy.py`): moving-average crossover. Buy when the
  20-candle average crosses above the 50-candle average; exit when it falls back
  below. Long only, no leverage. This is a baseline to measure against, not
  a money-maker.
- **Decisions use closed candles only.** The still-forming candle is dropped,
  and the backtest fills each signal at the *next* candle's open, so the
  backtest never sees a price the live bot couldn't have seen. Tests cover this.
- **Risk** (`tradebot/risk.py`, all in `config.yaml`):
  - Position size: lose about 1% of equity if the 3% stop is hit, and at most
    25% of equity in any one symbol.
  - Daily loss limit: after -3% in a UTC day, no new entries.
  - Kill switch: at -15% from the equity peak, sell everything and halt until
    you run `reset --yes`.
- **Costs**: 0.1% fee and 0.05% slippage on every fill.

## Gold

PAXG (PAX Gold) is a token backed by one troy ounce of physical gold per token,
so `PAXG/USDT` follows the gold price and trades 24/7 on crypto exchanges. For
Indian tax purposes it is still a crypto asset (see below), not gold.

The other routes to gold for Indian residents are GOLDBEES (NSE) or MCX gold
futures, both through an Indian broker's API. Offshore forex apps offering
XAUUSD are not a legal option for Indian residents.

## Before real money

Don't add a live mode until **every** box is ticked:

- [ ] Backtested over at least two years, covering both up and down markets
- [ ] Beats buy-and-hold after fees *on data you didn't tune the settings on*
- [ ] At least 4 weeks of `paper` trading, with results close to the backtest
- [ ] You understand every trade in `state/trades.csv` and why it happened
- [ ] Exchange API key is **trade-only**, with **withdrawals disabled** and an
      **IP whitelist**
- [ ] Keys live in a `.env` file on your machine, never in git or a chat
- [ ] Starting capital is money you can afford to lose entirely

## India notes (check with a CA; rules change)

- Gains on crypto (including PAXG) are taxed at a flat 30%, and losses can't be
  set off against other income.
- 1% TDS is deducted on each sale. A bot that trades often locks up capital in
  TDS until you file your return.
- Use an exchange registered with FIU-IND.

## Layout

```
tradebot/
  config.py     load + validate config.yaml (rejects anything but paper mode)
  data.py       candle frames, CSV, synthetic prices, closed-candle filter
  market.py     public market data via ccxt (no keys, no orders)
  strategy.py   moving-average crossover signals
  risk.py       position sizing, daily loss limit, drawdown kill switch
  broker.py     simulated account: fills, fees, slippage, saved state
  backtest.py   historical replay + stats
  runner.py     live paper-trading loop
tests/          pytest suite (no network needed)
```
