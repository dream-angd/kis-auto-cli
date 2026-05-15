"""백테스트 결과 출력 및 파일 저장 모듈."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from src.backtester import BacktestResult, TradeRecord
from src.config import get_logs_dir


def print_summary(result: BacktestResult) -> None:
    """백테스트 결과를 콘솔에 출력한다."""
    m = result.metrics
    sep = "=" * 60

    print(f"\n{sep}")
    print(f"  백테스트 결과 — {result.stock_code}  ({result.start} ~ {result.end})")
    print(sep)
    print(f"  초기 자본금   : {result.initial_capital:>14,.0f} 원")
    print(f"  최종 자본금   : {m['final_capital']:>14,.0f} 원")
    pnl = m["total_pnl"]
    sign = "+" if pnl >= 0 else ""
    print(f"  실현 손익     : {sign}{pnl:>13,.0f} 원")
    ret = m["total_return_pct"]
    sign = "+" if ret >= 0 else ""
    print(f"  총 수익률     : {sign}{ret:.2f}%")
    print(f"  최대 낙폭     : -{m['max_drawdown_pct']:.2f}%")
    print(f"  샤프 비율     : {m['sharpe_ratio']:.3f}")
    print()
    print(f"  총 매도 건수  : {m['total_trades']} 건")
    print(f"  승률          : {m['win_rate']:.1f}%  ({m['win_count']}승 / {m['loss_count']}패)")
    pf = m["profit_factor"]
    pf_str = f"{pf:.3f}" if pf is not None else "N/A"
    print(f"  Profit Factor : {pf_str}")
    print(f"{sep}\n")


def save_csv(trades: list[TradeRecord], path: Path) -> None:
    """거래 내역을 CSV로 저장한다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["date", "action", "price", "qty", "amount", "fee", "pnl", "reason"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for t in trades:
            writer.writerow({
                "date": t.date,
                "action": t.action,
                "price": t.price,
                "qty": t.qty,
                "amount": round(t.amount, 0),
                "fee": round(t.fee, 2),
                "pnl": round(t.pnl, 2),
                "reason": t.reason,
            })


def save_json(result: BacktestResult, path: Path) -> None:
    """성과 지표를 JSON으로 저장한다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "stock_code": result.stock_code,
        "start": result.start,
        "end": result.end,
        "metrics": result.metrics,
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def generate_report(result: BacktestResult) -> tuple[Path, Path]:
    """콘솔 출력 + CSV/JSON 파일을 생성하고 파일 경로를 반환한다."""
    print_summary(result)

    tag = f"{result.stock_code}_{result.start}_{result.end}"
    logs_dir = get_logs_dir()
    csv_path = logs_dir / f"backtest_{tag}.csv"
    json_path = logs_dir / f"backtest_{tag}.json"

    save_csv(result.trades, csv_path)
    save_json(result, json_path)

    return csv_path, json_path
