import os
import json
import requests
import pandas as pd
import base64
from io import StringIO
import sys
import time
import unicodedata

# Configuration Setup
GITHUB_REPOSITORY = os.environ.get("GITHUB_REPOSITORY", "owner/repo")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
CONFIG_PATH = "seats_config.json"
RESULTS_PATH = "race_results.csv"

HEADERS = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json"
}

def normalize_string(s):
    return unicodedata.normalize('NFKD', s).encode('ASCII', 'ignore').decode('utf-8').lower()

def get_team_key(api_team_name):
    t = api_team_name.lower().replace(" ", "")
    if "redbull" in t: return "red_bull"
    if "mercedes" in t: return "mercedes"
    if "mclaren" in t: return "mclaren"
    if "ferrari" in t: return "ferrari"
    if "williams" in t: return "williams"
    if "alpine" in t: return "alpine"
    if "haas" in t: return "haas"
    if "aston" in t: return "aston_martin"
    if "audi" in t or "sauber" in t or "alfaromeo" in t: return "audi"
    if "rb" == t or "alphatauri" in t or "racingbulls" in t: return "racing_bulls"
    if "cadillac" in t or "andretti" in t: return "cadillac"
    return t

def fetch_file_from_github(path, is_json=True):
    url = f"https://api.github.com/repos/{GITHUB_REPOSITORY}/contents/{path}"
    res = requests.get(url, headers=HEADERS)
    if res.status_code == 200:
        content = base64.b64decode(res.json()["content"]).decode("utf-8")
        if is_json:
            return json.loads(content), res.json()["sha"]
        else:
            return pd.read_csv(StringIO(content)), res.json()["sha"]
    return (None, None) if is_json else (pd.DataFrame(), None)

def push_file_to_github(path, content_str, sha, message):
    url = f"https://api.github.com/repos/{GITHUB_REPOSITORY}/contents/{path}"
    payload = {
        "message": message,
        "content": base64.b64encode(content_str.encode("utf-8")).decode("utf-8")
    }
    if sha:
        payload["sha"] = sha
    requests.put(url, json=payload, headers=HEADERS)

def ingest_latest_race():
    print("Starting Jolpica API ingestion sequence with Seat-Inheritance...")
    config, config_sha = fetch_file_from_github(CONFIG_PATH, is_json=True)
    if not config:
        sys.exit(1)
    
    existing_df, csv_sha = fetch_file_from_github(RESULTS_PATH, is_json=False)
    all_new_results = []
    updates_made = False

    for round_num in range(1, 25):
        time.sleep(1) 
        api_url = f"https://api.jolpi.ca/ergast/f1/current/{round_num}/results.json"
        response = requests.get(api_url)
        if response.status_code != 200:
            break
            
        race_data = response.json().get("MRData", {}).get("RaceTable", {}).get("Races", [])
        if not race_data:
            break 
            
        race = race_data[0]
        round_id = int(race["round"])
        race_id = race["raceName"].lower().replace(" ", "_")
        
        historical_rounds = [h.get("round") for h in config.get("history", [])]
        if round_id in historical_rounds:
            continue
            
        print(f"Catching up Round {round_id}: {race_id}")
        updates_made = True
        
        team_drivers = {}
        for r in race.get("Results", []):
            driver_name = f"{r['Driver']['givenName']} {r['Driver']['familyName']}"
            last_name = r['Driver']['familyName']
            team_name = r["Constructor"]["name"]
            team_key = get_team_key(team_name)
            
            # --- STRICT DNF ENFORCEMENT ---
            status = str(r.get("status", "")).strip().lower()
            if "lap" in status or status == "finished":
                pos_val = r.get("position")
                position = int(float(pos_val)) if pos_val else "DNF"
            else:
                position = "DNF"
                
            team_drivers.setdefault(team_key, []).append({
                "driver_name": driver_name,
                "last_name": last_name,
                "position": position,
                "team_name": team_name
            })

        for team_key, drivers_list in team_drivers.items():
            team_seats = sorted([k for k in config["seats"].keys() if k.startswith(team_key + "_")])
            unmatched_drivers = []
            
            for d_info in drivers_list:
                placed = False
                for s in team_seats:
                    current_d = config["seats"][s]["current_driver"]
                    if normalize_string(d_info["last_name"]) in normalize_string(current_d) or normalize_string(current_d.split()[-1]) in normalize_string(d_info["last_name"]):
                        config["seats"][s]["current_driver"] = d_info["driver_name"] 
                        placed = True
                        all_new_results.append({
                            "race_id": race_id, "round": round_id, 
                            "driver": d_info["driver_name"], "team": d_info["team_name"], 
                            "position": d_info["position"]
                        })
                        break
                if not placed:
                    unmatched_drivers.append(d_info)
                    
            for s in team_seats:
                current_d = config["seats"][s]["current_driver"]
                is_in_race = any(normalize_string(current_d.split()[-1]) in normalize_string(dr["last_name"]) for dr in drivers_list)
                
                if not is_in_race and unmatched_drivers:
                    new_d_info = unmatched_drivers.pop(0)
                    print(f"  -> Mid-Season Swap: {new_d_info['driver_name']} takes over {s} from {current_d}")
                    config["seats"][s]["current_driver"] = new_d_info["driver_name"]
                    
                    all_new_results.append({
                        "race_id": race_id, "round": round_id, 
                        "driver": new_d_info["driver_name"], "team": new_d_info["team_name"], 
                        "position": new_d_info["position"]
                    })

        for seat_key, seat_data in config["seats"].items():
            config["history"].append({
                "round": round_id,
                "seat_id": seat_key,
                "driver": seat_data["current_driver"]
            })
            
    if updates_made:
        new_results_df = pd.DataFrame(all_new_results)
        final_df = pd.concat([existing_df, new_results_df], ignore_index=True) if not existing_df.empty else new_results_df
        push_file_to_github(CONFIG_PATH, json.dumps(config, indent=2), config_sha, "Ingested configurations")
        push_file_to_github(RESULTS_PATH, final_df.to_csv(index=False), csv_sha, "Appended race results")
        print("Catch-up complete!")

if __name__ == "__main__":
    ingest_latest_race()
