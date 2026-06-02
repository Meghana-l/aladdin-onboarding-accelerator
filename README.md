# Aladdin Client Onboarding Accelerator

## Live Demo
https://meghana-l.github.io/aladdin-onboarding-accelerator/

AI-powered reference data validation tool simulating an Aladdin client onboarding pipeline. A Python reconciliation engine checks 140 securities across fixed income, equities, derivatives and private markets against Aladdin conventions. Claude API classifies each issue with root cause and recommended fix.

---

## Project Structure

| File | What it does |
|---|---|
| `generate_data.py` | Fetches live market data (EURIBOR, US 10Y, VIX) and builds the client security master |
| `reconcile.py` | Runs validation checks against Aladdin conventions and outputs all issues |
| `ai_classify.py` | Sends each issue to Claude API for root cause analysis and fix recommendation |
| `index.html` | Live analyst dashboard — open this in your browser to see the full output |

---

## How to Run

### Step 1 — Install dependencies
```bash
pip install pandas numpy
```

### Step 2 — Add your Anthropic API key

Open `ai_classify.py` in any text editor and find this line:

```python
api_key = os.environ.get("ANTHROPIC_API_KEY","")
```

Replace it with:

```python
api_key = os.environ.get("ANTHROPIC_API_KEY","your_key_here")
```

Get your API key at https://console.anthropic.com

Without a key the script runs in demo mode automatically — no error.

### Step 3 — Run the scripts in order

```bash
# Fetches live EURIBOR, US 10Y Treasury, VIX and builds the security master
python generate_data.py

# Validates all 140 securities against Aladdin conventions
python reconcile.py

# Classifies each issue with Claude AI (or demo mode if no key set)
python ai_classify.py
```

### Step 4 — Open the dashboard

Double-click `index.html` or run:

```bash
open index.html
```

The dashboard works as a standalone file with no server needed — all pipeline output is embedded.

---

## What the Reconciliation Engine Checks

| Check | Asset Class | Aladdin Convention |
|---|---|---|
| Duration vs YTM | Fixed Income | Delta > 0.4 years flagged as critical |
| Convexity present | Fixed Income | Required for Aladdin risk analytics |
| Benchmark ID format | FI + Equity | Must be `FTSE-JSE-ALBI` not `ALBI` |
| Float index ISDA name | Derivatives | Must be `USD-SOFR-CME` not `USD-SOFR` |
| Notional present | Derivatives | Go-live blocker — Aladdin cannot price without it |
| NAV freshness | Private Markets | Aladdin requires NAV within 90 days |
| GICS sector vs MSCI | Equity | Client classification checked against MSCI standard |
| CPI flag on linkers | Fixed Income | Incorrect flag causes 4x duration calculation error |

---

## Real Data Sources

| Data | Source | Used for |
|---|---|---|
| S&P 500 constituents | GitHub public dataset | Real company names and GICS sectors |
| EURIBOR 3M | GitHub public dataset | Validating EUR swap fixed rates |
| US 10Y Treasury yield | GitHub public dataset | Derivative rate reasonableness checks |
| VIX | GitHub public dataset | Market stress context in issue flags |

---

## Results on STANLIB Demo Run

| Asset Class | Securities | Readiness | Issues |
|---|---|---|---|
| Fixed Income | 60 | 48% ⚠️ | 84 |
| Equity | 40 | 75% ✅ | 22 |
| Derivatives | 25 | 44% 🔴 | 32 |
| Private Markets | 15 | 20% 🔴 | 23 |
| **Overall** | **140** | **47% ❌** | **161** |

33 critical go-live blockers. Not UAT-ready.

---

*Meghana Lakshminarayana Swamy — MS Business Analytics, University of New Haven*
