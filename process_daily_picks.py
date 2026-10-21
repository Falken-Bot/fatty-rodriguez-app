import os
import sys
import requests
from datetime import datetime

# --- 1. SAFE IMPORTS & CREDENTIAL STRIPPING ---
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "").strip()
ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "").strip()

print(f"DEBUG: SUPABASE_URL set: {bool(SUPABASE_URL)}")
print(f"DEBUG: SUPABASE_KEY set: {bool(SUPABASE_KEY)}")
print(f"DEBUG: ODDS_API_KEY set: {bool(ODDS_API_KEY)}")

try:
    from supabase import create_client, Client
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    print(f"CRITICAL ERROR initializing Supabase client: {e}")
    sys.exit(1)

SPORTS_LIST = [
    "baseball_mlb", 
    "basketball_nba", 
    "hockey_nhl", 
    "americanfootball_nfl", 
    "tennis_atp", 
    "golf_pga_championship"
]

def get_today_str_et():
    """Returns today's date formatted as YYYY-MM-DD in US Eastern Time."""
    try:
        import zoneinfo
        et_tz = zoneinfo.ZoneInfo("America/New_York")
        return datetime.now(et_tz).strftime("%Y-%m-%d")
    except Exception:
        # Fallback to standard UTC date if zoneinfo is unavailable
        return datetime.utcnow().strftime("%Y-%m-%d")

def check_existing_today_parlay(today_str):
    try:
        res = supabase.table('bets').select('*').eq('event_date', today_str).execute()
        if res.data and len(res.data) >= 2:
            print(f"Today's parlay ({today_str}) is ALREADY LOCKED in Supabase.")
            return True
    except Exception as e:
        print(f"Notice: Error checking existing bets from Supabase: {e}")
    return False

def fetch_odds(sport_key):
    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/?apiKey={ODDS_API_KEY}&regions=us&markets=h2h,spreads,totals&oddsFormat=american"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error fetching odds for {sport_key}: {e}")
        return []

def filter_fatty_picks(data, today_str, target_min=-130, target_max=110):
    qualified = []
    for game in data:
        commence_raw = game.get('commence_time', '')
        if not commence_raw:
            continue
            
        game_date = commence_raw.split('T')[0]
        # Match against today's date
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
        print("Not enough qualified same-day legs found.")
        return []
    
    unique_candidates = []
    seen_matchups = set()
    for c in candidates:
        if c['matchup'] not in seen_matchups:
            seen_matchups.add(c['matchup'])
            unique_candidates.append(c)

    unique_candidates.sort(key=lambda x: abs(x['odds'] + 110))
    return unique_candidates[:2]

if __name__ == "__main__":
    today_str = get_today_str_et()
    print(f"Running Fatty Rodriguez Scanner for Date: {today_str}")
    
    if not check_existing_today_parlay(today_str):
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
            try:
                supabase.table('bets').insert(records).execute()
                print(f"Successfully locked today's same-day 2-leg parlay for {today_str}!")
            except Exception as e:
                print(f"Error inserting picks into Supabase: {e}")
        else:
            print("Could not find 2 qualified legs strictly taking place today.")
