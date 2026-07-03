import streamlit as st
import pandas as pd
import numpy as np
import json
import plotly.express as px

# --- SETUP & CONSTANTS ---
st.set_page_config(page_title="MusCup F1 2026 Dashboard", layout="wide")

TEAM_COLORS = {
    "Mercedes": "#00D2BE",
    "McLaren": "#FF8000",
    "Ferrari": "#DC0000",
    "Red Bull Racing": "#3671C6",
    "Williams": "#005AFF",
    "Alpine": "#FF87BC",
    "Haas F1 Team": "#E6002B",
    "Kick Sauber": "#00E701",
    "Sauber": "#00E701",
    "Aston Martin": "#229971",
    "RB": "#6692FF",
    "Racing Bulls": "#6692FF",
    "Cadillac": "#FFB81C" 
}

PLAYER_FORMAT = {
    "Chief": {"emoji": "🔴"},
    "Carly": {"emoji": "🔵"},
    "Stuebe": {"emoji": "🟣"},
    "Kennedy": {"emoji": "🟢"},
    "Unassigned": {"emoji": "⚪"}
}

# --- DATA LOADING ---
@st.cache_data(ttl=60)
def load_data():
    try:
        with open("seats_config.json", "r") as f:
            config_data = json.load(f)
        results_data = pd.read_csv("race_results.csv")
        return config_data, results_data
    except Exception as e:
        st.error(f"Error loading data: {e}")
        return None, pd.DataFrame()

# --- LOGIC & MATH ---
def compute_points(position):
    if position == "DNF" or pd.isna(position):
        return 0
    try:
        pos = int(float(position))
        return max(0, 23 - pos)
    except:
        return 0

def process_standings(config, results):
    # Map drivers to their owners based on the config
    driver_owner = {seat_data["current_driver"]: seat_data["player_owner"] for seat_id, seat_data in config["seats"].items()}
    
    results["points"] = results["position"].apply(compute_points)
    results["owner"] = results["driver"].map(driver_owner).fillna("Unassigned")
    
    # Player Standings
    standings = results.groupby("owner")["points"].sum().reset_index()
    standings.rename(columns={"owner": "player_owner"}, inplace=True)
    standings = standings.sort_values(by="points", ascending=False).reset_index(drop=True)
    standings.index += 1
    
    return standings, results

# --- UI & DASHBOARD ---
st.title("🏎️ MusCup 2026 F1 Fantasy Tracker")

config_data, results_data = load_data()

if config_data and not results_data.empty:
    tab_leaderboard, tab_monte_carlo = st.tabs(["📊 Leaderboard", "🎲 Monte Carlo Projections"])
    
    # --- TAB 1: LEADERBOARD ---
    with tab_leaderboard:
        st.header("Season Standings")
        standings, processed_results = process_standings(config_data, results_data.copy())
        
        col1, col2 = st.columns([1, 1.5])
        
        with col1:
            st.subheader("Current Leaderboard")
            display_df = standings.copy()
            display_df["Player"] = display_df["player_owner"].apply(
                lambda p: f"{PLAYER_FORMAT.get(p, PLAYER_FORMAT['Unassigned'])['emoji']} {p}"
            )
            display_df = display_df[["Player", "points"]].rename(columns={"points": "Total Points"})
            st.dataframe(display_df, use_container_width=True)
            
            # --- DRIVER BREAKDOWN TABLE ---
            st.subheader("Driver Breakdown")
            driver_totals = processed_results.groupby(["driver", "team"])["points"].sum().reset_index()
            driver_totals = driver_totals.sort_values(by="points", ascending=False).reset_index(drop=True)
            driver_totals.index += 1
            driver_totals.rename(columns={"driver": "Driver", "team": "Team", "points": "Total Points"}, inplace=True)
            st.dataframe(driver_totals, use_container_width=True)
            
        with col2:
            st.subheader("Top 5 Drivers: Points Progression")
            # 1. Identify top 5 drivers
            top_drivers_series = processed_results.groupby("driver")["points"].sum().nlargest(5)
            top_5_names = top_drivers_series.index.tolist()
            
            # 2. Filter and calculate cumulative points
            top_5_df = processed_results[processed_results["driver"].isin(top_5_names)].copy()
            top_5_df = top_5_df.sort_values(by=["driver", "round"])
            top_5_df["Cumulative Points"] = top_5_df.groupby("driver")["points"].cumsum()
            
            # 3. Map colors based on team
            driver_to_team = top_5_df.drop_duplicates(subset=["driver"], keep="last").set_index("driver")["team"].to_dict()
            color_map = {driver: TEAM_COLORS.get(team, "#A8A8A8") for driver, team in driver_to_team.items()}
            
            # 4. Generate line chart
            fig_drivers = px.line(
                top_5_df,
                x="round",
                y="Cumulative Points",
                color="driver",
                markers=True,
                color_discrete_map=color_map,
                labels={"round": "Race Round", "Cumulative Points": "Total Points", "driver": "Driver"}
            )
            fig_drivers.update_layout(hovermode="x unified", xaxis=dict(tickmode='linear', tick0=1, dtick=1))
            st.plotly_chart(fig_drivers, use_container_width=True)

    # --- TAB 2: MONTE CARLO SIMULATION ---
    with tab_monte_carlo:
        st.header("Rest-of-Season Projections")
        st.write("Simulating the remaining races based on current season performance...")
        
        # Determine remaining races (24 total in the season)
        completed_rounds = processed_results["round"].nunique()
        remaining_races = max(0, 24 - completed_rounds)
        
        if remaining_races > 0:
            # 1. Calculate driver weights based on average points scored per race
            driver_stats = processed_results.groupby("driver")["points"].agg(['mean']).reset_index()
            drivers = driver_stats["driver"].tolist()
            weights = driver_stats["mean"].tolist()
            
            # 2. Add a tiny baseline weight to avoid 0-probability crashes
            weights = np.array(weights) + 0.01 
            
            # 3. SAFELY Normalize probabilities to sum exactly to 1.0
            prob_dist = weights / weights.sum()
            prob_dist = prob_dist / prob_dist.sum() # Double-check normalization for float precision
            
            num_simulations = 1000
            simulation_results = []
            driver_owner_map = {seat_data["current_driver"]: seat_data["player_owner"] for seat_id, seat_data in config_data["seats"].items()}
            
            # 4. Run the Simulation Loop
            progress_bar = st.progress(0)
            for i in range(num_simulations):
                sim_scores = {p: 0 for p in ["Chief", "Carly", "Stuebe", "Kennedy", "Unassigned"]}
                
                for _ in range(remaining_races):
                    # The ValueError is fixed here thanks to strict prob_dist normalization
                    simmed_finish = np.random.choice(drivers, size=len(drivers), replace=False, p=prob_dist)
                    
                    # Award points (1st = 22, 2nd = 21, etc.)
                    for pos, driver in enumerate(simmed_finish):
                        points_awarded = max(0, 22 - pos)
                        owner = driver_owner_map.get(driver, "Unassigned")
                        sim_scores[owner] += points_awarded
                        
                simulation_results.append(sim_scores)
                if i % 100 == 0:
                    progress_bar.progress((i + 1) / num_simulations)
            progress_bar.empty()
            
            # 5. Process and Display Simulation Output
            sim_df = pd.DataFrame(simulation_results)
            
            # Add current points to simulated points
            current_totals = standings.set_index("player_owner")["points"].to_dict()
            for player in sim_df.columns:
                sim_df[player] = sim_df[player] + current_totals.get(player, 0)
                
            win_counts = sim_df.idxmax(axis=1).value_counts(normalize=True) * 100
            
            col_sim1, col_sim2 = st.columns(2)
            with col_sim1:
                st.subheader("Championship Probability")
                win_df = win_counts.reset_index()
                win_df.columns = ["Player", "Win Probability (%)"]
                win_df["Player"] = win_df["Player"].apply(lambda p: f"{PLAYER_FORMAT.get(p, PLAYER_FORMAT['Unassigned'])['emoji']} {p}")
                
                fig_pie = px.pie(win_df, names="Player", values="Win Probability (%)", hole=0.4)
                st.plotly_chart(fig_pie, use_container_width=True)
                
            with col_sim2:
                st.subheader("Projected Final Points (Average)")
                avg_final = sim_df.mean().sort_values(ascending=False).reset_index()
                avg_final.columns = ["Player", "Projected Points"]
                avg_final["Player"] = avg_final["Player"].apply(lambda p: f"{PLAYER_FORMAT.get(p, PLAYER_FORMAT['Unassigned'])['emoji']} {p}")
                st.dataframe(avg_final.style.format({"Projected Points": "{:.0f}"}), use_container_width=True)
        else:
            st.success("The season is complete! No remaining races to simulate.")
else:
    st.info("Awaiting race data. Please ensure the GitHub Action has run successfully.")
