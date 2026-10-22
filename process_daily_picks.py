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

def distill_cross_sport_parlay(candidates):
    if len(candidates) < 3:
        print("Fewer than 3 total candidate picks available across markets.")
        return []

    # Deduplicate matchups
    unique = []
    seen = set()
    for c in candidates:
        if c['matchup'] not in seen:
            seen.add(c['matchup'])
            unique.append(c)

    # Sort candidates by proximity to standard value (-110 baseline)
    unique.sort(key=lambda x: abs(x['odds'] + 110))

    # Pull top 3 candidate legs
    top_three = unique[:3]

    # Verify cross-sport requirement
    sports_present = {c['sport'] for c in top_three}
    if len(sports_present) < 2:
        # If top 3 are all one sport, force second sport insertion if available in remaining candidates
        alt_sport_candidate = next((c for c in unique[3:] if c['sport'] not in sports_present), None)
        if alt_sport_candidate:
            top_three[2] = alt_sport_candidate
        else:
            print("Could not enforce cross-sport requirement: only one sport available today.")
            return []

    # Distill 3 candidate legs down to the Final 2
    final_two = top_three[:2]
    return final_two

def save_bets_direct_http(records):
    target_endpoint = f"{SUPABASE_URL}/rest/v1/bets"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }
    
    res = requests.post(target_endpoint, json=records, headers=headers)
    if res.status_code in [200, 201]:
        print(f"SUCCESS: Successfully saved {len(records)} cross-sport bets directly to Supabase!")
    else:
        print(f"Supabase HTTP Error ({res.status_code}): {res.text}")

if __name__ == "__main__":
    today_str = get_today_str_et()
    print(f"Running Fatty Rodriguez Cross-Sport Engine for Date: {today_str}")
    
    all_candidates = []
    for sport in SPORTS_LIST:
        raw = fetch_odds(sport)
        all_candidates.extend(filter_fatty_picks(raw, today_str))

    best_two = distill_cross_sport_parlay(all_candidates)
    
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
        print("Could not complete cross-sport distillation for today.")
