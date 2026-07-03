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
    if "audi" in t or "sauber" in t: return "audi"
    if "racingbulls" in t or "rb" == t: return "racing_bulls"
    if "cadillac" in t or "andretti" in t: return "cadillac"
    return t

def fetch_file_from_github(path, is_json=True):
    url = f"https://api.github.com/repos/{GITHUB_REPOSITORY}/contents/{path}"
    res = requests.get(url, headers=HEADERS)
    if res.status_code == 200:
        content = base64.b64decode(res.json()["content"]).decode("utf-8")
        if is_json:
            try:
                return json.loads(content), res.json()["sha"]
            except:
                sys.exit(1)
        else:
            try:
                if not content.strip():
                    return pd.DataFrame(), res.json()["sha"]
                return pd.read_csv(StringIO(content)), res.json()["sha"]
            except:
                sys.exit(1)
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
    print("Starting OpenF1 2026 API ingestion sequence...")
    
    config, config_sha = fetch_file_from_github(CONFIG_PATH, is_json=True)
    if not config:
        sys.exit(1)
        
    existing_df, csv_sha = fetch_file_from_github(RESULTS_PATH, is_json=False)
    all_new_results = []
    updates_made = False

    sessions_url = "https://api.openf1.org/v1/sessions?year=2026&session_type=Race"
    session_res = requests.get(sessions_url)
    if session_res.status_code != 200:
        sys.exit(1)
        
    sessions = session_res.json()
    sessions = sorted(sessions, key=lambda x: x.get("date_start", ""))
    historical_rounds = [h.get("round") for h in config.get("history", [])]

    for idx, session in enumerate(sessions):
        round_id = idx + 1
        session_key = session["session_key"]
        race_id = session.get("session_name", f"round_{round_id}").lower().replace(" ", "_")
        
        if round_id in historical_rounds:
            continue
            
        print(f"Ingesting Round {round_id}: {race_id} from OpenF1...")
        updates_made = True
        
        time.sleep(2.5)
        drivers_res = requests.get(f"https://api.openf1.org/v1/drivers?session_key={session_key}")
        drivers_list = drivers_res.json() if drivers_res.status_code == 200 else []
        drivers_map = {d["driver_number"]: d for d in drivers_list}
        
        time.sleep(2.5)
        results_res = requests.get(f"https://api.openf1.org/v1/session_result?session_key={session_key}")
        results_list = results_res.json() if results_res.status_code == 200 else []
        
        if not results_list:
            continue
            
        team_drivers = {}
        
        for r in results_list:
            # --- THE DEBUGGER IS HERE ---
            if r.get("driver_number") == 1:
                print(f"\n---> RAW OPENF1 DATA FOR VERSTAPPEN: {r} <---\n")

            driver_num = r.get("driver_number")
            driver_info = drivers_map.get(driver_num, {})
            driver_name = driver_info.get("full_name", f"Unknown Driver {driver_num}")
            last_name = driver_info.get("last_name", str(driver_num))
            team_name = driver_info.get("team_name", "Unknown Team")
            team_key = get_team_key(team_name)
            
            # Temporary safety logic so the script doesn't crash while we debug
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
            
        for team_key, drivers_list_team in team_drivers.items():
            team_seats = sorted([k for k in config["seats"].keys() if k.startswith(team_key + "_")])
            unmatched_drivers = []
            
            for d_info in drivers_list_team:
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
                is_in_race = any(normalize_string(current_d.split()[-1]) in normalize_string(dr["last_name"]) for dr in drivers_list_team)
                
                if not is_in_race and unmatched_drivers:
                    new_d_info = unmatched_drivers.pop(0)
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
        
        push_file_to_github(CONFIG_PATH, json.dumps(config, indent=2), config_sha, "Ingested OpenF1 configurations")
        push_file_to_github(RESULTS_PATH, final_df.to_csv(index=False), csv_sha, "Appended OpenF1 race results")
        print("Catch-up complete!")

if __name__ == "__main__":
    ingest_latest_race()
