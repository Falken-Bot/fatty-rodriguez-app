import os
import sys
import requests
from datetime import datetime

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "").strip()
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

def distill_parlay_package(candidates):
    if len(candidates) < 3:
        print("Fewer than 3 candidate picks found across today's markets.")
        return None

    # Deduplicate by matchup
    unique = []
    seen_matchups = set()
    for c in candidates:
        if c['matchup'] not in seen_matchups:
            seen_matchups.add(c['matchup'])
            unique.append(c)

    if len(unique) < 3:
        print("Fewer than 3 unique matchup picks found across markets.")
        return None

    # Sort by value proximity to standard -110 line
    unique.sort(key=lambda x: abs(x['odds'] + 110))

    top_three = unique[:3]

    # Enforce cross-sport requirement in top three
    sports_present = {c['sport'] for c in top_three}
    if len(sports_present) < 2:
        alt_candidate = next((c for c in unique[3:] if c['sport'] not in sports_present), None)
        if alt_candidate:
            top_three[2] = alt_candidate
        else:
            print("Could not satisfy cross-sport requirement: only one sport available today.")
            return None

    # Identify active legs vs distilled out leg
    active_legs = top_three[:2]
    dropped_leg = top_three[2]

    reason = (
        f"Leg 3 ({dropped_leg['sport']}: {dropped_leg['pick']} @ {dropped_leg['odds']}) "
        f"was distilled out due to market value deviation relative to the top two cross-sport legs."
    )

    return {
        "active_legs": active_legs,
        "dropped_leg": dropped_leg,
        "distill_reason": reason
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
        print("SUCCESS: Successfully saved distilled 2-leg $2 parlay package to Supabase!")
    else:
        print(f"Supabase HTTP Error ({res.status_code}): {res.text}")

if __name__ == "__main__":
    today_str = get_today_str_et()
    print(f"Running Fatty Rodriguez Cross-Sport Engine for Date: {today_str}")
    
    all_candidates = []
    for sport in SPORTS_LIST:
        raw = fetch_odds(sport)
        all_candidates.extend(filter_fatty_picks(raw, today_str))

    parlay_pkg = distill_parlay_package(all_candidates)
    
    if parlay_pkg:
        # Save as a single combined record storing both active legs and the distilled leg
        record = {
            "event_date": today_str,
            "sport": "CROSS-SPORT PARLAY",
            "matchup": f"PARLAY: {parlay_pkg['active_legs'][0]['matchup']} | {parlay_pkg['active_legs'][1]['matchup']}",
            "pick": f"LEG 1: {parlay_pkg['active_legs'][0]['sport']} - {parlay_pkg['active_legs'][0]['pick']} ({parlay_pkg['active_legs'][0]['odds']}) || LEG 2: {parlay_pkg['active_legs'][1]['sport']} - {parlay_pkg['active_legs'][1]['pick']} ({parlay_pkg['active_legs'][1]['odds']}) || DROPPED: {parlay_pkg['dropped_leg']['sport']} - {parlay_pkg['dropped_leg']['pick']} ({parlay_pkg['dropped_leg']['odds']})",
            "odds": parlay_pkg['active_legs'][0]['odds'],
            "wager_amount": 2.00,
            "status": "pending"
        }
        save_parlay_direct_http(record)
    else:
        print("Could not build a qualifying cross-sport parlay today.")
