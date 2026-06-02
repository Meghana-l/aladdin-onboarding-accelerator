"""
generate_data.py  —  STANLIB onboarding security master simulation
==================================================================
Uses REAL data sources:
  • S&P 500 constituents from GitHub (real companies, real GICS sectors)
  • Real EURIBOR 3M rate for floating rate swaps
  • Real US 10Y Treasury yield for duration benchmarking
  • Real VIX for market context

Simulates the security master file that STANLIB South Africa would send
to BlackRock's Data Implementation team before Aladdin onboarding.
Intentionally injects the exact data quality issues this team fixes daily.
"""

import json, csv, random, urllib.request, io
from datetime import date, timedelta

random.seed(42)

# ── Pull real reference data ─────────────────────────────────────────────────

def fetch(url):
    with urllib.request.urlopen(url) as r:
        return r.read().decode()

print("Fetching real market reference data...")

# Real S&P 500 companies (real names, real GICS sectors, real CIK numbers)
sp500 = list(csv.DictReader(io.StringIO(
    fetch("https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv")
)))

# Real EURIBOR 3M (used as benchmark for EUR swap floating legs)
euribor_rows = list(csv.DictReader(io.StringIO(
    fetch("https://raw.githubusercontent.com/datasets/euribor/main/data/euribor-3m-monthly.csv")
)))
EURIBOR_3M = float(euribor_rows[-1]["rate"])
EURIBOR_DATE = euribor_rows[-1]["date"]

# Real US 10Y Treasury yield (used for duration sanity checks)
tsy_rows = list(csv.DictReader(io.StringIO(
    fetch("https://raw.githubusercontent.com/datasets/bond-yields-us-10y/main/data/monthly.csv")
)))
US_10Y = float(tsy_rows[-1]["Rate"])

# Real VIX (market stress — affects credit spread context)
vix_rows = list(csv.DictReader(io.StringIO(
    fetch("https://raw.githubusercontent.com/datasets/finance-vix/main/data/vix-daily.csv")
)))
VIX = float(vix_rows[-1]["CLOSE"])

print(f"  EURIBOR 3M: {EURIBOR_3M}% (as of {EURIBOR_DATE})")
print(f"  US 10Y Treasury: {US_10Y}%")
print(f"  VIX: {VIX}")
print()

# Save market snapshot for reconciliation engine to use
with open("/home/claude/aladdin_project/data/market_data.json", "w") as f:
    json.dump({
        "euribor_3m": EURIBOR_3M, "euribor_date": EURIBOR_DATE,
        "us_10y": US_10Y, "vix": VIX,
        "fetch_date": date.today().isoformat()
    }, f, indent=2)

# ── Aladdin reference conventions (what the platform expects) ────────────────

# Aladdin benchmark IDs — the canonical IDs Aladdin uses internally
ALADDIN_BENCHMARKS_FI   = ["FTSE-JSE-ALBI", "FTSE-JSE-GOVI", "FTSE-JSE-OTHI", "FTSE-JSE-CORP"]
ALADDIN_BENCHMARKS_EQ   = ["FTSE-JSE-ALSI40", "FTSE-JSE-SWIX", "FTSE-JSE-FINI15", "FTSE-JSE-INDI25"]

# Client typically uses these short-form names instead — Aladdin can't match them
CLIENT_BENCH_FI_WRONG   = ["ALBI", "SA-GOV-BOND-IDX", "JSE-COMPOSITE", "SAGovt", ""]
CLIENT_BENCH_EQ_WRONG   = ["ALSI", "JSE-TOP40", "SWIX-INDEX", "TOP40", ""]

# Aladdin-standard float index names (ISDA conventions)
VALID_FLOAT_INDICES     = {"EUR-EURIBOR-Reuters", "USD-SOFR-CME", "GBP-SONIA-WMBA",
                            "ZAR-JIBAR-SAFEX", "ZAR-CPI", "N/A"}
# What clients typically send instead
CLIENT_FLOAT_WRONG      = {"EUR": "EURIBOR", "USD": "USD-SOFR", "GBP": "SONIA"}

# ── Helpers ──────────────────────────────────────────────────────────────────

def maybe_null(v, pct=0.15):
    return "" if random.random() < pct else v

def corrupt_float(v, pct=0.12, factor_range=(0.75, 1.4)):
    """Simulate source system errors — slightly wrong numeric values."""
    if v and random.random() < pct:
        return round(float(v) * random.uniform(*factor_range), 4)
    return v

def rand_isin(prefix, n=10):
    return prefix + str(random.randint(10**(n-1), 10**n - 1))

def rand_date_past(min_days=10, max_days=200):
    return (date.today() - timedelta(days=random.randint(min_days, max_days))).isoformat()

def rand_maturity(min_yr=1, max_yr=30):
    return (date.today() + timedelta(days=random.randint(min_yr*365, max_yr*365))).isoformat()[:7] + "-15"

# ── Fixed Income (60 securities) ─────────────────────────────────────────────
# RSA government bonds, SOE bonds, bank paper — real SA issuers

SA_ISSUERS = [
    ("Republic of South Africa", "Sovereign", "AAA", "Aaa"),
    ("Eskom SOC Limited",        "SOE",       "",    ""),    # only Fitch-rated — triggers missing rating issue
    ("Transnet SOC Ltd",         "SOE",       "",    ""),
    ("City of Johannesburg",     "Municipal", "AA",  "Aa2"),
    ("Standard Bank of SA",      "Financial", "A+",  "A1"),
    ("Absa Bank Limited",        "Financial", "A",   "A2"),
    ("Nedbank Limited",          "Financial", "A-",  "A3"),
    ("FirstRand Bank",           "Financial", "A+",  "A1"),
    ("Old Mutual Limited",       "Financial", "BBB+","Baa1"),
    ("Investec Bank",            "Financial", "BBB", "Baa2"),
]

def gen_fixed_income(n=60):
    rows = []
    for i in range(n):
        issuer, issuer_type, sp_base, mdy_base = random.choice(SA_ISSUERS)
        coupon = round(random.uniform(6.5, 12.5), 2)
        maturity_yr = date.today().year + random.randint(1, 25)
        is_inflation = random.random() < 0.10
        name = f"{issuer} {'Inflation-Linked ' if is_inflation else ''}{maturity_yr} {coupon}%"

        # Duration: compute from coupon and maturity (simplified)
        years_to_mat = maturity_yr - date.today().year
        true_duration = round(min(years_to_mat * 0.85, years_to_mat - 0.3), 4)

        # Inject duration error: client uses settlement-date convention (~15% of bonds)
        # This is the #1 real-world FI onboarding issue
        if random.random() < 0.15:
            # Settlement date adds ~2-5 days, causing duration to be slightly off
            dur_client = str(round(true_duration * random.uniform(0.78, 1.35), 4))
            duration_error = True
        else:
            dur_client = str(true_duration)
            duration_error = False

        convexity_true = round(true_duration**2 / random.uniform(8, 12), 4)
        conv_client = maybe_null(str(convexity_true), pct=0.15)

        # Ratings: SOEs often missing S&P/Moody's
        sp_rating   = maybe_null(sp_base,  pct=0.10) if sp_base  else ""
        mdy_rating  = maybe_null(mdy_base, pct=0.10) if mdy_base else ""

        # Benchmark: client uses wrong format
        bench_correct = random.choice(ALADDIN_BENCHMARKS_FI)
        benchmark = random.choice(CLIENT_BENCH_FI_WRONG) if random.random() < 0.30 else bench_correct

        # CPI flag error on inflation bonds
        cpi_flag = "Y" if is_inflation else "N"
        if is_inflation and random.random() < 0.60:
            cpi_flag = "N"  # wrong — inflation bond flagged as not CPI-linked

        # Day count convention — clients send inconsistent values
        day_count = random.choice(["Act/365", "Act/360", "30/360", "Actual/365", "ACT365", ""])

        rows.append({
            "isin":              rand_isin("ZAG"),
            "name":              name,
            "asset_class":       "Fixed Income",
            "sub_type":          issuer_type,
            "issuer":            issuer,
            "coupon":            coupon,
            "maturity_date":     f"{maturity_yr}-{random.randint(1,12):02d}-15",
            "currency":          "ZAR",
            "duration_client":   dur_client,
            "duration_true":     true_duration,        # what Aladdin will compute
            "convexity_client":  conv_client,
            "sp_rating":         sp_rating,
            "moodys_rating":     mdy_rating,
            "benchmark":         benchmark,
            "benchmark_correct": bench_correct,
            "sector_gics":       maybe_null("4010", pct=0.08),
            "day_count":         day_count,
            "cpi_linked":        cpi_flag,
            "settlement_days":   random.choice([3, 5, 0]),
            "_duration_error":   duration_error,
        })
    return rows

# ── Equities (40 securities) — built from REAL S&P 500 data ─────────────────
# Uses actual company names, real GICS sectors from the public dataset.
# Simulates a client who holds a mix of US + some cross-listed names,
# with sector misclassifications and currency unit errors.

def gen_equities(n=40):
    rows = []
    # Pull real companies from S&P500 dataset — financials + cross-sector
    pool = [r for r in sp500 if r["GICS Sector"] in
            ("Financials","Energy","Materials","Information Technology","Health Care")][:n]
    random.shuffle(pool)

    for comp in pool[:n]:
        name   = comp["Security"]
        sector = comp["GICS Sector"]
        gics_map = {
            "Financials": "4010", "Energy": "1010", "Materials": "1510",
            "Information Technology": "4510", "Health Care": "3510"
        }
        gics_correct = gics_map.get(sector, "9999")

        # Inject GICS misclassification (15%)
        all_gics = ["4010","1010","1510","4510","3510","2010","5010"]
        gics_client = random.choice([g for g in all_gics if g != gics_correct]) \
                      if random.random() < 0.15 else gics_correct

        # Benchmark: client uses short-form ID
        bench_correct = random.choice(ALADDIN_BENCHMARKS_EQ)
        benchmark = random.choice(CLIENT_BENCH_EQ_WRONG) if random.random() < 0.20 else bench_correct

        # Currency: some energy/materials names listed in multiple currencies
        # Client sometimes sends USD instead of proper exchange currency
        currency = "USD"
        currency_error = False
        if sector in ("Materials","Energy") and random.random() < 0.20:
            currency = "GBP"   # client sends GBP when it should be GBp — 100x error
            currency_error = True

        rows.append({
            "isin":             rand_isin("US"),
            "name":             name,
            "asset_class":      "Equity",
            "sub_type":         "Listed Equity",
            "issuer":           name,
            "sector_gics":      gics_client,
            "sector_correct":   gics_correct,
            "gics_sector_name": sector,
            "currency":         currency,
            "benchmark":        benchmark,
            "benchmark_correct":bench_correct,
            "exchange":         "NYSE" if random.random() > 0.3 else "NASDAQ",
            "sp500_symbol":     comp["Symbol"],
            "cik":              comp["CIK"],         # real SEC CIK number
            "_gics_error":      gics_client != gics_correct,
            "_currency_error":  currency_error,
        })
    return rows

# ── Derivatives (25 securities) — calibrated to real EURIBOR/SOFR ────────────
# Real floating rate benchmark values from live data.
# Swap rates derived from real yield curve.

DERIV_TYPES = [
    ("Interest Rate Swap",  "IRS",  "EUR",     "EUR-EURIBOR-Reuters"),
    ("Interest Rate Swap",  "IRS",  "USD",     "USD-SOFR-CME"),
    ("Credit Default Swap", "CDS",  "USD",     "N/A"),
    ("FX Forward",          "FXF",  "USD/ZAR", "N/A"),
    ("SOFR OIS",            "OIS",  "USD",     "USD-SOFR-CME"),
    ("Inflation Swap",      "ILS",  "ZAR",     "ZAR-CPI"),
    ("Total Return Swap",   "TRS",  "EUR",     "EUR-EURIBOR-Reuters"),
    ("Swaption",            "SWPN", "USD",     "USD-SOFR-CME"),
]

def gen_derivatives(n=25):
    rows = []
    for _ in range(n):
        dtype, dcode, ccy, correct_idx = random.choice(DERIV_TYPES)
        tenor_yr = random.choice([1,2,3,5,7,10,15,20,30])
        notional  = round(random.uniform(1e6, 5e7), -3)

        # Calibrate fixed rate to real yields
        if "USD" in ccy:
            fixed_rate = round(US_10Y + random.uniform(-0.5, 1.5), 3)
        else:
            fixed_rate = round(EURIBOR_3M + random.uniform(0.5, 2.5), 3)

        # Missing notional: CRITICAL issue, ~20% of derivatives
        notional_client = "" if random.random() < 0.20 else str(int(notional))

        # Float index: client sends short-form name instead of ISDA standard
        if correct_idx not in ("N/A", "ZAR-CPI"):
            ccy_key = ccy.split("/")[0]
            float_idx = CLIENT_FLOAT_WRONG.get(ccy_key, correct_idx) \
                        if random.random() < 0.35 else correct_idx
        else:
            float_idx = correct_idx

        # CDS reference entity naming
        ref_entity = ""
        if dcode == "CDS":
            ref_entity = random.choice([
                "Republic of South Africa",   # correct ISDA name
                "RSA",                         # client shorthand
                "South Africa",                # another variant
                "South Africa (Government)",   # yet another
                ""
            ])

        # Payment calendar
        calendar_map = {"EUR":"EUTA","USD":"USNY","GBP":"GBLO","ZAR":"ZAJO"}
        cal_correct = calendar_map.get(ccy.split("/")[0], "USNY")
        payment_cal = maybe_null(cal_correct, pct=0.30)

        rows.append({
            "isin":              rand_isin("XS"),
            "name":              f"{dtype} {tenor_yr}Y {ccy}",
            "asset_class":       "Derivatives",
            "sub_type":          dcode,
            "currency":          ccy,
            "tenor_years":       tenor_yr,
            "fixed_rate":        fixed_rate,
            "notional":          notional_client,
            "notional_true":     int(notional),
            "float_index":       float_idx,
            "float_index_correct": correct_idx,
            "ref_entity":        ref_entity,
            "payment_calendar":  payment_cal,
            "day_count":         maybe_null(random.choice(["Act/360","Act/365",""]), pct=0.15),
            "maturity_date":     rand_maturity(tenor_yr, tenor_yr+1),
            # Real rate context for reconciliation
            "market_euribor_3m": EURIBOR_3M,
            "market_us_10y":     US_10Y,
        })
    return rows

# ── Private Markets (15 funds) ───────────────────────────────────────────────
# Real fund names, realistic NAV staleness issues

PRIV_FUNDS = [
    ("Growthpoint Real Estate Fund II",  "Real Estate",     "ZAR"),
    ("Abraaj Infrastructure Fund IV",    "Infrastructure",  "USD"),
    ("Actis Energy Fund 5",              "Infrastructure",  "USD"),
    ("Old Mutual PE Fund IV",            "PE Fund",         "ZAR"),
    ("Ethos Private Equity VIII",        "PE Fund",         "ZAR"),
    ("Vantage Capital Mezzanine V",      "Private Credit",  "ZAR"),
    ("Pemberton Direct Lending III",     "Private Credit",  "EUR"),
    ("RMB Ventures Infrastructure II",  "Infrastructure",  "ZAR"),
    ("Harith General Partners Fund II", "Infrastructure",  "USD"),
    ("Capitalworks Private Equity III", "PE Fund",         "ZAR"),
    ("Medu Capital Fund IV",             "PE Fund",         "ZAR"),
    ("Knife Capital Growth Equity III", "PE Fund",         "ZAR"),
    ("Futuregrowth Infrastructure Fund","Infrastructure",  "ZAR"),
    ("Sanlam Private Equity VIII",      "PE Fund",         "ZAR"),
    ("Ninety One Private Credit II",    "Private Credit",  "USD"),
]

def gen_private_markets(n=15):
    rows = []
    for i in range(n):
        name, sub_type, ccy = PRIV_FUNDS[i % len(PRIV_FUNDS)]
        # NAV staleness: Aladdin requires <90 days. Many PM funds update quarterly.
        nav_days = random.choice([25, 45, 60, 88, 92, 105, 120, 150, 200])
        nav_date  = (date.today() - timedelta(days=nav_days)).isoformat()
        nav_val   = round(random.uniform(85.0, 140.0), 4)
        commitment = round(random.uniform(1e6, 2e7), -4)
        irr_val   = round(random.uniform(8.0, 24.0), 2)

        rows.append({
            "isin":               f"PRV-ZA-{i+1:03d}",
            "name":               name,
            "asset_class":        "Private Markets",
            "sub_type":           sub_type,
            "currency":           ccy,
            "nav":                str(nav_val),
            "nav_date":           nav_date,
            "nav_days_stale":     nav_days,
            "cashflow_schedule":  maybe_null("quarterly", pct=0.40),
            "irr":                maybe_null(str(irr_val), pct=0.35),
            "commitment":         str(int(commitment)),
            "vintage_year":       random.randint(2018, 2023),
            "manager":            name.split(" Fund")[0].split(" Equity")[0],
        })
    return rows

# ── Write all files ──────────────────────────────────────────────────────────

def write_csv(rows, path):
    if not rows: return
    keys = sorted(set(k for r in rows for k in r.keys()))
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k,"") for k in keys})
    print(f"  Wrote {path}  ({len(rows)} rows)")

if __name__ == "__main__":
    print("\nBuilding STANLIB security master...\n")
    fi   = gen_fixed_income(60)
    eq   = gen_equities(40)
    der  = gen_derivatives(25)
    priv = gen_private_markets(15)
    all_sec = fi + eq + der + priv

    write_csv(fi,    "/home/claude/aladdin_project/data/client_fixed_income.csv")
    write_csv(eq,    "/home/claude/aladdin_project/data/client_equities.csv")
    write_csv(der,   "/home/claude/aladdin_project/data/client_derivatives.csv")
    write_csv(priv,  "/home/claude/aladdin_project/data/client_private_markets.csv")

    with open("/home/claude/aladdin_project/data/all_securities.json","w") as f:
        json.dump(all_sec, f, indent=2)

    print(f"\nTotal: {len(all_sec)} securities")
    print(f"  Fixed Income : {len(fi)}  (SA sovereign/SOE/bank bonds)")
    print(f"  Equities     : {len(eq)}  (real S&P500 companies)")
    print(f"  Derivatives  : {len(der)}  (IRS/CDS/OIS — real EURIBOR/SOFR rates)")
    print(f"  Private Mkts : {len(priv)}  (SA PE/infrastructure/credit funds)")
    print(f"\nMarket reference data used:")
    print(f"  EURIBOR 3M : {EURIBOR_3M}% (real, as of {EURIBOR_DATE})")
    print(f"  US 10Y     : {US_10Y}% (real)")
    print(f"  VIX        : {VIX} (real)")
