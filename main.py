import argparse
import csv
import sys
from datetime import datetime
from pathlib import Path

from src.auth import get_mode


def _print_mode():
    mode = get_mode()
    print(f"\n  MODE = {mode.upper()}")
    if mode == "real":
        print("  [!] Real trading mode. Orders can use real money.\n")
    else:
        print("  Mock trading mode.\n")


def cmd_run(args):
    _print_mode()

    from src.scheduler import run_loop
    run_loop(interval_sec=args.interval)


def cmd_run_all(args):
    _print_mode()

    from src.combined import run_all_loop
    run_all_loop(
        swing_interval_sec=args.swing_interval,
        scalp_stock=args.scalp_code,
        scalp_interval_sec=args.scalp_interval,
    )


def cmd_scalp(args):
    _print_mode()

    from src.combined import run_scalp_loop
    run_scalp_loop(
        scalp_stock=args.code,
        scalp_interval_sec=args.interval,
    )


def cmd_status(args):
    from src.trader import get_account_info

    balance, holdings = get_account_info()
    print("\n=== Account ===")
    print(f"  Total eval: {balance['total_eval']:>15,} KRW")
    print(f"  Cash:       {balance['cash']:>15,} KRW")
    print(f"  P/L:        {balance['profit_loss']:>15,} KRW")

    if holdings:
        print("\n=== Holdings ===")
        print(f"  {'Name':<12} {'Qty':>6} {'Avg':>10} {'Price':>10} {'P/L%':>8} {'P/L':>12}")
        print("  " + "-" * 64)
        for h in holdings:
            print(
                f"  {h['stock_name']:<12} {h['quantity']:>6} "
                f"{h['avg_price']:>10,} {h['current_price']:>10,} "
                f"{h['profit_rate']:>7.1f}% {h['profit_loss']:>11,} KRW"
            )
    else:
        print("\n  No holdings")
    print()


def cmd_history(args):
    today = datetime.now().strftime("%Y%m%d")
    csv_path = Path(__file__).parent / "logs" / f"trades_{today}.csv"

    if not csv_path.exists():
        print("\n  No trades today\n")
        return

    with open(csv_path, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        print("\n  No trades today\n")
        return

    print(f"\n=== Trade history ({today}) ===")
    print(f"  {'Time':<20} {'Code':>8} {'Action':>10} {'Price':>10} {'Qty':>6} {'Amount':>12} Reason")
    print("  " + "-" * 92)
    for r in rows:
        try:
            print(
                f"  {r.get('datetime', ''):<20} {r.get('stock_code', ''):>8} "
                f"{r.get('action', ''):>10} {int(r.get('price', 0)):>10,} "
                f"{int(r.get('quantity', 0)):>6} {int(r.get('amount', 0)):>11,} "
                f"{r.get('reason', '')}"
            )
        except (ValueError, KeyError):
            continue
    print()


def cmd_analyze(args):
    from src.analyzer import analyze

    code = args.code
    print(f"\n=== Analyze {code} ===")
    result = analyze(code)
    print(f"  Signal: {result['signal']}")
    print(f"  Price:  {result['current_price']:,} KRW")
    print(f"  Reason: {result['reason']}")
    print()


def main():
    parser = argparse.ArgumentParser(
        prog="kis-trader",
        description="KIS auto trading CLI",
    )
    sub = parser.add_subparsers(dest="command")

    p_run = sub.add_parser("run", help="start swing strategy")
    p_run.add_argument("--interval", type=int, default=300, help="swing interval seconds")
    p_run.set_defaults(func=cmd_run)

    p_run_all = sub.add_parser("run-all", help="start swing + scalp strategies in one process")
    p_run_all.add_argument("--swing-interval", type=int, default=300, help="swing interval seconds")
    p_run_all.add_argument("--scalp-code", default=None, help="stock code for scalp strategy")
    p_run_all.add_argument("--scalp-interval", type=float, default=None, help="scalp interval seconds")
    p_run_all.set_defaults(func=cmd_run_all)

    p_scalp = sub.add_parser("scalp", help="start scalp strategy only")
    p_scalp.add_argument("code", nargs="?", default=None, help="stock code")
    p_scalp.add_argument("--interval", type=float, default=None, help="scalp interval seconds")
    p_scalp.set_defaults(func=cmd_scalp)

    p_status = sub.add_parser("status", help="show account and holdings")
    p_status.set_defaults(func=cmd_status)

    p_history = sub.add_parser("history", help="show today's trade history")
    p_history.set_defaults(func=cmd_history)

    p_analyze = sub.add_parser("analyze", help="analyze stock")
    p_analyze.add_argument("code", help="stock code, e.g. 005930")
    p_analyze.set_defaults(func=cmd_analyze)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
