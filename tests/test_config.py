import pytest
from src import config


def test_get_mode_default(monkeypatch):
    monkeypatch.delenv("MODE", raising=False)
    assert config.get_mode() == "mock"


def test_get_mode_real(monkeypatch):
    monkeypatch.setenv("MODE", "real")
    assert config.get_mode() == "real"


def test_get_max_buy_amount_default(monkeypatch):
    monkeypatch.delenv("MAX_BUY_AMOUNT", raising=False)
    assert config.get_max_buy_amount() == 500000


def test_get_max_buy_amount_custom(monkeypatch):
    monkeypatch.setenv("MAX_BUY_AMOUNT", "1000000")
    assert config.get_max_buy_amount() == 1000000


def test_get_atr_multiplier_default(monkeypatch):
    monkeypatch.delenv("ATR_MULTIPLIER", raising=False)
    assert config.get_atr_multiplier() == pytest.approx(2.0)


def test_get_atr_multiplier_custom(monkeypatch):
    monkeypatch.setenv("ATR_MULTIPLIER", "3.0")
    assert config.get_atr_multiplier() == pytest.approx(3.0)


def test_get_atr_risk_pct_default(monkeypatch):
    monkeypatch.delenv("ATR_RISK_PCT", raising=False)
    assert config.get_atr_risk_pct() == pytest.approx(0.01)


def test_get_atr_risk_pct_custom(monkeypatch):
    monkeypatch.setenv("ATR_RISK_PCT", "0.02")
    assert config.get_atr_risk_pct() == pytest.approx(0.02)


def test_get_account_no_valid_mock(monkeypatch):
    monkeypatch.setenv("MODE", "mock")
    monkeypatch.setenv("KIS_MOCK_ACCOUNT_NO", "44407084-01")
    cano, acnt = config.get_account_no()
    assert cano == "44407084"
    assert acnt == "01"


def test_get_account_no_valid_real(monkeypatch):
    monkeypatch.setenv("MODE", "real")
    monkeypatch.setenv("KIS_ACCOUNT_NO", "12345678-01")
    cano, acnt = config.get_account_no()
    assert cano == "12345678"
    assert acnt == "01"


def test_get_account_no_invalid(monkeypatch):
    monkeypatch.setenv("MODE", "mock")
    monkeypatch.setenv("KIS_MOCK_ACCOUNT_NO", "invalid_no_dash")
    monkeypatch.delenv("KIS_ACCOUNT_NO", raising=False)
    with pytest.raises(ValueError):
        config.get_account_no()


def test_get_stop_loss_pct_default(monkeypatch):
    monkeypatch.delenv("STOP_LOSS_PCT", raising=False)
    assert config.get_stop_loss_pct() == pytest.approx(-3.0)


def test_get_take_profit_pct_default(monkeypatch):
    monkeypatch.delenv("TAKE_PROFIT_PCT", raising=False)
    assert config.get_take_profit_pct() == pytest.approx(5.0)


def test_get_max_daily_loss_default(monkeypatch):
    monkeypatch.delenv("MAX_DAILY_LOSS", raising=False)
    assert config.get_max_daily_loss() == pytest.approx(100000.0)


def test_get_max_consecutive_losses_default(monkeypatch):
    monkeypatch.delenv("MAX_CONSECUTIVE_LOSSES", raising=False)
    assert config.get_max_consecutive_losses() == 3


def test_get_target_stocks(monkeypatch):
    monkeypatch.setenv("TARGET_STOCKS", "005930,000660,035720")
    stocks = config.get_target_stocks()
    assert stocks == ["005930", "000660", "035720"]


def test_get_target_stocks_empty(monkeypatch):
    monkeypatch.setenv("TARGET_STOCKS", "")
    assert config.get_target_stocks() == []
