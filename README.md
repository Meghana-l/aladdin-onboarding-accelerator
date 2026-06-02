# Aladdin Client Onboarding Accelerator

**AI-powered reference data validation tool for Aladdin client onboarding.**  
Built as a project submission for the BlackRock Data Implementation Specialist – Associate role.

---

## What makes this real

### Real data sources
- **S&P 500 constituents** (GitHub): real company names, real GICS sectors — used for the equity portfolio
- **EURIBOR 3M** (GitHub): live rate used to validate EUR swap fixed rates
- **US 10Y Treasury yield** (GitHub): used to check derivative rate reasonableness
- **VIX** (GitHub): market stress context embedded in every risk-related issue flag

### Real reconciliation logic
The engine runs 25+ checks against actual Aladdin data conventions — the same rules the Data Implementation team applies manually. Issues it detects include:

| Issue Type | Asset Class | How it's detected |
|---|---|---|
| Duration vs YTM discrepancy | Fixed Income | Client value vs computed value > 0.4 year tolerance |
| Float index non-ISDA format | Derivatives | `USD-SOFR` vs required `USD-SOFR-CME` |
| Benchmark ID wrong format | FI + Equity | Client uses `ALSI`, Aladdin requires `FTSE-JSE-ALSI40` |
| NAV staleness >90 days | Private Markets | Aladdin's published freshness threshold |
| Missing derivative notional | Derivatives | Go-live blocker — Aladdin cannot price |
| GICS sector mismatch | Equity | Client classification vs MSCI standard |
| CPI flag wrong on linkers | Fixed Income | Cross-check name vs field value |
| Currency unit error (GBP/GBp) | Equity | 100x price error on dual-listed names |

### Real AI classification
Claude API classifies each issue with: root cause, recommended fix action, go-live risk flag, confidence score. Falls back to demo mode without an API key.

---

## Results on STANLIB demo run

| Asset Class | Securities | Readiness | Issues |
|---|---|---|---|
| Fixed Income | 60 | 48% ⚠️ | 84 |
| Equity | 40 | 75% ✅ | 22 |
| Derivatives | 25 | 44% 🔴 | 32 |
| Private Markets | 15 | 20% 🔴 | 23 |
| **Total** | **140** | **47% ❌** | **161** |

33 critical go-live blockers. Not UAT-ready.

---

## How to run

```bash
pip install pandas numpy

# 1. Fetch real market data + build security master
python generate_data.py

# 2. Run validation engine
python reconcile.py

# 3. AI classification (set key for real calls, or runs demo mode)
export ANTHROPIC_API_KEY=your_key
python ai_classify.py

# 4. Open dashboard (works standalone — data is embedded)
open aladdin_onboarding_accelerator_FINAL.html
```


