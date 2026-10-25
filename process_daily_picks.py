import os
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

# ESPN Public API Endpoint Mappings for Scores & Settlement
ESPN_SPORT_ENDPOINTS = {
    "NBA": "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard",
    "NHL": "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard",
    "NFL": "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard",
    "NCAAF": "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard"
}

def get_supabase_endpoint():
    clean_url = SUPABASE_URL.rstrip('/')
    if clean_url.endswith('/rest/v1'):
        return clean_url
    return f"{clean_url}/rest/v1"

def fetch_pending_bets():
    endpoint = get_supabase_endpoint()
    url = f"{endpoint}/bets?status=eq.pending"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}"
    }
    try:
        res = requests.get(url, headers=headers)
        if res.status_code == 200:
            return res.json()
        print(f"Error fetching pending bets from Supabase ({res.status_code}): {res.text}")
        return []
    except Exception as e:
        print(f"Exception fetching pending bets: {e}")
        return []

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
            print(f"Successfully updated Bet #{bet_id} status to: {new_status}")
        else:
            print(f"Failed updating Bet #{bet_id} ({res.status_code}): {res.text}")
    except Exception as e:
        print(f"Exception updating Bet #{bet_id}: {e}")

def fetch_completed_events_for_date(sport_name, event_date_str):
    base_url = ESPN_SPORT_ENDPOINTS.get(sport_name)
    if not base_url:
        return []
    
    date_param = event_date_str.replace("-", "")
    url = f"{base_url}?dates={date_param}"
    
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            return res.json().get("events", [])
    except Exception as e:
        print(f"Failed fetching scores for {sport_name} on {event_date_str}: {e}")
    return []

def evaluate_leg(leg_text, event_date_str):
    """
    Parses a leg string (e.g., 'LEG1: NCAAF | Pittsburgh Panthers @ Miami Hurricanes | Pick: Miami Hurricanes (-1983)')
    and checks ESPN public scoreboards to see if the pick won, lost, or is still pending.
    Returns: True (Won), False (Lost), or None (Pending/Incomplete)
    """
    parts = [p.strip() for p in leg_text.split('|')]
    if len(parts) < 3:
        return None
    
    # Extract sport name
    header_part = parts[0].replace("LEG1:", "").replace("LEG2:", "").strip()
    sport_key = header_part.split()[0] if header_part else ""
    
    # Extract matchup teams (Away @ Home)
    matchup_str = parts[1].strip()
    if "@" not in matchup_str:
        return None
    away_team_name, home_team_name = [t.strip() for t in matchup_str.split('@')]
    
    # Extract picked team
    pick_part = parts[2]
    if "Pick:" not in pick_part:
        return None
    picked_team = pick_part.split("Pick:")[1].split('(')[0].strip()

    events = fetch_completed_events_for_date(sport_key, event_date_str)
    if not events:
        return None

    for event in events:
        status_type = event.get("status", {}).get("type", {})
        is_completed = status_type.get("completed", False) or status_type.get("state") == "post"
        
        if not is_completed:
            return None # Game hasn't finished yet

        competitions = event.get("competitions", [])
        if not competitions:
            continue
        
        comp = competitions[0]
        competitors = comp.get("competitors", [])
        if len(competitors) != 2:
            continue

        match_found = False
        winner_team = None
        
        home_score, away_score = 0, 0
        h_name, a_name = "", ""

        for c in competitors:
            t_name = c.get("team", {}).get("displayName")
            score = int(c.get("score", 0))
            is_home = (c.get("homeAway") == "home")

            if is_home:
                h_name = t_name
                home_score = score
            else:
                a_name = t_name
                away_score = score

        # Check if this event matches our leg teams
        if (picked_team.lower() in h_name.lower() or picked_team.lower() in a_name.lower()) and \
           (home_team_name.lower() in h_name.lower() or away_team_name.lower() in a_name.lower()):
            
            if home_score > away_score:
                winner_team = h_name
            elif away_score > home_score:
                winner_team = a_name
            else:
                return False # Tie counts as loss/push for standard moneyline parlays
            
            return picked_team.lower() in winner_team.lower()

    return None # Game not found or incomplete

def main():
    eastern = ZoneInfo('America/New_York')
    today_str = datetime.now(eastern).strftime('%Y-%m-%d')
    print(f"Initiating automated free bet grading sweep... Today's ET Date: {today_str}")

    pending_bets = fetch_pending_bets()
    print(f"Found {len(pending_bets)} pending bet record(s) in Supabase.")

    for bet in pending_bets:
        bet_id = bet.get("id")
        event_date = bet.get("event_date")
        pick_payload = bet.get("pick", "")

        if event_date > today_str:
            print(f"Bet #{bet_id}: Event date is in the future ({event_date}). Skipping.")
            continue

        legs = [l.strip() for l in pick_payload.split('||')]
        active_legs = [l for l in legs if l.startswith("LEG1") or l.startswith("LEG2")]

        leg_results = []
        for leg in active_legs:
            res = evaluate_leg(leg, event_date)
            leg_results.append(res)

        print(f"DEBUG: Bet #{bet_id} ({event_date}) leg results evaluation: {leg_results}")

        if all(r is True for r in leg_results):
            update_bet_status(bet_id, "won")
        elif any(r is False for r in leg_results):
            update_bet_status(bet_id, "lost")
        else:
            print(f"Bet #{bet_id}: Remains pending (waiting on incomplete games).")

if __name__ == "__main__":
    main()
