import os
import requests
from datetime import datetime
import zoneinfo
from supabase import create_client, Client

# --- 1. CONFIGURATION ---
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
ODDS_API_KEY = os.environ.get("ODDS_API_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

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
    et_tz = zoneinfo.ZoneInfo("America/New_York")
    return datetime.now(et_tz).strftime("%Y-%m-%d")

def check_existing_today_parlay(today_str):
    """Checks if today's parlay has already been generated and locked."""
    try:
        res = supabase.table('bets').select('*').eq('event_date', today_str).execute()
        if res.data and len(res.data) >= 2:
            print(f"Today's parlay ({today_str}) is ALREADY LOCKED. Skipping regeneration.")
            return True
    except Exception as e:
        print(f"Error checking existing bets: {e}")
    return False

def fetch_odds(sport_key):
    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/?apiKey={ODDS_API_KEY}&regions=us&markets=h2h&oddsFormat=american"
    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error fetching odds for {sport_key}: {e}")
        return []

def filter_fatty_picks(data, today_str, target_min=-115, target_max=-105):
    """Filters events strictly occurring TODAY in Eastern Time near -110 odds."""
    qualified = []
    et_tz = zoneinfo.ZoneInfo("America/New_York")

    for game in data:
        # Parse commence time and convert to US Eastern Time
        commence_utc = datetime.fromisoformat(game['commence_time'].replace('Z', '+00:00'))
        commence_et = commence_utc.astimezone(et_tz)
        game_date_et = commence_et.strftime("%Y-%m-%d")

        # STRICT RULE: Must be a game played TODAY
        if game_date_et != today_str:
            continue

        for bookmaker in game.get('bookmakers', []):
            if bookmaker['key'] == 'draftkings': # Standardized reference book
                for market in bookmaker.get('markets', []):
                    if market['key'] == 'h2h':
                        for outcome in market['outcomes']:
                            price = outcome['price']
                            if target_min <= price <= target_max:
                                qualified.append({
                                    'sport': game['sport_title'],
                                    'matchup': f"{game['home_team']} vs {game['away_team']}",
                                    'pick': outcome['name'],
                                    'odds': price
                                })
    return qualified

def select_top_two(candidates):
    if len(candidates) < 2:
        print("Not enough qualified same-day legs near -110 found today.")
        return []
    # Sort candidates by closest distance to standard -110 odds
    candidates.sort(key=lambda x: abs(x['odds'] + 110))
    return candidates[:2]

if __name__ == "__main__":
    today_str = get_today_str_et()
    print(f"Running Fatty Rodriguez Scanner for Date: {today_str} (ET)")
    
    # 1. Check if today's parlay is already locked
    if not check_existing_today_parlay(today_str):
        all_candidates = []
        for sport in SPORTS_LIST:
            raw = fetch_odds(sport)
            all_candidates.extend(filter_fatty_picks(raw, today_str))

        best_two = select_top_two(all_candidates)
        
        # 2. Lock in today's single 2-Leg Parlay ($2 Wager)
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
            supabase.table('bets').insert(records).execute()
            print(f"Successfully locked today's same-day 2-leg parlay for {today_str}!")
        else:
            print("Could not form a 2-leg parlay strictly from today's games.")
