import os
import requests
import json
from datetime import datetime, timedelta
from supabase import create_client, Client

# --- 1. CONFIGURATION ---
# These are stored securely in GitHub Secrets, NOT hardcoded.
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
ODDS_API_KEY = os.environ.get("ODDS_API_KEY")

# Initialize Supabase client
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Sports to check (multi-sport focus)
SPORTS_LIST = ["baseball_mlb", "basketball_nba", "hockey_nhl", "americanfootball_nfl", "tennis_atp", "golf_pga_championship"]

def fetch_odds(sport_key):
    """Queries The Odds API for team lines (-110 range) for a specific sport."""
    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/?apiKey={ODDS_API_KEY}&regions=us&markets=h2h&oddsFormat=american"
    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error fetching odds for {sport_key}: {e}")
        return []

def filter_fatty_picks(data, target_min=-115, target_max=-105):
    """Filters events to isolate lines closest to -110."""
    qualified_picks = []
    
    # Analyze only games happening in the next 24 hours
    tomorrow = (datetime.utcnow() + timedelta(days=1)).strftime("%Y-%m-%d")

    for game in data:
        game_time = game['commence_time'].split('T')[0]
        if game_time != tomorrow:
            continue

        for bookmaker in game.get('bookmakers', []):
            if bookmaker['key'] == 'draftkings': # Standardize on one bookmaker for consistency
                markets = bookmaker.get('markets', [])
                for market in markets:
                    if market['key'] == 'h2h':
                        for outcome in market['outcomes']:
                            price = outcome['price']
                            # Check if price falls within the -110 range
                            if target_min <= price <= target_max:
                                qualified_picks.append({
                                    'event_date': game_time,
                                    'sport': game['sport_title'],
                                    'matchup': f"{game['home_team']} vs {game['away_team']}",
                                    'pick': outcome['name'],
                                    'odds': price
                                })
    return qualified_picks

def select_top_three_to_two(candidates):
    """Applies secondary edge logic to select the Top 3, then Top 2."""
    if len(candidates) < 3:
        print("Not enough qualified picks (-110 range) found today.")
        return [], []

    # Secondary sorting logic (Example: sort by closest to -110 absolute value)
    # Fatty's 'Clever Dog' logic: we prioritize stability.
    candidates.sort(key=lambda x: abs(x['odds'] + 110))

    # Identify the Top 3 candidate legs
    top_three = candidates[:3]
    
    # Identify the Top 2 (the definitive picks)
    top_two = top_three[:2]
    excluded_leg = top_three[2] if len(top_three) > 2 else None

    print(f"Found {len(top_three)} Top Legs. Top 2 are definitively: {[p['pick'] for p in top_two]}")
    if excluded_leg:
        print(f"Excluded Leg: {excluded_leg['pick']}")

    return top_two, top_three

def save_picks_to_cloud(picks):
    """Saves the final Top 2 selections to the persistent Supabase DB."""
    if not picks: return

    records_to_insert = []
    for pick in picks:
        records_to_insert.append({
            "event_date": pick['event_date'],
            "sport": pick['sport'],
            "matchup": pick['matchup'],
            "pick": pick['pick'],
            "odds": pick['odds'],
            "status": 'pending'
        })
    
    try:
        response = supabase.table('bets').insert(records_to_insert).execute()
        print(f"Successfully saved {len(picks)} picks to the cloud DB.")
    except Exception as e:
        print(f"Error saving to Supabase: {e}")

# --- MAIN EXECUTION ---
if __name__ == "__main__":
    all_qualified_candidates = []
    
    # Loop through multiple sports to find cross-sport options
    for sport in SPORTS_LIST:
        raw_odds = fetch_odds(sport)
        sport_candidates = filter_fatty_picks(raw_odds)
        all_qualified_candidates.extend(sport_candidates)

    # Apply the Fatty Rodriguez 3-to-2 selection engine
    final_picks, all_legs = select_top_three_to_two(all_qualified_candidates)
    
    # Save only the designated Top 2 plays to the database
    save_picks_to_cloud(final_picks)