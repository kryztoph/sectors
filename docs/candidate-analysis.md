# Candidate review input and operating contract

The opt-in review engine runs in **sectors**, alongside the existing rotation
algorithms. It does not change sector rankings, fetch unspecified candidates,
place orders, modify the frontend, install jobs, or change the external ChatGPT
monitor's 7:45 PM ET primary run and conditional four-hour retries.

## Review workflow

1. Obtain candidate-specific daily OHLCV, a timestamped USD quote, proposed
   chart levels, and a current event review from sources you have verified.
   The existing optional yfinance provider can supply unadjusted daily OHLCV;
   sector snapshots alone are insufficient evidence for candidate review.
2. Supply the JSON contract below to
   `python3 -m sectors candidates --input /path/to/evidence.json`.
3. Review `reports/candidates/latest.md`, `.html`, and `.json`. JSON includes
   reasons, numerical indicators, prices, sizing, source identities/timestamps,
   a history hash, and the input hash. Full inputs are retained locally under
   `state/snapshots/candidates/<sha256>.json`; candidate inputs never overwrite
   the sector `latest.json` or enter the rotation tracker.
4. The existing `scripts/publish_to_reports_repo.sh` includes the complete
   current-review trio under `reports/sectors/candidates/` in
   `kryztoph/csfox-reports@master`. Publication is a separate action; the new
   commands never publish. Review code and integration before adding any new
   production schedule or candidate data adapter.
5. For hypothetical follow-up, provide sourced daily bars to
   `python3 -m sectors candidate-outcomes --input /path/to/outcomes.json`.
   This refreshes the report's hypothetical outcomes without replacing reviews.

No live candidate source or event calendar is configured by this change. The
engine checks explicit source verification attestations, identity, timestamps,
price basis, OHLC consistency, and technical evidence. It cannot authenticate a
vendor from a supplied JSON file. `verified: true` must reflect an actual upstream
verification, not a way to bypass missing data. Quotes may be delayed; source
and observation time remain visible. Missing evidence produces `REJECTED` rather
than inferred prices or event clearance. Synthetic tests are never live reports.

## Input contract

Top level is `{"candidates": [candidate, ...]}` with at least one candidate.
Each candidate has:

| Field | Requirement |
| --- | --- |
| `symbol` | Uppercase stock/ETF symbol, matching every evidence object |
| `asset_type`, `side` | `stock` or `etf`, and `long` |
| `setup_date` | ISO thesis date, no later than evaluation date; retain across retries |
| `entry`, `stop`, `target` | Positive finite USD prices; decimal strings recommended |
| `history` | Object described below, specific to this candidate |
| `quote` | Object described below; never substituted from an unrelated sector ETF |
| `events` | Verified event-review evidence described below |

`history` fields: `symbol`, nonempty `source` (vendor identifier or URL),
`verified: true`, timezone-aware `retrieved_at`, `price_basis: "raw"`,
`currency: "USD"`, `interval: "1d"`, and `bars`.
Each bar requires ISO `date` plus positive finite `open`, `high`, `low`, `close`,
and positive integral `volume`. No OHLC or volume fallback is synthesized.
At least 64 complete weekday daily bars are required in strictly increasing,
unique order; missing weekday sessions and gaps over seven calendar days are
rejected. Optional `non_trading_dates` is an explicit sourced list of ISO exchange
closure dates, covering the entire supplied history (and activation-to-outcome
window for outcomes). Closures cannot also contain bars. The latest completed
session must be present and latest bar age may not exceed four calendar days. Retrieval must be within 24 hours of evaluation,
without future timestamps. All bars must be complete by 4 PM America/New_York
at both retrieval and evaluation. This deliberately conservative rule also
waits until 4 PM on early-close days. Weekends are handled directly; exchange holidays require the source-attested
closure list. There is no built-in exchange holiday calendar, and extended
closures can still be rejected by the conservative calendar-age limit. Supplier verification must include session completeness,
splits and other corporate actions; raw price discontinuities need manual review.

`quote` fields: `symbol`, `source`, `verified: true`, timezone-aware `as_of`,
`price_basis: "raw"`, `currency: "USD"`, positive finite `price`.
Quote age must be at most 24 hours and cannot predate the latest daily bar.
A sourced closing quote is allowed if timestamped as such; no timestamp is
invented from a retrieval time. This freshness gate can reject weekend runs.

`events` fields: `symbol`, `source`, `verified: true`, timezone-aware `checked_at`
within 24 hours, `status: "clear"`, numeric `coverage_days >= 7`,
`next_event` (ISO date or null), and optional `risks` (must be empty).
Event clearance must cover earnings, splits, distributions, and material known
issuer or macro events for at least the next seven days. Present/unknown risks,
inadequate coverage, an outdated event date, or any event within seven days
rejects the setup. For ETFs, clearance still requires explicit evidence; missing
earnings dates do not establish event clearance. This is a calendar evidence
gate, not a prediction that no unscheduled event will occur.

There is deliberately no plausible-looking example quote or event clearance in
this document. Fill the contract with verified observations and chart levels.

## Risk and technical gates

Arithmetic uses decimal values and inclusive boundaries:

```
0 < stop < entry < target
entry - stop <= 0.03 * entry
target - entry >= 2 * (entry - stop)
shares = floor(min(2000 / entry, 60 / (entry - stop)))
shares > 0
```

The limits apply to **each hypothetical setup**, not a combined portfolio or
assumed simultaneous allocation. Planned loss excludes fees/slippage and is not
a guaranteed maximum realized loss, particularly across gaps.

Indicators use candidate bars: SMA20/SMA50, Wilder-smoothed RSI14 and ATR14,
20-bar average volume/dollar volume, and latest volume divided by that average.
Support is the nearest confirmed pivot low below entry; resistance is the
nearest confirmed pivot high above entry in the latest 64 bars. A pivot needs
two bars on either side. No projection or arbitrary 2R level supplies a target.
The stop must be strictly below support by at most 0.5 ATR and at least 0.5 ATR
below entry. The supplied target must be no more than 0.5 ATR below resistance
and cannot exceed it. Missing chart levels or nonpositive ATR rejects the setup.
Average volume must be at least 100,000 shares and average dollar volume $1m.
These are versioned research heuristics, not a validated profitability claim.

`READY FOR REVIEW` means every hard gate passes, last close >= MA20 > MA50,
RSI14 is 40–70 inclusive, relative volume >= 1, and the quote is between entry
and 0.5% above it. This is human review eligibility for the exact proposed entry;
it does not authorize buying at a different quote. Valid setups with unconfirmed
trend/volume/trigger are `WATCH FOR TRIGGER`; hard-gate failures are `REJECTED`.
Existing sector 5/21/63-day relative strength and ranking remain available in the
normal brief/tracker; a sector rank never substitutes for these candidate gates.

## IDs, replay, and hypothetical outcomes

IDs hash algorithm version, normalized symbol/type, thesis date, entry, stop,
and target. Equivalent decimal spellings and repeated evidence retrieval do not
create a new setup. Changing thesis or levels creates a new identity. Only a
setup's first `READY FOR REVIEW` observation activates a hypothetical scenario;
WATCH and REJECTED observations cannot create fills. Re-review does not reset
its activation or overwrite its original evidence.

SQLite state lives in ignored `state/candidates.sqlite3`. Transactions, unique
keys, and immutable stored bars prevent duplicate scenarios and silent historical
corrections. A conflicting previously recorded bar aborts the entire update for
manual review. Updates cannot move their evaluation time backward.

Outcome input is `{"histories": {"SYMBOL": history, ...}}` using the same history
evidence contract, with one or more bars instead of 64. Send all available bars
since activation; incremental inputs merge with stored bars. The tracker starts
on daily bars **after** activation day. No same-day or historical broker fill
is inferred from review evidence. A range crossing entry simulates an exact-entry
scenario. Entry and exit on one bar, stop and target on one bar, gaps above entry
or through exits, missing weekday sessions without attested closures, and history
gaps over seven days remain `UNRESOLVED`
with no R result. A same-bar ambiguity cannot be cleared by later bars. Otherwise
outcomes are AWAITING ENTRY, OPEN, STOP or TARGET, with hypothetical R only for
unambiguous exits. Verified suppliers are responsible for correct closure attestations and
complete daily session data. Activation days use America/New_York even when
the 7:45 PM ET review falls on the next UTC date. No win rate or
realized broker performance is claimed.

Every record is `kind: "hypothetical"`, with outcome `broker_fill: false`.
Real fills require a separate explicit broker-sourced system; none is imported,
synthesized, or executed here. The analysis never writes to a broker.

Use `--as-of <timezone-aware ISO timestamp>` on either command for explicit
historical replay. Replay uses `state/candidates-replay.sqlite3` and
`reports/candidates/replay/latest.*`, with a visible historical replay label.
The publisher excludes that directory. Both replay commands must use the same
mode; replay cannot activate current-review scenarios. Raw evidence snapshots
are content-addressed and may be shared safely across modes.

## Publication safety and review

Both publisher shell entrypoints resolve their own worktree by default and honor
`SECTORS_PROJECT_DIR`. `SECTORS_PUBLISH_REPO` overrides repository URL settings;
`SECTORS_PUBLISH_REPO_URL` and legacy `SECTORS_REPORTS_REPO_URL` remain supported.
Every configured repository setting is validated, including lower-priority
values. Any frontend `kryztoph/csfox` setting is rejected, case-insensitively.
Canonical GitHub metadata rejects redirects and frontend aliases before Git
writes. `SECTORS_PUBLISH_BRANCH` (legacy `SECTORS_REPORTS_BRANCH`) defaults to
`master`; the default reports repository requires `master`, which must exist.
Alternate explicit report repositories/branches remain supported. Commits use
only generated report/optional logo paths, preserve the base tree, skip unchanged
trees, and advance refs without force. Failed/racing ref updates fail rather
than overwriting other commits. Tests mock every publication API call; they do
not publish or touch a frontend checkout.
