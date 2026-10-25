import os
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

# ESPN Public API Endpoint Mappings (MLB and WNBA excluded)
ESPN_SPORT_ENDPOINTS = {
    "basketball_nba": "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard",
    "icehockey_nhl": "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard",
    "americanfootball_nfl": "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard",
    "americanfootball_ncaaf": "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard"
}

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

def decimal_to_american(dec):
    if dec >= 2.0:
        return round((dec - 1) * 100)
    else:
        return round(-100 / (dec - 1))

def calculate_combined_american_odds(odds1_str, odds2_str):
    def parse_odds(o_str):
        clean = o_str.replace('+', '')
        return int(clean)
    
    o1 = parse_odds(odds1_str)
    o2 = parse_odds(odds2_str)
    
    dec1 = american_to_decimal(o1)
    dec2 = american_to_decimal(o2)
    combined_dec = dec1 * dec2
    
    comb_american = decimal_to_american(combined_dec)
    return f"+{comb_american}" if comb_american > 0 else f"{comb_american}"

def get_supabase_endpoint():
    clean_url = SUPABASE_URL.rstrip('/')
    if clean_url.endswith('/rest/v1'):
        return clean_url
    return f"{clean_url}/rest/v1"

def fetch_public_odds(sport_key):
    base_url = ESPN_SPORT_ENDPOINTS.get(sport_key)
    if not base_url:
        return []
    
    eastern = ZoneInfo('America/New_York')
    today_date_str = datetime.now(eastern).strftime('%Y%m%d')
    url = f"{base_url}?dates={today_date_str}"
    
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            return res.json().get("events", [])
        print(f"Error fetching public feed for {sport_key} ({res.status_code})")
        return []
    except Exception as e:
        print(f"Failed to reach public endpoint for {sport_key}: {e}")
        return []

def filter_games_for_today(events):
    eastern = ZoneInfo('America/New_York')
    today_str = datetime.now(eastern).strftime('%Y-%m-%d')
    today_games = []

    for event in events:
        date_str = event.get("date")
        if not date_str:
            continue
        
        try:
            dt = datetime.fromisoformat(date_str.replace('Z', '+00:00')).astimezone(eastern)
            game_date_str = dt.strftime('%Y-%m-%d')
            if game_date_str == today_str:
                today_games.append(event)
        except Exception:
            continue

    return today_games

def extract_even_money_candidates(events, sport_key):
    candidates = []

    for event in events:
        competitions = event.get("competitions", [])
        if not competitions:
            continue
        
        comp = competitions[0]
        competitors = comp.get("competitors", [])
        if len(competitors) != 2:
            continue

        home_team, away_team = None, None
        home_odds, away_odds = None, None

        for c in competitors:
            team_name = c.get("team", {}).get("displayName")
            is_home = (c.get("homeAway") == "home")
            if is_home:
                home_team = team_name
            else:
                away_team = team_name

        # Deep extraction from competition-level odds providers
        odds_list = comp.get("odds", [])
        for provider_odds in odds_list:
            try:
                h_ml = provider_odds.get("homeTeamOdds", {}).get("moneyLine")
                a_ml = provider_odds.get("awayTeamOdds", {}).get("moneyLine")
                if h_ml is not None and a_ml is not None:
                    home_odds = int(h_ml)
                    away_odds = int(a_ml)
                    break
            except:
                pass

        # Fallback check inside competitor objects if competition-level odds are missing
        if home_odds is None or away_odds is None:
            for c in competitors:
                is_home = (c.get("homeAway") == "home")
                lines = c.get("odds", [])
                if lines:
                    try:
                        val = int(lines[0].get("moneyLine"))
                        if is_home:
                            home_odds = val
                        else:
                            away_odds = val
                    except:
                        pass

        # Drop game immediately if data is incomplete (NO fake defaults)
        if not home_team or not away_team or home_odds is None or away_odds is None:
            continue

        # STRICT EVEN-MONEY CORRIDOR FILTER: Drop anything outside -130 to +130
        if not (-130 <= home_odds <= 130) or not (-130 <= away_odds <= 130):
            continue

        dist_home = abs(home_odds - 100) if home_odds > 0 else abs(abs(home_odds) - 100)
        dist_away = abs(away_odds - 100) if away_odds > 0 else abs(abs(away_odds) - 100)
        matchup_even_distance = (dist_home + dist_away) / 2.0

        candidates.append({
            "sport_key": sport_key,
            "sport_name": SPORT_DISPLAY_NAMES.get(sport_key, sport_key.upper()),
            "matchup": f"{away_team} @ {home_team}",
            "home_team": home_team,
            "away_team": away_team,
            "home_odds": home_odds,
            "away_odds": away_odds,
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
    endpoint = get_supabase_endpoint()

    # Prevent duplicate entries for today's date
    check_url = f"{endpoint}/bets?event_date=eq.{event_date}&select=id"
    get_headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}"
    }
    try:
        existing_res = requests.get(check_url, headers=get_headers)
        if existing_res.status_code == 200:
            records = existing_res.json()
            if records:
                print(f"Parlay for {event_date} already exists in Supabase. Skipping duplicate insertion.")
                return
    except Exception as e:
        print(f"Exception checking existing records: {e}")

    l1_str = f"LEG1: {leg1['sport_name']} | {leg1['matchup']} | Pick: {leg1['selected_team']} ({leg1['selected_odds']})"
    l2_str = f"LEG2: {leg2['sport_name']} | {leg2['matchup']} | Pick: {leg2['selected_team']} ({leg2['selected_odds']})"
    
    if dropped_leg:
        l3_str = f"DROPPED: {dropped_leg['sport_name']} | {dropped_leg['matchup']} | Pick: {dropped_leg['selected_team']} ({dropped_leg['selected_odds']})"
    else:
        l3_str = "DROPPED: No third candidate available"

    full_pick_payload = f"{l1_str} || {l2_str} || {l3_str}"
    combined_sport_label = f"{leg1['sport_name']} / {leg2['sport_name']}"
    combined_matchup_label = f"{leg1['matchup']} / {leg2['matchup']}"
    combined_odds_str = calculate_combined_american_odds(leg1['selected_odds'], leg2['selected_odds'])

    url = f"{endpoint}/bets"
    post_headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal"
    }
    data = {
        "event_date": event_date,
        "sport": combined_sport_label,
        "matchup": combined_matchup_label,
        "odds": combined_odds_str,
        "pick": full_pick_payload,
        "wager_amount": 2.00,
        "status": "pending"
    }

    try:
        res = requests.post(url, json=data, headers=post_headers)
        if res.status_code in [200, 201]:
            print("Successfully saved daily even-money parlay to Supabase.")
        else:
            print(f"Failed saving to Supabase ({res.status_code}): {res.text}")
    except Exception as e:
        print(f"Exception writing to Supabase: {e}")

def main():
    print("Initiating Even-Money Scan...")
    all_candidates = []

    for sport in list(ESPN_SPORT_ENDPOINTS.keys()):
        raw_events = fetch_public_odds(sport)
        today_events = filter_games_for_today(raw_events)
        print(f"Found {len(today_events)} active today game(s) for {sport}")

        candidates = extract_even_money_candidates(today_events, sport)
        all_candidates.extend(candidates)

    if not all_candidates:
        print("No active matchups found within the strict even-money corridor (-130 to +130).")
        return

    all_candidates.sort(key=lambda x: x["even_distance"])
    print(f"Extracted {len(all_candidates)} strict even-money matchup(s). Running head-to-head metric engine...")

    evaluated_candidates = [run_head_to_head_metrics(c) for c in all_candidates]
    evaluated_candidates.sort(key=lambda x: x["metric_score"], reverse=True)

    leg1 = evaluated_candidates[0]
    leg2 = None
    dropped_leg = None

    # Pass 1: Cross-sport pairing
    for candidate in evaluated_candidates[1:]:
        if candidate["sport_key"] != leg1["sport_key"] and leg2 is None:
            leg2 = candidate
        elif dropped_leg is None and candidate["matchup"] != leg1["matchup"]:
            dropped_leg = candidate

        if leg2 is not None and dropped_leg is not None:
            break

    # Pass 2: Same-sport distinct matchup fallback
    if not leg2:
        for candidate in evaluated_candidates[1:]:
            if candidate["matchup"] != leg1["matchup"] and leg2 is None:
                leg2 = candidate
            elif dropped_leg is None and candidate["matchup"] != leg1["matchup"] and candidate != leg2:
                dropped_leg = candidate

            if leg2 is not None:
                break

    if not leg2:
        print("Could not find two unique matchups among even-money candidates.")
        return

    print("\n--- TODAY'S LOCKED PARLAY ---")
    print(f"Leg 1: {leg1['sport_name']} - {leg1['matchup']} -> Pick: {leg1['selected_team']} ({leg1['selected_odds']}) [Metric Score: {leg1['metric_score']}]")
    print(f"Leg 2: {leg2['sport_name']} - {leg2['matchup']} -> Pick: {leg2['selected_team']} ({leg2['selected_odds']}) [Metric Score: {leg2['metric_score']}]")
    if dropped_leg:
        print(f"Distilled Leg 3: {dropped_leg['sport_name']} - {dropped_leg['matchup']} -> Pick: {dropped_leg['selected_team']} ({dropped_leg['selected_odds']})")

    save_parlay_to_supabase(leg1, leg2, dropped_leg)

if __name__ == "__main__":
    main()
