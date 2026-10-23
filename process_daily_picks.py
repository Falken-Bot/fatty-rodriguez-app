import os
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

# Environment variables configured in GitHub Actions
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
ODDS_API_KEY = os.environ.get("ODDS_API_KEY")

SPORTS = [
    "icehockey_nhl",
    "basketball_nba",
    "americanfootball_nfl"
]

def fetch_odds_for_sport(sport):
    url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/"
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
        print(f"Odds API error ({res.status_code}) for {sport}: {res.text}")
        return []
    except Exception as e:
        print(f"Failed to fetch odds for {sport}: {e}")
        return []

def handicap_candidate(event, outcome):
    # Qualitative scoring logic (form, situational dynamics, market value)
    base_score = 50.0
    price = outcome.get("price", 0)
    
    # Odds corridor bonus/penalty
    if 100 <= price <= 130:
        base_score += 15.0
    elif -115 <= price < 100:
        base_score += 10.0
    elif -130 <= price < -115:
        base_score += 5.0

    return base_score

def scan_markets():
    eastern = ZoneInfo('America/New_York')
    today_str = datetime.now(eastern).strftime('%Y-%m-%d')
    candidates = []

    for sport in SPORTS:
        events = fetch_odds_for_sport(sport)
        for event in events:
            commence_time_str = event.get("commence_time", "")
            if not commence_time_str:
                continue
            
            # Convert ISO timestamp to Eastern time and verify it takes place TODAY
            event_dt = datetime.fromisoformat(commence_time_str.replace('Z', '+00:00')).astimezone(eastern)
            event_date = event_dt.strftime('%Y-%m-%d')

            if event_date != today_str:
                continue  # Skip games scheduled for future dates

            home_team = event.get("home_team", "")
            away_team = event.get("away_team", "")
            matchup_str = f"{away_team} vs {home_team}"

            for bookmaker in event.get("bookmakers", []):
                for market in bookmaker.get("markets", []):
                    if market.get("key") == "h2h":
                        for outcome in market.get("outcomes", []):
                            price = outcome.get("price")
                            team = outcome.get("name")
                            if price and -130 <= price <= +130:
                                score = handicap_candidate(event, outcome)
                                if score is not None:
                                    candidates.append({
                                        "sport": sport.replace("_", " ").upper(),
                                        "matchup": matchup_str,
                                        "pick": f"{team} ({price:+d})",
                                        "score": score,
                                        "odds": price
                                    })
    return candidates

def build_parlay_payload(candidates):
    if not candidates:
        return "NO QUALIFYING PICKS FOR TODAY"

    # Sort candidates by composite score descending
    sorted_candidates = sorted(candidates, key=lambda x: x["score"], reverse=True)
    
    top_leg = sorted_candidates[0]
    payload = f"LEG1: {top_leg['sport']} | {top_leg['matchup']} | Pick: {top_leg['pick']}"
    
    if len(sorted_candidates) > 1:
        leg2 = sorted_candidates[1]
        payload += f" || LEG2: {leg2['sport']} | {leg2['matchup']} | Pick: {leg2['pick']}"
        
    if len(sorted_candidates) > 2:
        dropped = sorted_candidates[2]
        payload += f" || DROPPED: {dropped['sport']} | {dropped['matchup']} | Pick: {dropped['pick']}"

    return payload

def push_to_supabase(pick_payload):
    eastern = ZoneInfo('America/New_York')
    today_str = datetime.now(eastern).strftime('%Y-%m-%d')

    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal"
    }

    base_url = SUPABASE_URL.rstrip('/')
    
    # 1. Clear any existing entry for today to avoid duplicate records
    delete_url = f"{base_url}/rest/v1/bets?event_date=eq.{today_str}"
    try:
        requests.delete(delete_url, headers=headers)
    except Exception as e:
        print(f"Warning: Could not clear previous entry for today: {e}")

    # 2. Insert fresh daily entry
    data = {
        "event_date": today_str,
        "sport": "CROSS-SPORT",
        "matchup": "Executive Daily Matrix",
        "pick": pick_payload,
        "odds": 0.0,
        "wager_amount": 2.00,
        "status": "pending"
    }

    insert_url = f"{base_url}/rest/v1/bets"
    res = requests.post(insert_url, json=data, headers=headers)
    if res.status_code in [200, 201]:
        print("Successfully logged handicapping matrix to Supabase.")
    else:
        print(f"Supabase logging failed ({res.status_code}): {res.text}")

def main():
    print("Initiating sports-centric market scan...")
    candidates = scan_markets()
    print(f"Found {len(candidates)} candidates passing odds corridor (-130 to +130).")
    
    final_payload = build_parlay_payload(candidates)
    print("Locked Parlay Payload:")
    print(final_payload)
    
    push_to_supabase(final_payload)

if __name__ == "__main__":
    main()
