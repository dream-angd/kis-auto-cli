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
    date_str = args.date if args.date else datetime.now().strftime("%Y%m%d")
    csv_path = Path(__file__).parent / "logs" / f"trades_{date_str}.csv"

    if not csv_path.exists():
        print(f"\n  {date_str} 매매 이력 없음\n")
        return

    with open(csv_path, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        print(f"\n  {date_str} 매매 이력 없음\n")
        return

    print(f"\n=== 매매 이력 ({date_str}) ===")
    print(f"  {'시각':<20} {'종목':>8} {'구분':>4} {'가격':>10} {'수량':>6} {'금액':>12} {'사유'}")
    print("  " + "-" * 76)
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


def cmd_report(args):
    from datetime import datetime
    from src.reporter import generate_daily_report

    date_str = args.date if args.date else datetime.now().strftime("%Y%m%d")
    display_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
    print(f"\n=== 리포트 생성 ({display_date}) ===")
    try:
        paths = generate_daily_report(date_str)
        for p in paths:
            print(f"  생성: {p}")
    except Exception as e:
        print(f"  오류: {e}", file=sys.stderr)
    print()


def cmd_analyze(args):
    from src.analyzer import analyze
    from src.trader import get_holdings

    code = args.code
    print(f"\n=== {code} 분석 ===")

    avg_price = 0
    try:
        for h in get_holdings():
            if h["stock_code"] == code:
                avg_price = h["avg_price"]
                print(f"  보유중 - 평균매입가: {avg_price:,}원")
                break
    except Exception:
        pass

    result = analyze(code, avg_price=avg_price)
    signal_emoji = {"BUY": "[매수]", "SELL": "[매도]", "HOLD": "[대기]"}
    print(f"  신호:   {signal_emoji.get(result['signal'], '')} {result['signal']}")
    print(f"  현재가: {result['current_price']:,}원")
    print(f"  사유:   {result['reason']}")
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

    p_history = sub.add_parser("history", help="매매 이력 출력")
    p_history.add_argument("--date", default=None, metavar="YYYYMMDD", help="조회 날짜 (기본: 오늘)")
    p_history.set_defaults(func=cmd_history)

    p_analyze = sub.add_parser("analyze", help="analyze stock")
    p_analyze.add_argument("code", help="stock code, e.g. 005930")
    p_analyze.set_defaults(func=cmd_analyze)

    p_report = sub.add_parser("report", help="일별 리포트 (재)생성")
    p_report.add_argument("--date", default=None, metavar="YYYYMMDD", help="대상 날짜 (기본: 오늘)")
    p_report.set_defaults(func=cmd_report)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
