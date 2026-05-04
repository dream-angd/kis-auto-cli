# Code Review Report — Final Pass

**Review Date:** 2026-05-02 (second pass, post-fix)
**Language:** Python
**Language-Specific Agent:** python-code-reviewer
**Design Document:** `specs/features/daily-report-logs/design.md`
**Changed Files:** 5 (`src/config.py`, `src/logger.py`, `src/scheduler.py`, `main.py`, `src/reporter.py` [new], `tests/test_reporter.py` [new], `tests/test_scheduler_report.py` [new])
**Review Method:** sequential (all 4 perspectives + Python Platform)
**Test Suite:** 86/86 PASS (confirmed by local run)

---

## Summary

| Level | Count |
|-------|-------|
| Critical | 0 |
| Important (Warning) | 3 |
| Minor (Suggestion) | 3 |

**Verdict:** APPROVE_WITH_NITS

---

## Design Conformance

- [x] Completion criteria implemented: PASS
- [x] Interface match: PASS (with one deliberate deviation documented below)
- [x] Exception handling implemented: PASS
- [x] Scope compliance: PASS

### Deliberate Deviation from Design Doc — Acceptable

Design doc (`design.md` §5, §12 task 7) specifies `_maybe_generate_report(started_at: datetime)` and states "`started_at` 파라미터를 받아 `run_meta`를 summary에 포함시킨다". The implementation drops the parameter entirely: `_maybe_generate_report() -> None` (scheduler.py:178).

This is **not a defect**. The implementation obtains `started_at` from `start_snapshot_YYYYMMDD.json` (set by `_snapshot_holdings_at_open()`), which is equivalent and actually more crash-resilient. The `started_at: datetime` variable captured at run_loop entry (scheduler.py:214) is unused, but that is harmless. The design doc itself describes this as the summary field source in section 5 (generate_daily_report comment). The deviation is self-consistent and fully tested.

---

## Critical Issues

None.

---

## Important Warnings

### [src/reporter.py:65] win_rate denominator uses total_sell_count but win_count/loss_count are counted only over pnl-available rows

- **Perspective:** Logic Validation
- **Problem:** When a day has mixed-version SELL records (some rows have `pnl`, some are `None` due to a mid-day restart with old code), `total_sell_count` counts all SELL rows while `win_count + loss_count` only counts rows where `pnl is not None`. The win_rate formula then produces a misleadingly low percentage, and `win_count + loss_count < total_sell_count` causes the summary to silently misrepresent reality (e.g., 1 win out of 2 SELL rows but one row has no pnl yields `50.0%` rather than `100%` of measured trades).

  Concrete example (confirmed by local test):
  ```
  trades = [{"action": "SELL", "pnl": 5000.0}, {"action": "SELL", "pnl": None}]
  → win_count=1, loss_count=0, total_sell_count=2, win_rate=50.0
  ```
  The denominator should be `len(pnl_values)` (rows that actually have pnl data), not `total_sell_count`, when computing win_rate in the partial-availability case.

- **Fix Suggestion:**
  ```python
  # reporter.py _calc_pnl_stats — line 70
  # Change:
  win_rate = (win_count / total_sell_count * 100.0) if total_sell_count > 0 else 0.0
  # To:
  pnl_count = len(pnl_values)
  win_rate = (win_count / pnl_count * 100.0) if pnl_count > 0 else 0.0
  ```
  Also add a `pnl_sell_count` key to the returned dict so `_format_summary` can display `(N/A행 제외 X건 기준)` when `pnl_count < total_sell_count`.

  Note: This edge case only occurs during partial-day restarts mixing old and new code versions. Low probability in practice, but the incorrect math is a real correctness issue.

---

### [src/reporter.py:146, 169] Silent `except Exception` in `_load_start_snapshot` and `_load_final_state`

- **Perspective:** Python Platform (check 8: bare except without logging)
- **Problem:** Both functions catch `Exception` silently and return `None`/default without any log output. A corrupt `start_snapshot_YYYYMMDD.json` or `state.json` will silently produce a summary with "알 수 없음" start time and zeroed risk state, giving the user no indication that data was lost. This passes the Python Platform checklist's spirit but violates the project's own `log_error` convention used everywhere else.

  ```python
  # _load_start_snapshot (line 144-147)
  try:
      return json.loads(path.read_text(encoding="utf-8"))
  except Exception:        # ← no log; user sees "알 수 없음" with no explanation
      return None
  ```

- **Fix Suggestion:**
  ```python
  from src.logger import log_error   # or pass logger as dependency

  except Exception as e:
      log_error(f"start_snapshot_{date_str}.json 파싱 실패 (무시): {e}")
      return None
  ```
  Same pattern for `_load_final_state`. This matches how `_snapshot_holdings_at_open` handles its own failures.

  Caveat: `reporter.py` deliberately avoids importing from `scheduler.py` (one-way dependency). Importing `log_error` from `logger.py` is already sanctioned by the design doc ("reporter → config, logger") so this is safe.

---

### [src/scheduler.py:214] `started_at` variable is captured but never used

- **Perspective:** Code Quality
- **Problem:** `started_at: datetime = datetime.now()` (scheduler.py:214) is assigned inside `run_loop` but is never passed to any function. The plan doc specifies it should be forwarded to `_maybe_generate_report(started_at)`, but the implementation dropped the parameter (see Deliberate Deviation note above). The unused variable adds reader confusion and will cause a linter warning.

- **Fix Suggestion:** Either remove the line entirely:
  ```python
  # Remove: started_at: datetime = datetime.now()
  ```
  Or add a brief comment to explain why it is retained for future use:
  ```python
  # NOTE: retained for future run_meta enrichment; currently sourced from start_snapshot
  started_at: datetime = datetime.now()  # noqa: F841
  ```
  The former is cleaner.

---

## Minor Suggestions

### [src/scheduler.py:38, 49, 74, 109, 204] Missing type annotations on pre-existing functions

- **Perspective:** Python Platform (check 1)
- **Problem:** `is_market_open`, `_check_holdings`, `_check_targets`, `_check_circuit_breaker`, `run_loop` all lack parameter/return type annotations. These are existing functions not changed by this PR, so they are reference notes only and do not affect verdict.

---

### [main.py:8, 16, 35, 66, 82] `cmd_*` functions lack type annotations

- **Perspective:** Python Platform (check 1)
- **Problem:** CLI handler functions have no `args: argparse.Namespace` or `-> None` annotation. Minor consistency issue since the rest of the new code is fully annotated.

---

### [src/reporter.py:430-431] Docstrings in `_parse_signals_log` and `_parse_errors_log` describe sidecar file as `signals_YYYYMMDD.log` / `errors_YYYYMMDD.log`

- **Perspective:** Code Quality
- **Problem:** The docstring at reporter.py:89 says `signals_YYYYMMDD.log 사이드카 파일을 파싱한다` and reporter.py:120 says `errors_YYYYMMDD.log 사이드카 파일을 파싱한다`, but the actual file names read are `raw_signals_YYYYMMDD.log` and `raw_errors_YYYYMMDD.log` (reporter.py:430-431). The docstrings describe the sidecar inputs by the old name while the output report files use the same root name. This creates reader confusion distinguishing sidecar (input) from report (output).

- **Fix Suggestion:** Update docstrings to:
  ```python
  def _parse_signals_log(log_path: Path) -> list[dict]:
      """raw_signals_YYYYMMDD.log 사이드카 파일(logger.py가 기록)을 파싱한다."""
  ```

---

## Verification of Previously Reported Fixes

### C-1/C-2: Sidecar file naming

CONFIRMED CORRECT.
- `src/logger.py:48` writes `raw_errors_{today}.log`
- `src/logger.py:94` writes `raw_signals_{today}.log`
- `src/reporter.py:430-431` reads `raw_signals_{date_str}.log` and `raw_errors_{date_str}.log`
- Report output files are `signals_{date_str}.log` and `errors_{date_str}.log` (no `raw_` prefix)
- Cross-file consistency is exact. No typos or separator mismatches.

### C-3: Dead `started_at` parameter removed from `_maybe_generate_report`

CONFIRMED. Function at scheduler.py:178 takes zero parameters: `def _maybe_generate_report() -> None`.
Called correctly at scheduler.py:255: `_maybe_generate_report()`.

### `_file_lock` rename

CONFIRMED. `src/logger.py:12`: `_file_lock = threading.Lock()`. No remaining references to `_csv_lock` anywhere in the changed files.

### `pyproject.toml` / `uv.lock` reverted

CONFIRMED. `pyproject.toml` contains no `[dependency-groups]` block. Only the standard `[project.optional-dependencies]` `dev` group.

---

## End-to-End Data Flow Trace

### SELL event → log_trade(pnl=...) → trades CSV → reporter aggregation → summary output

1. `scheduler._check_holdings` (scheduler.py:54-69): When `result["signal"] == "SELL"`, calls `sell()`, computes `pnl = (current_price - avg_price) * qty`, calls `log_trade(..., pnl=pnl)`. CORRECT.

2. `logger.log_trade` (logger.py:57-86): Writes `pnl` as the 8th column (or empty string for BUY). CSV header is `["datetime","stock_code","action","price","quantity","amount","reason","pnl"]`. CORRECT.

3. `reporter._parse_trades_csv` (reporter.py:23-43): Reads CSV, converts `pnl` column to `float | None`. Empty string → `None` (BUY rows). CORRECT. Legacy CSV without `pnl` column: `row.get("pnl", None)` returns `None` safely. CORRECT.

4. `reporter._calc_pnl_stats` (reporter.py:46-80): Filters SELL rows, sums `pnl_values` (only non-None entries). `win_count = pnl > 0`, `loss_count = pnl <= 0`. CORRECT per design spec formula. One edge case noted in Important Warning #1 above.

5. `reporter._format_summary` (reporter.py:173-271): Uses `pnl_stats["realized_pnl"]` for display, `win_rate` for percentage. The `final_state["daily_loss"]` from `state.json` is displayed in the "일별 위험 상태" section as a cross-check figure, not reused in win_rate computation. CORRECT per design doc §6.

### Error isolation in `run_loop.finally`

`_maybe_generate_report()` catches all exceptions internally (scheduler.py:192-194 for `get_account_info`, scheduler.py:199-201 for `generate_daily_report`). The function signature is `-> None`. The `finally` block at scheduler.py:253-256 therefore cannot raise from report generation:
```python
finally:
    _clear_status()           # stdlib unlink — could raise on permission error (pre-existing)
    _maybe_generate_report()  # all exceptions swallowed internally
    signal.signal(...)        # stdlib — cannot raise under normal circumstances
```
Error isolation is verified by `test_maybe_generate_report_swallows_exception` in `tests/test_scheduler_report.py`.

### CLI smoke — `kis-trader report --date YYYYMMDD` with no logs

`cmd_report` (main.py:66-79) wraps `generate_daily_report` in a `try/except Exception` block that prints to stderr. `generate_daily_report` itself calls `_parse_trades_csv` (returns `[]` on missing file), `_parse_signals_log` (returns `[]`), `_parse_errors_log` (returns `[]`), `_load_start_snapshot` (returns `None`), `_load_final_state` (returns defaults). No path raises on missing files. The summary file is written with "거래 없음" content. The function returns 3 `Path` objects (no balance), and `cmd_report` prints each path. No stack trace. CONFIRMED CORRECT.

---

## Key Improvement Points (Top 3)

1. **Fix win_rate denominator for partial-pnl rows** (`src/reporter.py:70`): The denominator should be the count of rows that actually have pnl data, not `total_sell_count`. This is the only correctness issue in the entire feature and affects any day where old and new code both write to the same CSV.

2. **Log silently-swallowed parse failures in `_load_start_snapshot` and `_load_final_state`** (`src/reporter.py:146, 169`): Adopt the same `log_error(..., e)` pattern used throughout the rest of the codebase so corrupt auxiliary files surface in `raw_errors_YYYYMMDD.log` and alert the user.

3. **Remove or annotate the dead `started_at` variable in `run_loop`** (`src/scheduler.py:214`): The variable was introduced for an interface that was subsequently simplified. Leaving it creates reader confusion about whether it is supposed to be forwarded somewhere.

---

```
critical_count: 0
important_count: 3
minor_count: 3
verdict: APPROVE_WITH_NITS
```
