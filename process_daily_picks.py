import os
import sys
import requests
from datetime import datetime
import zoneinfo

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://ejnwsxbpuumcpyxnmsaz.supabase.co").strip().rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "sb_publishable_M4seLrgZoXLBY9m01uMa1Q_ZFHBW1Dp").strip()
ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "").strip()

if "/rest/v1" in SUPABASE_URL:
    SUPABASE_URL = SUPABASE_URL.split("/rest/v1")[0]

SPORTS_LIST = [
    "americanfootball_nfl",
    "americanfootball_ncaaf",
    "basketball_nba",
    "basketball_ncaab",
    "icehockey_nhl",
    "baseball_mlb"
]

def get_today_str_et():
    et_tz = zoneinfo.ZoneInfo("America/New_York")
    return datetime.now(et_tz).strftime("%Y-%m-%d")

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
    et_tz = zoneinfo.ZoneInfo("America/New_York")

    for game in data:
        commence_raw = game.get('commence_time', '')
        if not commence_raw:
            continue

        try:
            utc_dt = datetime.fromisoformat(commence_raw.replace('Z', '+00:00'))
            et_dt = utc_dt.astimezone(et_tz)
            game_date_et = et_dt.strftime("%Y-%m-%d")
        except Exception:
            game_date_et = commence_raw.split('T')[0]

        if game_date_et != today_str:
            continue

        for bookmaker in game.get('bookmakers', []):
            for market in bookmaker.get('markets', []):
                for outcome in market.get('outcomes', []):
                    price = outcome.get('price')
                    if price is not None and (target_min <= price <= target_max):
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

def build_distilled_cross_sport_parlay(candidates):
    if not candidates:
        print("No qualified candidates found today.")
        return None

    # Group candidates by sport, ensuring unique matchups per sport
    by_sport = {}
    for c in candidates:
        sport = c['sport']
        if sport not in by_sport:
            by_sport[sport] = []
        if not any(existing['matchup'] == c['matchup'] for existing in by_sport[sport]):
            by_sport[sport].append(c)

    # Filter out sports with zero qualified picks
    by_sport = {s: items for s, items in by_sport.items() if items}
    available_sports = list(by_sport.keys())
    print(f"Active sports with valid odds today (-130 to +130): {available_sports}")

    # STRICT RULE: Must have at least 2 distinct sports to build a cross-sport parlay
    if len(available_sports) < 2:
        print(f"CRITICAL ERROR: Cross-sport diversity violation. Found qualifying odds in only {len(available_sports)} sport(s): {available_sports}. Aborting parlay generation.")
        return None

    # Select Leg 1 from Sport 1, Leg 2 from Sport 2
    sport1, sport2 = available_sports[0], available_sports[1]
    leg1 = by_sport[sport1][0]
    leg2 = by_sport[sport2][0]

    # Double check that Leg 1 and Leg 2 are strictly different sports
    if leg1['sport'] == leg2['sport']:
        print("CRITICAL ERROR: Leg 1 and Leg 2 belong to the same sport. Aborting.")
        return None

    # Select Leg 3 (Distilled Out) from a 3rd sport if available, otherwise from remaining distinct matchups
    leg3 = None
    if len(available_sports) >= 3 and len(by_sport[available_sports[2]]) > 0:
        leg3 = by_sport[available_sports[2]][0]
    else:
        for s in available_sports:
            for item in by_sport[s]:
                if item['matchup'] != leg1['matchup'] and item['matchup'] != leg2['matchup']:
                    leg3 = item
                    break
            if leg3:
                break

    if not leg3 or leg3['matchup'] == leg1['matchup'] or leg3['matchup'] == leg2['matchup']:
        print("Could not find a distinct 3rd candidate leg with a unique matchup.")
        return None

    return {
        "leg1": leg1,
        "leg2": leg2,
        "leg3": leg3
    }

def save_parlay_direct_http(record):
    target_endpoint = f"{SUPABASE_URL}/rest/v1/bets"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }
    
    res = requests.post(target_endpoint, json=[record], headers=headers, timeout=10)
    if res.status_code in [200, 201]:
        print("SUCCESS: Saved validated 2-leg cross-sport parlay package directly to Supabase!")
    else:
        print(f"Supabase HTTP Error ({res.status_code}): {res.text}")
        sys.exit(1)

if __name__ == "__main__":
    today_str = get_today_str_et()
    print(f"Running Fatty Rodriguez Cross-Sport Engine for Date: {today_str}")
    
    all_candidates = []
    for sport in SPORTS_LIST:
        raw = fetch_odds(sport)
        all_candidates.extend(filter_fatty_picks(raw, today_str))

    parlay_pkg = build_distilled_cross_sport_parlay(all_candidates)
    
    if parlay_pkg:
        l1 = parlay_pkg['leg1']
        l2 = parlay_pkg['leg2']
        l3 = parlay_pkg['leg3']

        fmt_l1 = f"{l1['sport']} | {l1['matchup']} | Pick: {l1['pick']} ({'+' if l1['odds']>0 else ''}{l1['odds']})"
        fmt_l2 = f"{l2['sport']} | {l2['matchup']} | Pick: {l2['pick']} ({'+' if l2['odds']>0 else ''}{l2['odds']})"
        fmt_l3 = f"{l3['sport']} | {l3['matchup']} | Pick: {l3['pick']} ({'+' if l3['odds']>0 else ''}{l3['odds']})"

        record = {
            "event_date": today_str,
            "sport": "CROSS-SPORT PARLAY",
            "matchup": f"{l1['sport']} & {l2['sport']}",
            "pick": f"LEG1: {fmt_l1} || LEG2: {fmt_l2} || DROPPED: {fmt_l3}",
            "odds": l1['odds'],
            "wager_amount": 2.00,
            "status": "pending"
        }
        save_parlay_direct_http(record)
    else:
        print("Could not build a qualifying cross-sport parlay today.")
        sys.exit(1)
