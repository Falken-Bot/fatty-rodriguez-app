import os
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "")

# Target sports to scan
ACTIVE_SPORTS = [
    "basketball_nba",
    "icehockey_nhl",
    "americanfootball_nfl",
    "americanfootball_ncaaf"
]

SPORT_DISPLAY_NAMES = {
    "basketball_nba": "NBA",
    "icehockey_nhl": "NHL",
    "americanfootball_nfl": "NFL",
    "americanfootball_ncaaf": "NCAAF"
}

def american_to_decimal(odds):
    if odds > 0:
        return (odds / 100) + 1
    else:
        return (100 / abs(odds)) + 1

def get_supabase_endpoint():
    clean_url = SUPABASE_URL.rstrip('/')
    if clean_url.endswith('/rest/v1'):
        return clean_url
    return f"{clean_url}/rest/v1"

def fetch_live_odds(sport_key):
    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "us",
        "markets": "h2h",
        "oddsFormat": "american"
    }
    try:
        res = requests.get(url, params=params)
        if res.status_code == 200:
            return res.json()
        print(f"Error fetching odds for {sport_key} ({res.status_code}): {res.text}")
        return []
    except Exception as e:
        print(f"Failed to reach Odds API for {sport_key}: {e}")
        return []

def filter_games_for_today(games):
    eastern = ZoneInfo('America/New_York')
    today_str = datetime.now(eastern).strftime('%Y-%m-%d')
    today_games = []

    for game in games:
        commence_str = game.get("commence_time")
        if not commence_str:
            continue
        
        # Convert ISO start time to Eastern Time
        dt = datetime.fromisoformat(commence_str.replace('Z', '+00:00')).astimezone(eastern)
        game_date_str = dt.strftime('%Y-%m-%d')

        if game_date_str == today_str:
            today_games.append(game)

    return today_games

def extract_even_money_candidates(games, sport_key):
    candidates = []

    for game in games:
        home_team = game.get("home_team")
        away_team = game.get("away_team")
        bookmakers = game.get("bookmakers", [])

        if not bookmakers:
            continue

        home_odds_list = []
        away_odds_list = []

        for bm in bookmakers:
            for m in bm.get("markets", []):
                if m.get("key") == "h2h":
                    for outcome in m.get("outcomes", []):
                        name = outcome.get("name")
                        price = outcome.get("price")
                        if name == home_team:
                            home_odds_list.append(price)
                        elif name == away_team:
                            away_odds_list.append(price)

        if not home_odds_list or not away_odds_list:
            continue

        avg_home_odds = sum(home_odds_list) / len(home_odds_list)
        avg_away_odds = sum(away_odds_list) / len(away_odds_list)

        dist_home = abs(avg_home_odds - 100) if avg_home_odds > 0 else abs(abs(avg_home_odds) - 100)
        dist_away = abs(avg_away_odds - 100) if avg_away_odds > 0 else abs(abs(avg_away_odds) - 100)

        matchup_even_distance = (dist_home + dist_away) / 2.0

        candidates.append({
            "sport_key": sport_key,
            "sport_name": SPORT_DISPLAY_NAMES.get(sport_key, sport_key.upper()),
            "matchup": f"{away_team} @ {home_team}",
            "home_team": home_team,
            "away_team": away_team,
            "home_odds": round(avg_home_odds),
            "away_odds": round(avg_away_odds),
            "even_distance": matchup_even_distance
        })

    return candidates

def run_head_to_head_metrics(candidate):
    home_team = candidate["home_team"]
    away_team = candidate["away_team"]
    h_odds = candidate["home_odds"]
    a_odds = candidate["away_odds"]

    home_score = 50.0
    away_score = 50.0

    # Metric 1: Home Advantage Baseline
    home_score += 3.5

    # Metric 2: Price Line Leverage & Value Corridor
    if -115 <= h_odds <= 105:
        home_score += 4.0
    if -115 <= a_odds <= 105:
        away_score += 4.0

    # Metric 3: Implied Probability Margin
    h_dec = american_to_decimal(h_odds)
    a_dec = american_to_decimal(a_odds)
    h_prob = (1 / h_dec) * 100
    a_prob = (1 / a_dec) * 100

    if h_prob > a_prob:
        home_score += (h_prob - a_prob)
    else:
        away_score += (a_prob - h_prob)

    if home_score >= away_score:
        selected_team = home_team
        selected_odds = f"+{h_odds}" if h_odds > 0 else str(h_odds)
        winning_score = home_score
    else:
        selected_team = away_team
        selected_odds = f"+{a_odds}" if a_odds > 0 else str(a_odds)
        winning_score = away_score

    candidate["selected_team"] = selected_team
    candidate["selected_odds"] = selected_odds
    candidate["metric_score"] = round(winning_score, 2)

    return candidate

def save_parlay_to_supabase(leg1, leg2, dropped_leg):
    eastern = ZoneInfo('America/New_York')
    event_date = datetime.now(eastern).strftime('%Y-%m-%d')

    l1_str = f"LEG1: {leg1['sport_name']} | {leg1['matchup']} | Pick: {leg1['selected_team']} ({leg1['selected_odds']})"
    l2_str = f"LEG2: {leg2['sport_name']} | {leg2['matchup']} | Pick: {leg2['selected_team']} ({leg2['selected_odds']})"
    
    if dropped_leg:
        l3_str = f"DROPPED: {dropped_leg['sport_name']} | {dropped_leg['matchup']} | Pick: {dropped_leg['selected_team']} ({dropped_leg['selected_odds']})"
    else:
        l3_str = "DROPPED: No third cross-sport candidate available"

    full_pick_payload = f"{l1_str} || {l2_str} || {l3_str}"
    combined_sport_label = f"{leg1['sport_name']} / {leg2['sport_name']}"

    endpoint = get_supabase_endpoint()
    url = f"{endpoint}/bets"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal"
    }
    data = {
        "event_date": event_date,
        "sport": combined_sport_label,
        "pick": full_pick_payload,
        "wager_amount": 2.00,
        "status": "pending"
    }

    try:
        res = requests.post(url, json=data, headers=headers)
        if res.status_code in [200, 201]:
            print("Successfully saved daily even-money parlay to Supabase.")
        else:
            print(f"Failed saving to Supabase ({res.status_code}): {res.text}")
    except Exception as e:
        print(f"Exception writing to Supabase: {e}")

def main():
    print("Initiating Even-Money Market Scan...")
    all_candidates = []

    for sport in ACTIVE_SPORTS:
        raw_games = fetch_live_odds(sport)
        today_games = filter_games_for_today(raw_games)
        print(f"Found {len(today_games)} active today game(s) for {sport}")

        candidates = extract_even_money_candidates(today_games, sport)
        all_candidates.extend(candidates)

    if not all_candidates:
        print("No active even-money matchups found for today.")
        return

    all_candidates.sort(key=lambda x: x["even_distance"])
    print(f"Extracted {len(all_candidates)} near even-money matchup(s). Running head-to-head metric engine...")

    evaluated_candidates = [run_head_to_head_metrics(c) for c in all_candidates]
    evaluated_candidates.sort(key=lambda x: x["metric_score"], reverse=True)

    leg1 = evaluated_candidates[0]
    leg2 = None
    dropped_leg = None

    for candidate in evaluated_candidates[1:]:
        if candidate["sport_key"] != leg1["sport_key"] and leg2 is None:
            leg2 = candidate
        elif dropped_leg is None:
            dropped_leg = candidate

        if leg2 is not None and dropped_leg is not None:
            break

    if not leg2:
        print("Could not find two unique cross-sport legs among candidates.")
        return

    print("\n--- TODAY'S EVEN-MONEY LOCKED PARLAY ---")
    print(f"Leg 1: {leg1['sport_name']} - {leg1['matchup']} -> Pick: {leg1['selected_team']} ({leg1['selected_odds']}) [Metric Score: {leg1['metric_score']}]")
    print(f"Leg 2: {leg2['sport_name']} - {leg2['matchup']} -> Pick: {leg2['selected_team']} ({leg2['selected_odds']}) [Metric Score: {leg2['metric_score']}]")
    if dropped_leg:
        print(f"Distilled Leg 3: {dropped_leg['sport_name']} - {dropped_leg['matchup']} -> Pick: {dropped_leg['selected_team']} ({dropped_leg['selected_odds']})")

    save_parlay_to_supabase(leg1, leg2, dropped_leg)

if __name__ == "__main__":
    main()
