import os
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "")

SPORTS_KEYS = {
    "BASKETBALL NBA": "basketball_nba",
    "ICEHOCKEY NHL": "icehockey_nhl",
    "AMERICANFOOTBALL NFL": "americanfootball_nfl"
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
    
    team_pick = pick_raw.split('(')[0].replace("Pick:", "").strip()
    
    return {
        "sport": sport_raw,
        "matchup": matchup_raw,
        "team": team_pick
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
    sport_key = SPORTS_KEYS.get(leg["sport"])
    if not sport_key:
        print(f"DEBUG: Unknown sport key for '{leg['sport']}'")
        return None  # Unknown sport

    scores = scores_by_sport.get(sport_key, [])
    picked_team = leg["team"].lower()

    for game in scores:
        home_team = game.get("home_team", "")
        away_team = game.get("away_team", "")
        completed = game.get("completed", False)

        # Debug print all games checked
        print(f"DEBUG: Checking game [{away_team} @ {home_team}] | Completed: {completed} | Looking for pick: {leg['team']}")

        if not completed:
            continue

        if picked_team not in [home_team.lower(), away_team.lower()]:
            continue

        game_scores = game.get("scores", [])
        if not game_scores or len(game_scores) < 2:
            print(f"DEBUG: Game completed but scores array invalid: {game_scores}")
            continue

        home_score = 0
        away_score = 0
        for s in game_scores:
            if s.get("name", "").lower() == home_team.lower():
                home_score = int(s.get("score", 0))
            elif s.get("name", "").lower() == away_team.lower():
                away_score = int(s.get("score", 0))

        print(f"DEBUG: Final Score - {away_team}: {away_score} vs {home_team}: {home_score}")

        if home_score == away_score:
            return "push"

        winning_team = home_team if home_score > away_score else away_team
        is_win = winning_team.lower() == picked_team
        return "win" if is_win else "loss"

    return None  # Game not yet completed or name mismatch

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

    # Cache scores for involved sports
    scores_by_sport = {}
    for sport_key in SPORTS_KEYS.values():
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

        if None in leg_results:
            print(f"Bet #{bet_id}: Games still pending or scores not finalized yet.")
            continue

        if "loss" in leg_results:
            final_status = "loss"
        elif "push" in leg_results:
            final_status = "push"
        elif all(r == "win" for r in leg_results):
            final_status = "win"
        else:
            final_status = "pending"

        if final_status != "pending":
            print(f"Grading Bet #{bet_id} -> Result: {final_status.upper()}")
            update_bet_status(bet_id, final_status)

if __name__ == "__main__":
    main()
