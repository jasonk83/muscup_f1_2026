import os
import json
import requests
import pandas as pd
import base64
from io import StringIO

# Configuration Setup
GITHUB_REPOSITORY = os.environ.get("GITHUB_REPOSITORY", "owner/repo")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
CONFIG_PATH = "seats_config.json"
RESULTS_PATH = "race_results.csv"

HEADERS = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json"
}

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
    # 1. Extract configuration file state
    config, config_sha = fetch_file_from_github(CONFIG_PATH, is_json=True)
    if not config:
        print("Configuration profiles unreachable.")
        return

    # Fetch existing data frame histories
    existing_df, csv_sha = fetch_file_from_github(RESULTS_PATH, is_json=False)

    all_new_results = []
    updates_made = False

    # 2. Loop sequentially through the calendar to bypass API payload limits
    for round_num in range(1, 25):
        api_url = f"https://api.jolpi.ca/ergast/f1/current/{round_num}/results.json"
        response = requests.get(api_url)
        
        if response.status_code != 200:
            break
            
        json_data = response.json()
        race_data = json_data["MRData"]["RaceTable"]["Races"]
        
        if not race_data:
            break # Reached the end of completed races
            
        race = race_data[0]
        round_id = int(race["round"])
        race_id = race["raceName"].lower().replace(" ", "_")
        
        # Check if this round has already been captured
        historical_rounds = [h["round"] for h in config.get("history", [])]
        if round_id in historical_rounds:
            print(f"Round {round_id} has already been logged. Skipping.")
            continue
            
        print(f"Catching up Round {round_id}: {race_id}")
        updates_made = True
        api_results = race["Results"]
        
        # 3. Analyze real-time roster alignment to identify mid-season driver swaps
        for r in api_results:
            driver_name = f"{r['Driver']['givenName']} {r['Driver']['familyName']}"
            team_name = r["Constructor"]["name"]
            position = r["position"]
            
            all_new_results.append({
                "race_id": race_id,
                "round": round_id,
                "driver": driver_name,
                "team": team_name,
                "position": position
            })
            
            matched_seat = None
            for seat_key, seat_data in config["seats"].items():
                if seat_key.split("_")[0] in team_name.lower().replace(" ", ""):
                    if seat_data["current_driver"] == driver_name:
                        matched_seat = seat_key
                        break
            
            if not matched_seat:
                for seat_key, seat_data in config["seats"].items():
                    if seat_key.split("_")[0] in team_name.lower().replace(" ", ""):
                        if seat_data["current_driver"] == "Unassigned" or seat_data["current_driver"] != driver_name:
                            print(f"Driver Swap: Moving {driver_name} into {seat_key}")
                            config["seats"][seat_key]["current_driver"] = driver_name
                            break
                            
        # Append round data back to tracking arrays
        for seat_key, seat_data in config["seats"].items():
            config["history"].append({
                "round": round_id,
                "seat_id": seat_key,
                "driver": seat_data["current_driver"]
            })
            
    # 4. Commit and push data updates back to the GitHub Repository if changes occurred
    if updates_made:
        new_results_df = pd.DataFrame(all_new_results)
        final_df = pd.concat([existing_df, new_results_df], ignore_index=True) if not existing_df.empty else new_results_df
        
        push_file_to_github(CONFIG_PATH, json.dumps(config, indent=2), config_sha, "Catch-up ingested missing configurations")
        push_file_to_github(RESULTS_PATH, final_df.to_csv(index=False), csv_sha, "Appended missing race results")
        print("Catch-up complete!")
    else:
        print("No new rounds to ingest.")

if __name__ == "__main__":
    ingest_latest_race()
