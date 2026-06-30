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

# Mapping API Constructor names to your Seat keys
TEAM_TRANSLATION = {
    "Sauber": "audi",
    "RB": "racingbulls",
    "Aston Martin": "astonmartin",
    "Red Bull Racing": "redbull",
    "Kick Sauber": "audi"
}

HEADERS = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json"
}

def normalize_string(s):
    return unicodedata.normalize('NFKD', s).encode('ASCII', 'ignore').decode('utf-8').lower()

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
    print("Starting automated ingestion sequence with delay...")
    config, config_sha = fetch_file_from_github(CONFIG_PATH, is_json=True)
    existing_df, csv_sha = fetch_file_from_github(RESULTS_PATH, is_json=False)

    all_new_results = []
    updates_made = False

    for round_num in range(1, 25):
        # 1-second delay to prevent 429 rate-limiting
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
        
        historical_rounds = [h.get("round") for h in config.get("history", [])]
        if round_id in historical_rounds:
            continue
            
        print(f"Ingesting Round {round_id}...")
        updates_made = True
        
        for r in race.get("Results", []):
            driver_name = f"{r['Driver']['givenName']} {r['Driver']['familyName']}"
            last_name = r['Driver']['familyName']
            team_name = r["Constructor"]["name"]
            
            # Apply Team Translation Map
            team_key = TEAM_TRANSLATION.get(team_name, team_name.lower().replace(" ", ""))
            
            position = r["position"] if r.get("status", "") in ["Finished"] or "+" in r.get("status", "") else "DNF"
            
            all_new_results.append({
                "race_id": race["raceName"].lower().replace(" ", "_"),
                "round": round_id,
                "driver": driver_name,
                "team": team_name,
                "position": position
            })
            
            # Match drivers to seats
            for seat_key, seat_data in config["seats"].items():
                if team_key in seat_key:
                    if seat_data["current_driver"] == driver_name or normalize_string(last_name) in normalize_string(seat_data["current_driver"]):
                        config["seats"][seat_key]["current_driver"] = driver_name
                        break
                            
        for seat_key, seat_data in config["seats"].items():
            config["history"].append({"round": round_id, "seat_id": seat_key, "driver": seat_data["current_driver"]})
            
    if updates_made:
        new_results_df = pd.DataFrame(all_new_results)
        final_df = pd.concat([existing_df, new_results_df], ignore_index=True) if not existing_df.empty else new_results_df
        push_file_to_github(CONFIG_PATH, json.dumps(config, indent=2), config_sha, "Ingested auto-corrected configurations")
        push_file_to_github(RESULTS_PATH, final_df.to_csv(index=False), csv_sha, "Appended missing race results")
        print("Ingestion complete.")

if __name__ == "__main__":
    ingest_latest_race()
