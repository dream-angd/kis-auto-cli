import csv
import logging
import threading
from logging.handlers import TimedRotatingFileHandler
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)

_file_lock = threading.Lock()

_logger = logging.getLogger("kis-trader")
_logger.setLevel(logging.DEBUG)

if not _logger.handlers:
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("[%(asctime)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    _logger.addHandler(ch)

    fh_info = TimedRotatingFileHandler(
        LOGS_DIR / "app.log", when="midnight", backupCount=30, encoding="utf-8"
    )
    fh_info.setLevel(logging.INFO)
    fh_info.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s %(message)s"))
    fh_info.suffix = "%Y%m%d"
    _logger.addHandler(fh_info)

    fh_err = TimedRotatingFileHandler(
        LOGS_DIR / "error.log", when="midnight", backupCount=30, encoding="utf-8"
    )
    fh_err.setLevel(logging.ERROR)
    fh_err.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s %(message)s"))
    fh_err.suffix = "%Y%m%d"
    _logger.addHandler(fh_err)


def log_info(msg: str) -> None:
    _logger.info(msg)


def log_error(msg: str) -> None:
    _logger.error(msg)

    today = datetime.now().strftime("%Y%m%d")
    sidecar_path = LOGS_DIR / f"raw_errors_{today}.log"
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{ts}\tERROR\t{msg}\n"

    with _file_lock:
        with open(sidecar_path, "a", encoding="utf-8") as f:
            f.write(line)


def log_trade(
    stock_code: str,
    action: str,
    price: int,
    quantity: int,
    amount: int,
    reason: str = "",
    pnl: float | None = None,
) -> None:
    log_info(f"{stock_code} | 신호: {action} | 가격: {price:,} | 수량: {quantity} | 금액: {amount:,} | {reason}")

    today = datetime.now().strftime("%Y%m%d")
    csv_path = LOGS_DIR / f"trades_{today}.csv"

    with _file_lock:
        write_header = not csv_path.exists()
        with open(csv_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if write_header:
                writer.writerow(["datetime", "stock_code", "action", "price", "quantity", "amount", "reason", "pnl"])
            writer.writerow([
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                stock_code,
                action,
                price,
                quantity,
                amount,
                reason,
                "" if pnl is None else pnl,
            ])


def log_signal(stock_code: str, signal: str, price: int, reason: str = "") -> None:
    action_str = {"BUY": "BUY ", "SELL": "SELL", "HOLD": "HOLD"}
    log_info(f"{stock_code} | 신호: {action_str.get(signal, signal)} | 가격: {price:,} | 결과: {reason}")

    today = datetime.now().strftime("%Y%m%d")
    sidecar_path = LOGS_DIR / f"raw_signals_{today}.log"
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{ts}\t{stock_code}\t{action_str.get(signal, signal)}\t{price}\t{reason}\n"

    with _file_lock:
        with open(sidecar_path, "a", encoding="utf-8") as f:
            f.write(line)
