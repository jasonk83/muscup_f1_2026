import fastf1
import pandas as pd
import json
import os
import sys
import base64
import requests

# GitHub Configuration Setup
GITHUB_REPOSITORY = os.environ.get("GITHUB_REPOSITORY", "owner/repo")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
TELEMETRY_PATH = "telemetry_summary.json"

HEADERS = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json"
}

# Enable FastF1 Cache to prevent redundant downloads
if not os.path.exists('fastf1_cache'):
    os.makedirs('fastf1_cache')
fastf1.Cache.enable_cache('fastf1_cache')

def get_file_sha(path):
    url = f"https://api.github.com/repos/{GITHUB_REPOSITORY}/contents/{path}"
    res = requests.get(url, headers=HEADERS)
    if res.status_code == 200:
        return res.json().get("sha")
    return None

def push_file_to_github(path, content_str, sha, message):
    url = f"https://api.github.com/repos/{GITHUB_REPOSITORY}/contents/{path}"
    payload = {
        "message": message,
        "content": base64.b64encode(content_str.encode("utf-8")).decode("utf-8")
    }
    if sha:
        payload["sha"] = sha
    res = requests.put(url, json=payload, headers=HEADERS)
    if res.status_code in [200, 201]:
        print(f"Successfully pushed {path} to GitHub.")
    else:
        print(f"Failed to push {path}. API Response: {res.text}")

def generate_telemetry_summary():
    print("Initializing FastF1 Telemetry Extraction...")
    
    # 1. Read local results to find the most recent round
    try:
        results_df = pd.read_csv("race_results.csv")
    # Ensure round is numeric before finding max
        results_df['round'] = pd.to_numeric(results_df['round'], errors='coerce')
        latest_round = int(results_df['round'].max())
        latest_round = int(results_df['round'].max())
    except Exception as e:
        print(f"Could not read race_results.csv to determine latest round: {e}")
        sys.exit(1)
        
    # 2. Fetch the session from FastF1
    try:
        session = fastf1.get_session(2026, latest_round, 'R')
        session.load(telemetry=True, weather=False, messages=False)
    except Exception as e:
        print(f"Telemetry not yet published by F1 or connection error: {e}")
        sys.exit(0)

    race_name = session.event['EventName']
    results = session.results
    laps = session.laps

    telemetry_db = {
        "race_name": race_name,
        "drivers": {}
    }

    # 3. Loop through every driver and extract every lap
    for index, row in results.iterrows():
        driver = row['Abbreviation']
        driver_laps = laps.pick_driver(driver)
        
        if driver_laps.empty:
            continue
            
        fastest_lap = driver_laps.pick_fastest()
        if pd.isna(fastest_lap['LapTime']):
            continue

        laps_data = []
        top_speed_kph = 0
        
        # Build the chronological stack
        for _, lap in driver_laps.iterlaps():
            if pd.isna(lap['LapTime']):
                continue
                
            tel = lap.get_telemetry().iloc[::5] # Downsample by 5 to keep file lightweight
            if tel.empty:
                continue
                
            lap_top_speed = float(tel['Speed'].max())
            if lap_top_speed > top_speed_kph:
                top_speed_kph = lap_top_speed
                
            states = []
            for _, t_row in tel.iterrows():
                if t_row['Brake'] > 0:
                    states.append(3) # 3 = Braking
                elif t_row['Throttle'] > 90:
                    states.append(1) # 1 = Accelerating
                else:
                    states.append(2) # 2 = Coasting
            
            laps_data.append({
                "x": [round(x, 1) for x in tel['X'].tolist()],
                "y": [round(y, 1) for y in tel['Y'].tolist()],
                "s": states
            })

        top_speed_mph = top_speed_kph * 0.621371

        total_time_td = row['Time']
        total_time = str(total_time_td).split('.')[-2] if not pd.isna(total_time_td) else "DNF / Not Classified"
        
        best_lap_td = fastest_lap['LapTime']
        best_lap = str(best_lap_td).split('.')[-2][2:] if not pd.isna(best_lap_td) else "N/A"

        telemetry_db["drivers"][driver] = {
            "name": row['FullName'],
            "total_time": total_time,
            "best_lap": best_lap,
            "top_speed_kph": round(top_speed_kph, 1),
            "top_speed_mph": round(top_speed_mph, 1),
            "laps": laps_data
        }

    # 4. Push directly to GitHub
    summary_json = json.dumps(telemetry_db)
    current_sha = get_file_sha(TELEMETRY_PATH)
    push_file_to_github(TELEMETRY_PATH, summary_json, current_sha, f"Telemetry update for {race_name}")

if __name__ == "__main__":
    generate_telemetry_summary()
