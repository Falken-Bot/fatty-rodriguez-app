import os
import sys
import requests
from datetime import datetime

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://ejnwsxbpuumcpyxnmsaz.supabase.co").strip().rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "sb_publishable_M4seLrgZoXLBY9m01uMa1Q_ZFHBW1Dp").strip()
ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "").strip()

if "/rest/v1" in SUPABASE_URL:
    SUPABASE_URL = SUPABASE_URL.split("/rest/v1")[0]

SPORTS_LIST = [
    "americanfootball_nfl",
    "basketball_nba",
    "icehockey_nhl",
    "baseball_mlb"
]

def get_today_str_et():
    try:
        import zoneinfo
        et_tz = zoneinfo.ZoneInfo("America/New_York")
        return datetime.now(et_tz).strftime("%Y-%m-%d")
    except Exception:
        return datetime.utcnow().strftime("%Y-%m-%d")

def fetch_odds(sport_key):
    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/?apiKey={ODDS_API_KEY}&regions=us&markets=h2h,spreads,totals&oddsFormat=american"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error fetching odds for {sport_key}: {e}")
        return []

def filter_fatty_picks(data, today_str, target_min=-130, target_max=130):
    qualified = []
    for game in data:
        commence_raw = game.get('commence_time', '')
        if not commence_raw or commence_raw.split('T')[0] != today_str:
            continue

        for bookmaker in game.get('bookmakers', []):
            for market in bookmaker.get('markets', []):
                for outcome in market.get('outcomes', []):
                    price = outcome.get('price')
                    if price is not None and (target_min <= price <= target_max):
                        pick_label = outcome['name']
                        if 'point' in outcome:
                            pick_label += f" ({outcome['point']:+g})"

                        qualified.append({
                            'sport': game.get('sport_title', 'Sports'),
                            'matchup': f"{game.get('home_team', '')} vs {game.get('away_team', '')}",
                            'pick': pick_label,
                            'odds': price
                        })
    return qualified

def build_distilled_cross_sport_parlay(candidates):
    if not candidates:
        print("No qualified candidates found today.")
        return None

    # Step 1: Group candidates by Sport and deduplicate by matchup
    by_sport = {}
    for c in candidates:
        sport = c['sport']
        if sport not in by_sport:
            by_sport[sport] = []
        
        # Avoid duplicate matchups within the same sport
        if not any(existing['matchup'] == c['matchup'] for existing in by_sport[sport]):
            by_sport[sport].append(c)

    # Sort each sport's candidates by proximity to -110 even money baseline
    for sport in by_sport:
        by_sport[sport].sort(key=lambda x: abs(x['odds'] + 110))

    available_sports = list(by_sport.keys())
    if len(available_sports) < 2:
        print(f"FAILED: Need at least 2 distinct sports available today, but only found {len(available_sports)} ({available_sports}).")
        return None

    # Step 2: Pick best candidate from Sport A and best candidate from Sport B
    leg1 = by_sport[available_sports[0]][0]
    leg2 = by_sport[available_sports[1]][0]

    # Step 3: Find a distinct candidate for the Distilled Leg (Leg 3)
    leg3 = None
    
    # Try a 3rd sport first if available
    if len(available_sports) >= 3 and len(by_sport[available_sports[2]]) > 0:
        leg3 = by_sport[available_sports[2]][0]
    else:
        # Otherwise, take the next best distinct matchup from Sport A or Sport B
        for s in available_sports:
            for item in by_sport[s]:
                if item['matchup'] != leg1['matchup'] and item['matchup'] != leg2['matchup']:
                    leg3 = item
                    break
            if leg3:
                break

    if not leg3:
        print("Could not find a distinct 3rd candidate leg to distill out.")
        return None

    return {
        "leg1": leg1,
        "leg2": leg2,
        "leg3": leg3
    }

def save_parlay_direct_http(record):
    target_endpoint = f"{SUPABASE_URL}/rest/v1/bets"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }
    
    res = requests.post(target_endpoint, json=[record], headers=headers)
    if res.status_code in [200, 201]:
        print("SUCCESS: Successfully saved distilled cross-sport parlay package to Supabase!")
    else:
        print(f"Supabase HTTP Error ({res.status_code}): {res.text}")

if __name__ == "__main__":
    today_str = get_today_str_et()
    print(f"Running Fatty Rodriguez Cross-Sport Engine for Date: {today_str}")
    
    all_candidates = []
    for sport in SPORTS_LIST:
        raw = fetch_odds(sport)
        all_candidates.extend(filter_fatty_picks(raw, today_str))

    parlay_pkg = build_distilled_cross_sport_parlay(all_candidates)
    
    if parlay_pkg:
        l1 = parlay_pkg['leg1']
        l2 = parlay_pkg['leg2']
        l3 = parlay_pkg['leg3']

        fmt_l1 = f"{l1['sport']} | {l1['matchup']} | Pick: {l1['pick']} ({'+' if l1['odds']>0 else ''}{l1['odds']})"
        fmt_l2 = f"{l2['sport']} | {l2['matchup']} | Pick: {l2['pick']} ({'+' if l2['odds']>0 else ''}{l2['odds']})"
        fmt_l3 = f"{l3['sport']} | {l3['matchup']} | Pick: {l3['pick']} ({'+' if l3['odds']>0 else ''}{l3['odds']})"

        record = {
            "event_date": today_str,
            "sport": "CROSS-SPORT PARLAY",
            "matchup": f"{l1['sport']} & {l2['sport']}",
            "pick": f"LEG1: {fmt_l1} || LEG2: {fmt_l2} || DROPPED: {fmt_l3}",
            "odds": l1['odds'],
            "wager_amount": 2.00,
            "status": "pending"
        }
        save_parlay_direct_http(record)
    else:
        print("Could not build a qualifying cross-sport parlay today.")
