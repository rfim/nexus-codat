# insights_cash_flow_monthly: C-107 fails bank reconciliation by 1,250.00

*Severity:* medium · *Confidence:* 90% · *Written by:* offline-rules over MCP (nexus-insights (stdio))

## Root cause
The bank feed re-sent one C-107 payment of 1,250.00 on 2026-08-14 under a new transaction id (C-107-T00120, C-107-T00120-R). The MERGE key is (company_id, txn_id), so it landed as a second row and inflated the month's cash flow by 1,250.00.

## Evidence
- reconcile net_movement_all to source within 0.01 failed on 2 rows, all for C-107 — `get_check_evidence`
- bank lines sum to 52,866.69; the balance moved 51,616.69 — `run_diagnostic(bank_lines_vs_balance)`
- 2 lines share date, amount and description: C-107-T00120, C-107-T00120-R — `run_diagnostic(same_day_same_amount)`
- lines by category: commerce_payout 120, loan_drawdown 1, own_transfer 4, payment 46, receipt 23 — `run_diagnostic(lines_by_category)`

## Hypotheses
- **supported**: The feed re-sent a line under a new id. A same-day, same-amount pair exactly equals the difference.
- **rejected**: The reported balance is stale. Every other company reconciles to the penny with the same balance feed.
- **rejected**: A recent code or contract change. No recent change touches banking logic.

## Proposed fix (as a pull request)
Quarantine a bank line that repeats an earlier line's account, date, amount and description within one day under a different id, and tell the source owner. Quarantine, not delete: a genuine second payment must stay reviewable.

Files: `contracts/quality.yml`, `src/nexus/silver.py`, `tests/test_silver.py`

Test: A bank line re-sent under a new id is quarantined, and the cash-flow reconciliation passes.

## Customer impact
Cash flow for one company is overstated for one month; the product carries a caveat until fixed.
