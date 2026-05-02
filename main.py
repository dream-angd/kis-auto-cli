import argparse
import sys

from src.auth import get_mode
from src.logger import log_info


def cmd_run(args):
    print(f"\n  MODE = {get_mode().upper()}")
    print(f"  {'[!] 실전 투자 모드입니다!' if get_mode() == 'real' else '모의 투자 모드입니다.'}\n")

    from src.scheduler import run_loop
    run_loop(interval_sec=args.interval)


def cmd_status(args):
    from src.trader import get_account_info

    balance, holdings = get_account_info()
    print("\n=== 계좌 현황 ===")
    print(f"  총 평가금액: {balance['total_eval']:>15,}원")
    print(f"  예수금:      {balance['cash']:>15,}원")
    print(f"  평가손익:    {balance['profit_loss']:>15,}원")
    if holdings:
        print("\n=== 보유 종목 ===")
        print(f"  {'종목명':<12} {'수량':>6} {'평균가':>10} {'현재가':>10} {'수익률':>8} {'손익':>12}")
        print("  " + "-" * 64)
        for h in holdings:
            print(f"  {h['stock_name']:<12} {h['quantity']:>6} {h['avg_price']:>10,} {h['current_price']:>10,} {h['profit_rate']:>7.1f}% {h['profit_loss']:>11,}원")
    else:
        print("\n  보유 종목 없음")
    print()


def cmd_history(args):
    from pathlib import Path
    from datetime import datetime
    import csv

    date_str = args.date if args.date else datetime.now().strftime("%Y%m%d")
    csv_path = Path(__file__).parent / "logs" / f"trades_{date_str}.csv"

    if not csv_path.exists():
        print(f"\n  {date_str} 매매 이력 없음\n")
        return

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        print(f"\n  {date_str} 매매 이력 없음\n")
        return

    print(f"\n=== 매매 이력 ({date_str}) ===")
    print(f"  {'시각':<20} {'종목':>8} {'구분':>4} {'가격':>10} {'수량':>6} {'금액':>12} {'사유'}")
    print("  " + "-" * 76)
    for r in rows:
        try:
            print(f"  {r.get('datetime',''):>20} {r.get('stock_code',''):>8} {r.get('action',''):>4} {int(r.get('price',0)):>10,} {int(r.get('quantity',0)):>6} {int(r.get('amount',0)):>11,}원 {r.get('reason','')}")
        except (ValueError, KeyError):
            continue
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
        description="KIS 자동매매 CLI",
    )
    sub = parser.add_subparsers(dest="command")

    p_run = sub.add_parser("run", help="자동매매 시작")
    p_run.add_argument("--interval", type=int, default=300, help="실행 간격 (초, 기본 300)")
    p_run.set_defaults(func=cmd_run)

    p_status = sub.add_parser("status", help="잔고/보유 종목 출력")
    p_status.set_defaults(func=cmd_status)

    p_history = sub.add_parser("history", help="매매 이력 출력")
    p_history.add_argument("--date", default=None, metavar="YYYYMMDD", help="조회 날짜 (기본: 오늘)")
    p_history.set_defaults(func=cmd_history)

    p_analyze = sub.add_parser("analyze", help="종목 분석")
    p_analyze.add_argument("code", help="종목코드 (예: 005930)")
    p_analyze.set_defaults(func=cmd_analyze)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
