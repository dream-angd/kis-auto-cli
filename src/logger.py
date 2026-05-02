import csv
import logging
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)

_logger = logging.getLogger("kis-trader")
_logger.setLevel(logging.DEBUG)

if not _logger.handlers:
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("[%(asctime)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    _logger.addHandler(ch)

    fh = TimedRotatingFileHandler(
        LOGS_DIR / "error.log",
        when="midnight",
        backupCount=30,
        encoding="utf-8",
    )
    fh.setLevel(logging.ERROR)
    fh.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s %(message)s"))
    fh.suffix = "%Y%m%d"
    _logger.addHandler(fh)


def log_info(msg):
    _logger.info(msg)


def log_error(msg):
    _logger.error(msg)


def log_trade(stock_code, action, price, quantity, amount, reason=""):
    log_info(
        f"{stock_code} | action={action} | price={price:,} | "
        f"qty={quantity} | amount={amount:,} | {reason}"
    )

    today = datetime.now().strftime("%Y%m%d")
    csv_path = LOGS_DIR / f"trades_{today}.csv"
    write_header = not csv_path.exists()

    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(["datetime", "stock_code", "action", "price", "quantity", "amount", "reason"])
        writer.writerow([
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            stock_code,
            action,
            price,
            quantity,
            amount,
            reason,
        ])


def log_signal(stock_code, signal, price, reason=""):
    log_info(f"{stock_code} | signal={signal} | price={price:,} | reason={reason}")
