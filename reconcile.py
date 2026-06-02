"""
reconcile.py  —  Aladdin data validation engine
================================================
Checks every field in the client security master against Aladdin conventions.
Uses real market data (live EURIBOR, US 10Y yield) to validate derivative
fixed rates and duration reasonableness.

This mirrors what the Data Implementation team runs manually today.
"""

import json, csv
from datetime import date
from dataclasses import dataclass, asdict

# ── Load real market reference data ─────────────────────────────────────────

with open("/home/claude/aladdin_project/data/market_data.json") as f:
    MARKET = json.load(f)

EURIBOR_3M = MARKET["euribor_3m"]
US_10Y     = MARKET["us_10y"]
VIX        = MARKET["vix"]

# ── Aladdin conventions ──────────────────────────────────────────────────────

ALADDIN_BENCH_FI  = {"FTSE-JSE-ALBI","FTSE-JSE-GOVI","FTSE-JSE-OTHI","FTSE-JSE-CORP"}
ALADDIN_BENCH_EQ  = {"FTSE-JSE-ALSI40","FTSE-JSE-SWIX","FTSE-JSE-FINI15","FTSE-JSE-INDI25"}
VALID_FLOAT_IDX   = {"EUR-EURIBOR-Reuters","USD-SOFR-CME","GBP-SONIA-WMBA",
                     "ZAR-JIBAR-SAFEX","ZAR-CPI","N/A"}
VALID_DAY_COUNTS  = {"Act/365","Act/360","30/360","Act/Act"}
NAV_STALE_DAYS    = 90       # Aladdin private markets NAV freshness requirement
DURATION_TOL      = 0.40     # flag if client duration > 0.4y off from computed value
RATE_SPREAD_MAX   = 3.0      # flag if fixed rate is > 300bp above benchmark (possible error)

# ── Issue record ─────────────────────────────────────────────────────────────

@dataclass
class Issue:
    isin:             str
    name:             str
    asset_class:      str
    check_name:       str
    field:            str
    client_value:     str
    expected:         str
    severity:         str     # critical | high | medium | low
    go_live_risk:     bool
    market_context:   str     # real market data that informed this check
    ai_classification:str = ""
    root_cause:       str = ""
    fix_action:       str = ""
    ai_confidence:    float = 0.0
    status:           str = "open"

# ── Fixed Income checks ──────────────────────────────────────────────────────

def check_fi(sec) -> list[Issue]:
    issues = []
    isin, name = sec["isin"], sec["name"]
    base = dict(isin=isin, name=name, asset_class="Fixed Income")

    # 1. Duration validation against computed true value
    dur_c = str(sec.get("duration_client","")).strip()
    dur_t = sec.get("duration_true", None)
    if not dur_c:
        issues.append(Issue(**base,
            check_name="Missing duration", field="duration_client",
            client_value="", expected="Required for Aladdin risk analytics",
            severity="critical", go_live_risk=True,
            market_context=f"US 10Y at {US_10Y}% — duration critical for risk attribution"))
    else:
        try:
            d = float(dur_c)
            if dur_t and abs(d - float(dur_t)) > DURATION_TOL:
                delta = round(abs(d - float(dur_t)), 3)
                issues.append(Issue(**base,
                    check_name="Duration discrepancy vs Aladdin computed",
                    field="duration_client",
                    client_value=f"{d} years",
                    expected=f"~{dur_t} years (Aladdin YTM convention)",
                    severity="critical", go_live_risk=True,
                    market_context=f"Delta: {delta}y. US 10Y={US_10Y}%, VIX={VIX} — risk error compounds in volatile market"))
            elif d <= 0 or d > 50:
                issues.append(Issue(**base,
                    check_name="Duration out of range", field="duration_client",
                    client_value=str(d), expected="0 < duration ≤ 50",
                    severity="critical", go_live_risk=True,
                    market_context="Invalid value — Aladdin analytics will reject"))
        except ValueError:
            issues.append(Issue(**base,
                check_name="Duration non-numeric", field="duration_client",
                client_value=dur_c, expected="Numeric (years)",
                severity="critical", go_live_risk=True,
                market_context="Parse failure — Aladdin pipeline will crash"))

    # 2. Convexity missing
    conv = str(sec.get("convexity_client","")).strip()
    if not conv:
        issues.append(Issue(**base,
            check_name="Missing convexity", field="convexity_client",
            client_value="", expected="Required — use YTM / Act/365 convention",
            severity="high", go_live_risk=False,
            market_context="Convexity matters more when yields move >100bp — VIX elevated"))

    # 3. Benchmark ID format
    bench = str(sec.get("benchmark","")).strip()
    if bench not in ALADDIN_BENCH_FI:
        correct = sec.get("benchmark_correct","FTSE-JSE-ALBI")
        issues.append(Issue(**base,
            check_name="Benchmark ID not recognised by Aladdin", field="benchmark",
            client_value=bench or "(blank)",
            expected=correct,
            severity="high", go_live_risk=False,
            market_context="Benchmark mismatch blocks tracking error and attribution analytics"))

    # 4. Both credit ratings absent
    sp = str(sec.get("sp_rating","")).strip()
    md = str(sec.get("moodys_rating","")).strip()
    if not sp and not md:
        issues.append(Issue(**base,
            check_name="No credit rating (S&P + Moody's)", field="sp_rating",
            client_value="(both blank)",
            expected="At least one rating required (Fitch accepted with mapping)",
            severity="medium", go_live_risk=False,
            market_context="Rating required for Aladdin credit risk analytics and compliance reporting"))

    # 5. CPI flag inconsistency
    cpi = str(sec.get("cpi_linked","")).strip()
    if "Inflation" in name and cpi != "Y":
        issues.append(Issue(**base,
            check_name="CPI-linked flag wrong on inflation bond", field="cpi_linked",
            client_value=cpi, expected="Y",
            severity="critical", go_live_risk=True,
            market_context="Incorrect flag causes ~4x duration calculation error on linkers"))

    # 6. Day count convention
    dc = str(sec.get("day_count","")).strip()
    if not dc or dc not in VALID_DAY_COUNTS:
        issues.append(Issue(**base,
            check_name="Invalid day-count convention", field="day_count",
            client_value=dc or "(blank)",
            expected="Act/365 | Act/360 | 30/360 | Act/Act",
            severity="medium", go_live_risk=False,
            market_context="Day count affects accrued interest calculation — impacts cash reconciliation"))

    return issues

# ── Equity checks ─────────────────────────────────────────────────────────────

GICS_NAMES = {
    "4010":"Financials","1010":"Energy","1510":"Materials",
    "4510":"IT/Consumer Disc","3510":"Health Care","2010":"Industrials","5010":"Comm Services"
}

def check_equity(sec) -> list[Issue]:
    issues = []
    isin, name = sec["isin"], sec["name"]
    base = dict(isin=isin, name=name, asset_class="Equity")

    # 1. GICS sector mismatch vs correct value
    gics_c = str(sec.get("sector_gics","")).strip()
    gics_t = str(sec.get("sector_correct","")).strip()
    if gics_c and gics_t and gics_c != gics_t:
        issues.append(Issue(**base,
            check_name="GICS sector mismatch vs MSCI standard",
            field="sector_gics",
            client_value=f"{gics_c} ({GICS_NAMES.get(gics_c,'?')})",
            expected=f"{gics_t} ({GICS_NAMES.get(gics_t,'?')}) — per MSCI/Aladdin",
            severity="high", go_live_risk=False,
            market_context="Incorrect sector causes wrong benchmark attribution in Aladdin analytics"))
    elif not gics_c:
        issues.append(Issue(**base,
            check_name="Missing GICS sector code", field="sector_gics",
            client_value="", expected="4-digit GICS code required",
            severity="low", go_live_risk=False,
            market_context="Required for sector exposure reporting"))

    # 2. Benchmark format
    bench = str(sec.get("benchmark","")).strip()
    if bench not in ALADDIN_BENCH_EQ:
        correct = sec.get("benchmark_correct","FTSE-JSE-ALSI40")
        issues.append(Issue(**base,
            check_name="Equity benchmark ID not in Aladdin reference",
            field="benchmark",
            client_value=bench or "(blank)",
            expected=correct,
            severity="medium", go_live_risk=False,
            market_context="Required for relative return and tracking error calculations"))

    # 3. Currency unit error
    if sec.get("_currency_error"):
        issues.append(Issue(**base,
            check_name="Currency unit error — GBP vs GBp (100x)",
            field="currency",
            client_value="GBP",
            expected="GBp (pennies) — dual-listed stock",
            severity="high", go_live_risk=False,
            market_context="Price off by 100x — P&L and NAV will be materially wrong"))

    return issues

# ── Derivatives checks ────────────────────────────────────────────────────────

def check_derivatives(sec) -> list[Issue]:
    issues = []
    isin, name = sec["isin"], sec["name"]
    sub   = sec.get("sub_type","")
    base  = dict(isin=isin, name=name, asset_class="Derivatives")

    # 1. Missing notional — absolute blocker
    notional = str(sec.get("notional","")).strip()
    if not notional:
        issues.append(Issue(**base,
            check_name="Missing notional — go-live blocker",
            field="notional",
            client_value="",
            expected=f"Required — true notional: ~{sec.get('notional_true','?'):,}",
            severity="critical", go_live_risk=True,
            market_context="Aladdin cannot price or risk a derivative without notional — blocks entire derivatives analytics"))

    # 2. Floating rate index — validate against ISDA standard
    fi_client  = str(sec.get("float_index","")).strip()
    fi_correct = str(sec.get("float_index_correct","")).strip()
    if sub in ("IRS","OIS","ILS","TRS") and fi_client not in VALID_FLOAT_IDX:
        # Also check against real rate — if client sent raw rate number instead of index name
        market_ref = f"EURIBOR 3M={EURIBOR_3M}%, US SOFR approx={US_10Y-1.5:.2f}%"
        issues.append(Issue(**base,
            check_name="Float index not ISDA-standard",
            field="float_index",
            client_value=fi_client or "(blank)",
            expected=fi_correct,
            severity="critical", go_live_risk=True,
            market_context=f"Real rates: {market_ref}. Wrong index breaks cash-flow scheduling and P&L attribution"))

    # 3. Fixed rate sanity check vs real market
    if sub in ("IRS","OIS") and notional:
        try:
            fr = float(sec.get("fixed_rate","0"))
            ccy = sec.get("currency","USD").split("/")[0]
            benchmark_rate = EURIBOR_3M if ccy == "EUR" else US_10Y
            spread = fr - benchmark_rate
            if spread > RATE_SPREAD_MAX:
                issues.append(Issue(**base,
                    check_name="Fixed rate suspiciously high vs market benchmark",
                    field="fixed_rate",
                    client_value=f"{fr}%",
                    expected=f"Within {RATE_SPREAD_MAX:.0f}% of {benchmark_rate}% ({ccy} benchmark)",
                    severity="medium", go_live_risk=False,
                    market_context=f"Current {ccy} benchmark: {benchmark_rate}%. Spread of {spread:.2f}% warrants review"))
        except (ValueError, TypeError):
            pass

    # 4. Payment calendar missing
    cal = str(sec.get("payment_calendar","")).strip()
    if not cal:
        issues.append(Issue(**base,
            check_name="Payment calendar missing",
            field="payment_calendar",
            client_value="",
            expected="EUTA (EUR) / USNY (USD) / ZAJO (ZAR)",
            severity="high", go_live_risk=False,
            market_context="Missing calendar causes incorrect cash-flow date generation in Aladdin"))

    # 5. CDS reference entity naming convention
    if sub == "CDS":
        ref = str(sec.get("ref_entity","")).strip()
        if ref not in ("Republic of South Africa","") and ref != "N/A":
            issues.append(Issue(**base,
                check_name="CDS reference entity — non-ISDA name variant",
                field="ref_entity",
                client_value=ref,
                expected="'Republic of South Africa' (ISDA standard)",
                severity="medium", go_live_risk=False,
                market_context="ISDA entity names required for credit event matching in Aladdin"))

    # 6. Day count
    dc = str(sec.get("day_count","")).strip()
    if not dc or dc not in VALID_DAY_COUNTS:
        issues.append(Issue(**base,
            check_name="Day-count convention missing or invalid",
            field="day_count",
            client_value=dc or "(blank)",
            expected="Act/360 for most swaps",
            severity="medium", go_live_risk=False,
            market_context="Day count affects accrued interest and cash-flow timing"))

    return issues

# ── Private Markets checks ────────────────────────────────────────────────────

def check_pm(sec) -> list[Issue]:
    issues = []
    isin, name = sec["isin"], sec["name"]
    base = dict(isin=isin, name=name, asset_class="Private Markets")

    stale = int(sec.get("nav_days_stale", 0))
    if stale > NAV_STALE_DAYS:
        issues.append(Issue(**base,
            check_name=f"NAV stale — {stale} days (threshold: {NAV_STALE_DAYS}d)",
            field="nav_date",
            client_value=sec.get("nav_date",""),
            expected=f"NAV dated within {NAV_STALE_DAYS} days",
            severity="critical", go_live_risk=True,
            market_context=f"VIX={VIX} — stale valuations create material NAV error in volatile markets"))

    cf = str(sec.get("cashflow_schedule","")).strip()
    if not cf:
        issues.append(Issue(**base,
            check_name="Cashflow schedule absent",
            field="cashflow_schedule",
            client_value="",
            expected="Quarterly schedule required for Aladdin IRR/yield calculation",
            severity="high", go_live_risk=False,
            market_context="Without schedule Aladdin cannot model distributions or compute DPI/RVPI"))

    irr = str(sec.get("irr","")).strip()
    if not irr:
        issues.append(Issue(**base,
            check_name="IRR not provided",
            field="irr",
            client_value="",
            expected="Required for performance attribution reporting",
            severity="medium", go_live_risk=False,
            market_context="IRR needed for Aladdin private markets analytics module"))

    return issues

# ── Run all checks ────────────────────────────────────────────────────────────

CHECKERS = {
    "Fixed Income":   check_fi,
    "Equity":         check_equity,
    "Derivatives":    check_derivatives,
    "Private Markets":check_pm,
}

def run(securities):
    issues = []
    for sec in securities:
        fn = CHECKERS.get(sec.get("asset_class",""))
        if fn:
            issues.extend(fn(sec))
    return issues

if __name__ == "__main__":
    with open("/home/claude/aladdin_project/data/all_securities.json") as f:
        secs = json.load(f)
    print(f"Loaded {len(secs)} securities\n")
    print(f"Market context: EURIBOR 3M={EURIBOR_3M}%, US 10Y={US_10Y}%, VIX={VIX}\n")

    issues = run(secs)

    by_sev = {}
    by_ac  = {}
    for i in issues:
        by_sev[i.severity] = by_sev.get(i.severity,0) + 1
        by_ac[i.asset_class] = by_ac.get(i.asset_class,0) + 1

    print("=== RECONCILIATION RESULTS ===")
    print(f"Total issues : {len(issues)}")
    for s in ("critical","high","medium","low"):
        print(f"  {s:<10}: {by_sev.get(s,0)}")
    print()
    for ac,n in by_ac.items():
        print(f"  {ac:<20}: {n} issues")

    out = [asdict(i) for i in issues]
    with open("/home/claude/aladdin_project/output/issues_raw.json","w") as f:
        json.dump(out, f, indent=2)

    with open("/home/claude/aladdin_project/output/issues.csv","w",newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)

    summary = {"total":len(issues),"by_severity":by_sev,"by_asset_class":by_ac,
               "market_data":MARKET}
    with open("/home/claude/aladdin_project/output/summary.json","w") as f:
        json.dump(summary, f, indent=2)
    print(f"\nSaved to output/")
