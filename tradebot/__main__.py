"""Command line: ``python -m tradebot <command>``."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .backtest import format_report, run_backtest
from .broker import load_state
from .config import Config, ConfigError, load_config
from .data import load_csv, save_csv, synthetic_ohlcv

DEFAULT_CONFIG = "config.yaml"


def _config(path: str | None) -> Config:
    if path is not None:
        return load_config(path)
    if Path(DEFAULT_CONFIG).exists():
        return load_config(DEFAULT_CONFIG)
    logging.getLogger("tradebot").warning("no %s found, using built-in defaults", DEFAULT_CONFIG)
    return load_config(None)


def _market(cfg: Config):
    from .market import ExchangeMarketData

    return ExchangeMarketData(cfg.exchange)


def cmd_backtest(args, cfg: Config) -> int:
    if args.csv:
        sets = [(args.symbol or Path(args.csv).stem, load_csv(args.csv))]
    elif args.synthetic:
        sets = [(args.symbol or "SYNTHETIC", synthetic_ohlcv(timeframe=cfg.timeframe))]
        print("Synthetic prices: this only checks the pipeline works, not that the strategy makes money.\n")
    else:
        market = _market(cfg)
        until = datetime.now(timezone.utc)
        since = until - timedelta(days=args.days)
        symbols = [args.symbol] if args.symbol else cfg.symbols
        sets = [(s, market.fetch_history(s, cfg.timeframe, since, until)) for s in symbols]

    for symbol, candles in sets:
        print(format_report(run_backtest(candles, cfg, symbol)))
        print()
    return 0


def cmd_fetch(args, cfg: Config) -> int:
    until = datetime.now(timezone.utc)
    candles = _market(cfg).fetch_history(args.symbol, cfg.timeframe, until - timedelta(days=args.days), until)
    save_csv(candles, args.out)
    print(f"saved {len(candles)} {cfg.timeframe} candles of {args.symbol} to {args.out}")
    return 0


def cmd_paper(args, cfg: Config) -> int:
    from .runner import PaperTrader

    trader = PaperTrader(cfg, _market(cfg))
    print(f"PAPER TRADING {', '.join(cfg.symbols)} on {cfg.exchange} ({cfg.timeframe} candles). Simulated money only. Ctrl-C to stop.")
    try:
        trader.run(max_steps=1 if args.once else None)
    except KeyboardInterrupt:
        print("\nstopped; account saved to", cfg.state_file)
    return 0


def cmd_status(args, cfg: Config) -> int:
    state = load_state(cfg.state_file, cfg.starting_cash)
    prices: dict[str, float] = {}
    if state.positions:
        try:
            market = _market(cfg)
            prices = {s: market.fetch_price(s) for s in state.positions}
        except Exception as exc:  # status should still print offline
            print(f"(could not fetch live prices: {exc})")
    value = state.cash
    print(f"cash            {state.cash:,.2f}")
    for symbol, pos in state.positions.items():
        price = prices.get(symbol, pos.entry_price)
        value += pos.qty * price
        print(f"{symbol:<15} qty {pos.qty:.6g} entry {pos.entry_price:.4f} now {price:.4f} stop {pos.stop_price:.4f} pnl {pos.qty * price - pos.cost:+,.2f}")
    print(f"equity          {value:,.2f}  (started with {cfg.starting_cash:,.2f}, {value / cfg.starting_cash - 1:+.2%})")
    if state.halted:
        print(f"HALTED: {state.halt_reason}")
    return 0


def cmd_reset(args, cfg: Config) -> int:
    if not args.yes:
        print("This deletes the paper account and trade log. Re-run with --yes to confirm.")
        return 1
    for path in (Path(cfg.state_file), Path(cfg.trade_log)):
        path.unlink(missing_ok=True)
    print(f"paper account reset to {cfg.starting_cash:,.2f}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tradebot", description="Paper-trading bot for crypto and tokenised gold. Simulated money only.")
    parser.add_argument("--config", help=f"YAML config file (default: {DEFAULT_CONFIG})")
    sub = parser.add_subparsers(dest="command", required=True)

    bt = sub.add_parser("backtest", help="replay history through the strategy")
    source = bt.add_mutually_exclusive_group()
    source.add_argument("--csv", help="candles saved by `fetch` (default: download from the exchange)")
    source.add_argument("--synthetic", action="store_true", help="random prices; checks the pipeline only")
    bt.add_argument("--symbol", help="default: every symbol in the config")
    bt.add_argument("--days", type=int, default=365, help="history to download (default 365)")

    fetch = sub.add_parser("fetch", help="download candles to a CSV file")
    fetch.add_argument("--symbol", required=True)
    fetch.add_argument("--days", type=int, default=365)
    fetch.add_argument("--out", required=True)

    paper = sub.add_parser("paper", help="trade live prices with simulated money")
    paper.add_argument("--once", action="store_true", help="run a single step and exit")

    sub.add_parser("status", help="show the paper account")

    reset = sub.add_parser("reset", help="delete the paper account and start over")
    reset.add_argument("--yes", action="store_true")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        cfg = _config(args.config)
    except (ConfigError, FileNotFoundError) as exc:
        print(exc, file=sys.stderr)
        return 2

    commands = {"backtest": cmd_backtest, "fetch": cmd_fetch, "paper": cmd_paper, "status": cmd_status, "reset": cmd_reset}
    try:
        return commands[args.command](args, cfg)
    except Exception as exc:
        if type(exc).__module__.startswith("ccxt"):
            print(f"exchange error: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        raise


if __name__ == "__main__":
    sys.exit(main())
