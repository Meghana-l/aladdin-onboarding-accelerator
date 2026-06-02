"""
ai_classify.py
==============
Sends each data issue to the Claude API for intelligent classification.
This is the "AI-powered anomaly detection" the JD explicitly calls out.

Each issue gets:
  - root_cause  : why this likely happened (source system, mapping gap, etc.)
  - fix_action  : the concrete step the implementation team should take
  - go_live_risk: whether this blocks go-live (True/False)
  - confidence  : AI confidence score 0-1

The human reviewer (the Data Implementation Associate = Meghana) then validates
and approves each AI recommendation before it's actioned — human-in-the-loop.
"""

import json
import time
import urllib.request
import urllib.error

API_URL = "https://api.anthropic.com/v1/messages"

SYSTEM_PROMPT = """You are a BlackRock Aladdin Data Implementation specialist with 
deep expertise in investment data, fixed income analytics, derivatives, and private markets.

You are reviewing data quality issues found during a client onboarding to the Aladdin platform.
The client is STANLIB South Africa.

For each issue, respond ONLY with valid JSON in this exact format:
{
  "root_cause": "1-2 sentences explaining why this data error likely occurred in the client's source system or feed",
  "fix_action": "Specific, actionable step the implementation team should take to resolve this",
  "go_live_risk": true or false,
  "confidence": 0.0 to 1.0
}

Be technically precise. Reference Aladdin conventions, ISDA standards, Bloomberg field names, 
or custodian interface specifics where relevant. Keep root_cause and fix_action under 40 words each."""

def classify_issue(issue: dict, api_key: str) -> dict:
    """Call Claude API to classify a single issue. Returns enriched issue dict."""

    prompt = f"""Issue to classify:
Security: {issue['name']} ({issue['isin']})
Asset class: {issue['asset_class']}
Check: {issue['check_name']}
Field: {issue['field']}
Client value: "{issue['client_value']}"
Expected (Aladdin): "{issue['expected']}"
Severity: {issue['severity']}

Classify this data issue."""

    payload = {
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 300,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": prompt}]
    }

    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01"
    }

    req = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode(),
        headers=headers,
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            text = data["content"][0]["text"].strip()
            # Strip markdown fences if present
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            result = json.loads(text)
            issue["root_cause"]   = result.get("root_cause","")
            issue["fix_action"]   = result.get("fix_action","")
            issue["go_live_risk"] = result.get("go_live_risk", issue["severity"]=="critical")
            issue["ai_confidence"]= result.get("confidence", 0.9)
            issue["ai_status"]    = "classified"
    except urllib.error.HTTPError as e:
        issue["root_cause"]   = f"[API error {e.code}]"
        issue["fix_action"]   = "Manual review required"
        issue["go_live_risk"] = issue["severity"] == "critical"
        issue["ai_confidence"]= 0.0
        issue["ai_status"]    = "error"
    except Exception as e:
        issue["root_cause"]   = f"[Error: {str(e)[:60]}]"
        issue["fix_action"]   = "Manual review required"
        issue["go_live_risk"] = issue["severity"] == "critical"
        issue["ai_confidence"]= 0.0
        issue["ai_status"]    = "error"

    return issue

def run_classification(issues_path: str, output_path: str, api_key: str,
                        max_issues: int = None, rate_limit_delay: float = 0.5):
    """
    Load issues, classify each with AI, save enriched output.
    max_issues: limit for demo/testing purposes (None = classify all)
    """
    with open(issues_path) as f:
        issues = json.load(f)

    if max_issues:
        issues = issues[:max_issues]

    total = len(issues)
    print(f"Classifying {total} issues with Claude AI...\n")

    classified = []
    for i, issue in enumerate(issues):
        print(f"  [{i+1}/{total}] {issue['check_name']} — {issue['name'][:35]}...", end=" ", flush=True)
        result = classify_issue(issue, api_key)
        classified.append(result)

        status_icon = "✓" if result.get("ai_status") == "classified" else "✗"
        glr = "🚨 GO-LIVE BLOCK" if result.get("go_live_risk") else ""
        print(f"{status_icon} {glr}")

        time.sleep(rate_limit_delay)   # be polite to the API

    with open(output_path, "w") as f:
        json.dump(classified, f, indent=2)

    n_classified = sum(1 for i in classified if i.get("ai_status")=="classified")
    n_blockers   = sum(1 for i in classified if i.get("go_live_risk"))
    print(f"\nClassification complete.")
    print(f"  Classified   : {n_classified}/{total}")
    print(f"  Go-live blockers flagged: {n_blockers}")
    print(f"  Output saved : {output_path}")
    return classified

# ── Standalone scoring: compute onboarding readiness score ───────────────────

def compute_readiness_score(issues: list[dict], total_securities: int) -> dict:
    """
    Readiness score = weighted quality score per asset class.
    Critical issues penalise heavily, low issues lightly.
    Score of 100 = ready to go live.
    """
    WEIGHTS = {"critical": 10, "high": 4, "medium": 2, "low": 1}

    by_ac = {}
    for iss in issues:
        ac = iss["asset_class"]
        if ac not in by_ac:
            by_ac[ac] = {"penalty": 0, "count": 0}
        by_ac[ac]["penalty"] += WEIGHTS.get(iss["severity"], 1)
        by_ac[ac]["count"]   += 1

    # Per-asset-class score out of 100 (max penalty = 100 before clamping)
    ac_scores = {}
    for ac, data in by_ac.items():
        raw = max(0, 100 - data["penalty"])
        ac_scores[ac] = round(raw, 1)

    # Overall weighted average
    overall = round(sum(ac_scores.values()) / max(len(ac_scores),1), 1)
    blockers = sum(1 for i in issues if i.get("go_live_risk") or i.get("severity")=="critical")

    return {
        "overall_score": overall,
        "by_asset_class": ac_scores,
        "total_issues": len(issues),
        "go_live_blockers": blockers,
        "go_live_ready": blockers == 0 and overall >= 85,
    }

if __name__ == "__main__":
    import os, sys

    api_key = os.environ.get("ANTHROPIC_API_KEY","")
    if not api_key:
        print("Set ANTHROPIC_API_KEY environment variable.")
        print("\nRunning in DEMO MODE (no real API calls — outputs mock classifications)\n")
        # Demo mode: load issues and add mock classifications
        with open("/home/claude/aladdin_project/output/issues_raw.json") as f:
            issues = json.load(f)

        MOCK_ROOTS = [
            "Client security master uses settlement-date based duration from custodian feed rather than yield-to-maturity.",
            "Field name discrepancy: client system uses legacy Bloomberg field alias not recognised in Aladdin interface mapping.",
            "Client data extract filter excluded this field — likely a default-off flag in their portfolio system export.",
            "Source system variant of reference entity name; ISDA standard name differs from internal client naming convention.",
            "Day-count convention defaults to Act/360 in client system but Aladdin requires explicit mapping per instrument type.",
        ]
        MOCK_FIXES = [
            "Re-pull from LSEG/Bloomberg with correct yield-to-maturity convention and update interface mapping table.",
            "Update field mapping in Aladdin interface configuration to translate client field name to Aladdin standard.",
            "Contact client ops team to enable field in security master export. Retest with full data extract.",
            "Apply entity name normalization rule in intake pipeline. Map all variants to ISDA standard name.",
            "Add day-count override to interface mapping. Confirm with client which convention their custodian uses.",
        ]
        import random
        random.seed(99)
        for iss in issues:
            iss["root_cause"]    = random.choice(MOCK_ROOTS)
            iss["fix_action"]    = random.choice(MOCK_FIXES)
            iss["go_live_risk"]  = iss["severity"] == "critical"
            iss["ai_confidence"] = round(random.uniform(0.82, 0.97), 2)
            iss["ai_status"]     = "demo"

        with open("/home/claude/aladdin_project/output/issues_classified.json","w") as f:
            json.dump(issues, f, indent=2)
        print(f"Demo classifications written for {len(issues)} issues.")

        score = compute_readiness_score(issues, total_securities=140)
        with open("/home/claude/aladdin_project/output/readiness_score.json","w") as f:
            json.dump(score, f, indent=2)

        print("\n=== ONBOARDING READINESS SCORE ===")
        print(f"Overall score : {score['overall_score']} / 100")
        print(f"Go-live ready : {'YES ✓' if score['go_live_ready'] else 'NO ✗'}")
        print(f"Blockers      : {score['go_live_blockers']}")
        print("\nBy asset class:")
        for ac, s in score["by_asset_class"].items():
            bar = "█" * int(s/5)
            print(f"  {ac:<20}: {s:>5}/100  {bar}")
    else:
        classified = run_classification(
            issues_path="/home/claude/aladdin_project/output/issues_raw.json",
            output_path="/home/claude/aladdin_project/output/issues_classified.json",
            api_key=api_key,
            max_issues=30,          # classify top 30 for demo; remove limit for full run
            rate_limit_delay=0.3
        )
        score = compute_readiness_score(classified, total_securities=140)
        with open("/home/claude/aladdin_project/output/readiness_score.json","w") as f:
            json.dump(score, f, indent=2)
        print(f"\nOverall readiness: {score['overall_score']}/100  |  Blockers: {score['go_live_blockers']}")
