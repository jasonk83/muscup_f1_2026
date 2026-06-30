import streamlit as st
import pandas as pd
import numpy as np
import requests
import json
import base64
from io import StringIO

# --- STREAMLIT CONFIGURATION ---
st.set_page_config(page_title="F1 2026 Fantasy Tracker", layout="wide", page_icon="🏎️")
st.title("🏎️ F1 2026 Championship Fantasy Tracker")

# --- CONFIG & SECRETS ---
GITHUB_TOKEN = st.secrets.get("GITHUB_TOKEN", "")
REPO_OWNER = st.secrets.get("REPO_OWNER", "")
REPO_NAME = st.secrets.get("REPO_NAME", "")
CONFIG_PATH = "seats_config.json"
RESULTS_PATH = "race_results.csv"

# --- GITHUB FILE HELPER FUNCTIONS ---
def load_file_from_github(file_path, is_json=True):
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{file_path}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"} if GITHUB_TOKEN else {}
    response = requests.get(url, headers=headers)
    
    if response.status_code == 200:
        content = base64.b64decode(response.json()["content"]).decode("utf-8")
        if is_json:
            return json.loads(content)
        else:
            return pd.read_csv(StringIO(content))
    else:
        return {} if is_json else pd.DataFrame(columns=["race_id", "round", "driver", "team", "position"])

def save_json_to_github(file_path, data, commit_message="Update configurations"):
    if not GITHUB_TOKEN:
        st.warning("No GitHub Token found. Changes will only persist in temporary local cache.")
        return False
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{file_path}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
    
    get_res = requests.get(url, headers=headers)
    sha = get_res.json().get("sha") if get_res.status_code == 200 else None
    
    serialized_data = json.dumps(data, indent=2)
    payload = {
        "message": commit_message,
        "content": base64.b64encode(serialized_data.encode("utf-8")).decode("utf-8")
    }
    if sha:
        payload["sha"] = sha
        
    put_res = requests.put(url, json=payload, headers=headers)
    return put_res.status_code in [200, 201]

# --- CORE CALCULATIONS ENGINE ---
def compute_points(position):
    try:
        pos = int(position)
        if 1 <= pos <= 22:
            return 23 - pos
    except (ValueError, TypeError):
        return 0
    return 0

def process_standings(config, results_df):
    if results_df.empty or "history" not in config:
        return pd.DataFrame(), pd.DataFrame()
        
    history_records = []
    for h in config["history"]:
        history_records.append({
            "round": h["round"],
            "seat_id": h["seat_id"],
            "driver": h["driver"],
            "player_owner": config["seats"][h["seat_id"]]["player_owner"]
        })
    hist_df = pd.DataFrame(history_records)
    
    results_df["points"] = results_df["position"].apply(compute_points)
    merged = pd.merge(results_df, hist_df, on=["round", "driver"], how="inner")
    
    player_standings = merged.groupby("player_owner")["points"].sum().reset_index()
    player_standings = player_standings.sort_values(by="points", ascending=False).reset_index(drop=True)
    player_standings.index += 1
    player_standings.index.name = "Rank"
    
    timeline = merged.groupby(["round", "player_owner"])["points"].sum().groupby(level=1).cumsum().reset_index()
    
    return player_standings, timeline

# --- DATA ACQUISITION LAYER ---
config_data = load_file_from_github(CONFIG_PATH, is_json=True)
results_data = load_file_from_github(RESULTS_PATH, is_json=False)

if not config_data:
    st.info("Loading template configurations. Please connect your GitHub account via Streamlit Secrets.")
    config_data = {"seats": {}, "history": []}

# --- RENDER APPLICATION TABS ---
tab_leaderboard, tab_simulation, tab_commissioner = st.tabs([
    "🏆 Standings & Analytics", 
    "🎲 Monte Carlo Predictor", 
    "🛠️ Admin & Draft Space"
])

# --- TAB 1: LEADERBOARD & PERFORMANCE CHARTS ---
with tab_leaderboard:
    st.header("Season Standings")
    if not results_data.empty:
        standings, timeline_df = process_standings(config_data, results_data)
        
        if not standings.empty:
            col1, col2 = st.columns([1, 2])
            with col1:
                st.subheader("Current Leaderboard")
                st.dataframe(standings, use_container_width=True)
            with col2:
                st.subheader("Points Progression Tracker")
                pivot_timeline = timeline_df.pivot(index="round", columns="player_owner", values="points").fillna(0)
                st.line_chart(pivot_timeline)
        else:
            st.info("Awaiting initial draft mapping configuration profiles.")
    else:
        st.info("No race results have been recorded for the season yet.")

# --- TAB 2: MONTE CARLO PREDICTOR MODEL ---
with tab_simulation:
    st.header("Championship Projection Engine")
    st.write("Simulates remaining races using baseline driver ratings to estimate final outcome probabilities.")
    
    if not results_data.empty and config_data.get("seats"):
        current_round = results_data["round"].max()
        remaining_races = max(0, 24 - current_round)
        
        if remaining_races > 0:
            run_sim = st.button("Execute 1,000 Iteration Simulation")
            if run_sim:
                standings, _ = process_standings(config_data, results_data)
                current_scores = dict(zip(standings["player_owner"], standings["points"]))
                
                players = list(set([seat["player_owner"] for seat in config_data["seats"].values() if seat["player_owner"] != "Unassigned"]))
                if not players:
                    st.warning("Assign drivers to players inside the Admin Space to calculate simulations.")
                else:
                    sim_scores = {p: [] for p in players}
                    
                    avg_finishes = results_data.groupby("driver")["position"].apply(
                        lambda x: pd.to_numeric(x, errors='coerce').mean()
                    ).fillna(11).to_dict()
                    
                    for _ in range(1000):
                        temp_scores = {p: current_scores.get(p, 0) for p in players}
                        
                        for r in range(int(current_round) + 1, 25):
                            drivers = list(avg_finishes.keys())
                            scores_pool = [1 / (avg_finishes[d] + np.random.normal(0, 3.5)) for d in drivers]
                            prob_dist = np.exp(scores_pool) / np.sum(np.exp(scores_pool))
                            
                            simmed_finish = np.random.choice(drivers, size=len(drivers), replace=False, p=prob_dist)
                            
                            for pos_idx, drv in enumerate(simmed_finish):
                                fin_pos = pos_idx + 1
                                for s_id, s_info in config_data["seats"].items():
                                    if s_info["current_driver"] == drv:
                                        owner = s_info["player_owner"]
                                        if owner in temp_scores:
                                            temp_scores[owner] += compute_points(fin_pos)
                                            
                        for p in players:
                            sim_scores[p].append(temp_scores[p])
                    
                    rank_counts = {p: [0, 0, 0, 0] for p in players}
                    for idx in range(1000):
                        round_results = {p: sim_scores[p][idx] for p in players}
                        sorted_players = sorted(round_results, key=round_results.get, reverse=True)
                        for rank_pos, p_name in enumerate(sorted_players):
                            if rank_pos < 4:
                                rank_counts[p_name][rank_pos] += 1
                                
                    summary_data = []
                    for p in players:
                        summary_data.append({
                            "Player": p,
                            "Win Probability": f"{rank_counts[p][0] / 10}%",
                            "Podium Probability": f"{sum(rank_counts[p][:3]) / 10}%",
                            "Wooden Spoon Probability": f"{rank_counts[p][3] / 10}%"
                        })
                    st.table(pd.DataFrame(summary_data))
        else:
            st.success("The season is complete! Check out the final leaderboard tab.")
    else:
        st.info("Awaiting initial draft configurations and verified results data.")

# --- TAB 3: COMMISSIONER SPACE & LINEUP MANAGERS ---
with tab_commissioner:
    st.header("League Configuration Desk")
    
    if config_data.get("seats"):
        st.subheader("Manage Active Rosters")
        st.write("Assign players to their 5 specific team seats. Saving configuration updates writes directly back to GitHub.")
        
        grid_rows = []
        for seat_key, data in config_data["seats"].items():
            grid_rows.append({
                "Seat Key": seat_key,
                "Current Driver": data["current_driver"],
                "Player Owner": data["player_owner"]
            })
        df_editor = pd.DataFrame(grid_rows)
        
        edited_df = st.data_editor(
            df_editor, 
            column_config={"Player Owner": st.column_config.SelectboxColumn(options=["Unassigned", "Carly", "Chief", "Kennedy", "Stuebe"])},
            disabled=["Seat Key", "Current Driver"],
            use_container_width=True
        )
        
        if st.button("Commit and Push Alignment to GitHub"):
            for _, row in edited_df.iterrows():
                config_data["seats"][row["Seat Key"]]["player_owner"] = row["Player Owner"]
                
            success = save_json_to_github(CONFIG_PATH, config_data, "Update player draft seat mappings")
            if success:
                st.success("Draft configurations successfully committed to your GitHub Repository!")
                st.rerun()
            else:
                st.error("Failed to commit updates to GitHub. Verify your access tokens.")
