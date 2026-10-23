import os
import re
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "")

SPORTS_KEYS = {
    # NBA
    "BASKETBALL NBA": "basketball_nba",
    "BASKETBALL_NBA": "basketball_nba",
    "NBA": "basketball_nba",

    # NHL
    "ICEHOCKEY NHL": "icehockey_nhl",
    "ICE_HOCKEY_NHL": "icehockey_nhl",
    "ICEHOCKEY_NHL": "icehockey_nhl",
    "NHL": "icehockey_nhl",

    # NFL
    "AMERICANFOOTBALL NFL": "americanfootball_nfl",
    "AMERICAN_FOOTBALL_NFL": "americanfootball_nfl",
    "AMERICANFOOTBALL_NFL": "americanfootball_nfl",
    "NFL": "americanfootball_nfl",

    # NCAAF
    "AMERICANFOOTBALL NCAAF": "americanfootball_ncaaf",
    "AMERICANFOOTBALL_NCAAF": "americanfootball_ncaaf",
    "NCAAF": "americanfootball_ncaaf"
}

def get_supabase_endpoint():
    clean_url = SUPABASE_URL.rstrip('/')
    if clean_url.endswith('/rest/v1'):
        return clean_url
    return f"{clean_url}/rest/v1"

def get_pending_bets():
    endpoint = get_supabase_endpoint()
    url = f"{endpoint}/bets?status=ilike.pending&select=*"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}"
    }
    try:
        res = requests.get(url, headers=headers)
        if res.status_code == 200:
            return res.json()
        print(f"Error fetching pending bets ({res.status_code}): {res.text}")
        return []
    except Exception as e:
        print(f"Failed to query Supabase: {e}")
        return []

def fetch_completed_scores(sport_key):
    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/scores/"
    params = {
        "apiKey": ODDS_API_KEY,
        "daysFrom": 3
    }
    try:
        res = requests.get(url, params=params)
        if res.status_code == 200:
            data = res.json()
            print(f"DEBUG: Fetched {len(data)} games for {sport_key}")
            return data
        print(f"Error fetching scores for {sport_key} ({res.status_code}): {res.text}")
        return []
    except Exception as e:
        print(f"Failed to fetch scores for {sport_key}: {e}")
        return []

def parse_leg(leg_str):
    clean = leg_str.replace("LEG1:", "").replace("LEG2:", "").replace("DROPPED:", "").strip()
    parts = [p.strip() for p in clean.split('|')]
    if len(parts) < 3:
        return None
    
    sport_raw = parts[0]
    matchup_raw = parts[1]
    pick_raw = parts[2]
    
    # Example pick_raw inputs:
    # "New England Patriots (+9.5)"
    # "Chicago Blackhawks (-110)" -> Moneyline
    # "Over 210.5 (-110)"
    
    # 1. Extract odds/handicap values inside parentheses
    spread_value = 0.0
    match = re.search(r'\(([^)]+)\)', pick_raw)
    
    clean_pick_name = re.sub(r'\([^)]*\)', '', pick_raw).replace("Pick:", "").strip()

    if match:
        val_str = match.group(1).strip()
        # If input has market odds like +100 or -110 but also a spread point, parse numeric spread point
        # e.g., "Patriots +9.5 (+100)" vs "Patriots (+9.5)"
        spread_matches = re.findall(r'([+-]?\d+\.?\d*)', val_str)
        if spread_matches:
            # Check if there is a spread modifier inside or prior to odds
            num = float(spread_matches[0])
            # Exclude standard American moneyline odds (-110, +150) if no point spread is explicitly designated
            if abs(num) < 50.0 or '.' in spread_matches[0]:
                spread_value = num

    # Also check if spread point is directly in team name, e.g. "New England Patriots +9.5"
    point_match = re.search(r'([+-]\d+\.?\d*)$', clean_pick_name)
    if point_match:
        spread_value = float(point_match.group(1))
        clean_pick_name = clean_pick_name[:point_match.start()].strip()

    return {
        "sport": sport_raw,
        "matchup": matchup_raw,
        "team": clean_pick_name,
        "spread": spread_value
    }

def parse_parlay(pick_payload):
    legs = []
    parts = pick_payload.split('||')
    for part in parts:
        part = part.strip()
        if part.startswith("LEG1:") or part.startswith("LEG2:"):
            parsed = parse_leg(part)
            if parsed:
                legs.append(parsed)
    return legs

def evaluate_leg_outcome(leg, scores_by_sport):
    raw_sport = leg["sport"].upper().replace("_", " ").strip()
    sport_key = SPORTS_KEYS.get(raw_sport) or SPORTS_KEYS.get(leg["sport"].upper().strip())
    
    if not sport_key:
        print(f"DEBUG: Unknown sport key for '{leg['sport']}'")
        return None

    scores = scores_by_sport.get(sport_key, [])
    picked_team = leg["team"].lower()
    spread = leg["spread"]

    for game in scores:
        home_team = game.get("home_team", "")
        away_team = game.get("away_team", "")
        completed = game.get("completed", False)

        if picked_team not in [home_team.lower(), away_team.lower()]:
            continue

        print(f"DEBUG: Checking game [{away_team} @ {home_team}] | Completed: {completed} | Pick: {leg['team']} | Spread Point: {spread:+g}")

        if not completed:
            continue

        game_scores = game.get("scores", [])
        if not game_scores or len(game_scores) < 2:
            print(f"DEBUG: Game completed but scores array invalid: {game_scores}")
            continue

        home_score = 0
        away_score = 0
        for s in game_scores:
            if s.get("name", "").lower() == home_team.lower():
                home_score = float(s.get("score", 0))
            elif s.get("name", "").lower() == away_team.lower():
                away_score = float(s.get("score", 0))

        # Determine scores with spread applied
        if picked_team == home_team.lower():
            adjusted_picked_score = home_score + spread
            opponent_score = away_score
        else:
            adjusted_picked_score = away_score + spread
            opponent_score = home_score

        print(f"DEBUG: Score Matrix - Raw: [{away_team} {away_score} @ {home_team} {home_score}] | Adjusted Pick Score: {adjusted_picked_score} vs Opponent: {opponent_score}")

        if adjusted_picked_score > opponent_score:
            return "win"
        elif adjusted_picked_score < opponent_score:
            return "loss"
        else:
            return "push"

    return None

def update_bet_status(bet_id, new_status):
    endpoint = get_supabase_endpoint()
    url = f"{endpoint}/bets?id=eq.{bet_id}"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal"
    }
    data = {"status": new_status}
    try:
        res = requests.patch(url, json=data, headers=headers)
        if res.status_code in [200, 204]:
            print(f"Successfully updated Bet #{bet_id} to status '{new_status}'.")
        else:
            print(f"Failed updating Bet #{bet_id} ({res.status_code}): {res.text}")
    except Exception as e:
        print(f"Exception updating Bet #{bet_id}: {e}")

def main():
    print("Initiating automated bet grading sweep...")
    pending_bets = get_pending_bets()
    print(f"Found {len(pending_bets)} pending bet record(s) to grade.")

    if not pending_bets:
        return

    # Cache scores for all mapped sports
    scores_by_sport = {}
    unique_sport_keys = set(SPORTS_KEYS.values())
    for sport_key in unique_sport_keys:
        scores_by_sport[sport_key] = fetch_completed_scores(sport_key)

    for bet in pending_bets:
        bet_id = bet.get("id")
        pick_payload = bet.get("pick", "")

        legs = parse_parlay(pick_payload)
        if not legs:
            print(f"Bet #{bet_id}: Unable to parse pick payload.")
            continue

        leg_results = []
        for leg in legs:
            res = evaluate_leg_outcome(leg, scores_by_sport)
            leg_results.append(res)

        print(f"DEBUG: Bet #{bet_id} leg results evaluation: {leg_results}")

        if "loss" in leg_results:
            final_status = "loss"
        elif None in leg_results:
            final_status = "pending"
        elif "push" in leg_results:
            final_status = "push"
        elif all(r == "win" for r in leg_results):
            final_status = "win"
        else:
            final_status = "pending"

        if final_status != "pending":
            print(f"Grading Bet #{bet_id} -> Result: {final_status.upper()}")
            update_bet_status(bet_id, final_status)
        else:
            print(f"Bet #{bet_id}: Remains pending (waiting on incomplete games).")

if __name__ == "__main__":
    main()
