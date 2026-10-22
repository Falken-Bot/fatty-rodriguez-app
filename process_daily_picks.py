import os
import sys
import requests
from datetime import datetime

# --- CREDENTIAL STRIPPING ---
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "").strip()
ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "").strip()

# Guarantee we hit the base domain root without redundant subpaths
if "/rest/v1" in SUPABASE_URL:
    SUPABASE_URL = SUPABASE_URL.split("/rest/v1")[0]

SPORTS_LIST = [
    "baseball_mlb", 
    "basketball_nba", 
    "icehockey_nhl", 
    "americanfootball_nfl"
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

def filter_fatty_picks(data, today_str, target_min=-150, target_max=130):
    qualified = []
    for game in data:
        commence_raw = game.get('commence_time', '')
        if not commence_raw:
            continue
            
        game_date = commence_raw.split('T')[0]
        if game_date != today_str:
            continue

        for bookmaker in game.get('bookmakers', []):
            for market in bookmaker.get('markets', []):
                for outcome in market.get('outcomes', []):
                    price = outcome.get('price')
                    if price and (target_min <= price <= target_max):
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

def select_top_two(candidates):
    if len(candidates) < 2:
        return []
    
    unique_candidates = []
    seen_matchups = set()
    for c in candidates:
        if c['matchup'] not in seen_matchups:
            seen_matchups.add(c['matchup'])
            unique_candidates.append(c)

    unique_candidates.sort(key=lambda x: abs(x['odds'] + 110))
    return unique_candidates[:2]

def save_bets_direct_http(records):
    """Direct PostgREST HTTP insertion targeting the verified endpoint."""
    target_endpoint = f"{SUPABASE_URL}/rest/v1/bets"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }
    
    res = requests.post(target_endpoint, json=records, headers=headers)
    if res.status_code in [200, 201]:
        print(f"SUCCESS: Successfully saved {len(records)} bets directly to Supabase!")
    else:
        print(f"Supabase HTTP Error ({res.status_code}): {res.text}")

if __name__ == "__main__":
    today_str = get_today_str_et()
    print(f"Running Fatty Rodriguez Scanner for Date: {today_str}")
    
    all_candidates = []
    for sport in SPORTS_LIST:
        raw = fetch_odds(sport)
        all_candidates.extend(filter_fatty_picks(raw, today_str))

    best_two = select_top_two(all_candidates)
    
    if len(best_two) == 2:
        records = []
        for pick in best_two:
            records.append({
                "event_date": today_str,
                "sport": pick['sport'],
                "matchup": pick['matchup'],
                "pick": pick['pick'],
                "odds": pick['odds'],
                "wager_amount": 2.00,
                "status": 'pending'
            })
        save_bets_direct_http(records)
    else:
        print("Could not find 2 qualified legs strictly taking place today.")
