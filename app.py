import streamlit as st
import pandas as pd
import numpy as np
import json
import plotly.express as px
import plotly.graph_objects as go

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

# Used to differentiate Seat 2 drivers on the line charts
TEAM_SECONDARY_COLORS = {
    "Mercedes": "#000000",       # Black
    "McLaren": "#000000",        # Black
    "Ferrari": "#FFC000",        # Yellow
    "Red Bull Racing": "#FCD700",# Yellow
    "Williams": "#00A0DE",       # Light Blue
    "Alpine": "#0050BA",         # Dark Blue
    "Haas F1 Team": "#FFFFFF",   # White
    "Kick Sauber": "#000000",    # Black
    "Sauber": "#000000",         # Black
    "Aston Martin": "#D0FE1D",   # Lime
    "RB": "#FFFFFF",             # White
    "Racing Bulls": "#FFFFFF",   # White
    "Cadillac": "#000000"        # Black
}

PLAYER_FORMAT = {
    "Chief": {"emoji": "🔴", "color": "#EF4444"},   # Red
    "Carly": {"emoji": "🔵", "color": "#3B82F6"},   # Blue
    "Stuebe": {"emoji": "🟣", "color": "#A855F7"},  # Purple
    "Kennedy": {"emoji": "🟢", "color": "#22C55E"}, # Green
    "Unassigned": {"emoji": "⚪", "color": "#9CA3AF"} # Gray
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
    tab_leaderboard, tab_monte_carlo, tab_telemetry, tab_admin = st.tabs([
            "📊 Leaderboard", 
            "🎲 Monte Carlo Projections", 
            "🏎️ Telemetry Lab", 
            "⚙️ Admin & Draft"
        ])
    
    # --- TAB 1: LEADERBOARD & CHARTS ---
    with tab_leaderboard:
        st.header("Season Standings")
        standings, processed_results = process_standings(config_data, results_data.copy())
        
        # 1. Main Leaderboard Table
        display_df = standings.copy()
        display_df["Player"] = display_df["player_owner"].apply(
            lambda p: f"{PLAYER_FORMAT.get(p, PLAYER_FORMAT['Unassigned'])['emoji']} {p}"
        )
        display_df = display_df[["Player", "points"]].rename(columns={"points": "Total Points"})
        st.dataframe(display_df, use_container_width=True)
        
        st.divider()
        
        # 2. Player Progression Line Chart
        st.subheader("Player Points Progression")
        
        player_round_pts = processed_results.groupby(["owner", "round"])["points"].sum().reset_index()
        player_pivot = player_round_pts.pivot(index="round", columns="owner", values="points").fillna(0)
        player_cum = player_pivot.cumsum().reset_index()
        player_melt = player_cum.melt(id_vars="round", var_name="Player", value_name="Cumulative Points")
        
        player_color_map = {p: PLAYER_FORMAT.get(p, PLAYER_FORMAT["Unassigned"])["color"] for p in player_melt["Player"].unique()}
        
        fig_players = px.line(
            player_melt,
            x="round",
            y="Cumulative Points",
            color="Player",
            markers=True,
            color_discrete_map=player_color_map,
            labels={"round": "Race Round", "Cumulative Points": "Total Points", "Player": "Owner"}
        )
        fig_players.update_layout(
            hovermode="x unified",
            xaxis=dict(tickmode='linear', tick0=1, dtick=1),
            legend=dict(orientation="h", yanchor="top", y=-0.2, xanchor="center", x=0.5, title=None)
        )
        st.plotly_chart(fig_players, use_container_width=True)
        
        st.divider()

        # 3. Top 5 Drivers Line Chart
        st.subheader("Top 5 Drivers: Points Progression")
        top_drivers_series = processed_results.groupby("driver")["points"].sum().nlargest(5)
        top_5_names = top_drivers_series.index.tolist()
        
        top_5_df = processed_results[processed_results["driver"].isin(top_5_names)].copy()
        top_5_df = top_5_df.sort_values(by=["driver", "round"])
        top_5_df["Cumulative Points"] = top_5_df.groupby("driver")["points"].cumsum()
        
        driver_to_team = top_5_df.drop_duplicates(subset=["driver"], keep="last").set_index("driver")["team"].to_dict()
        color_map = {driver: TEAM_COLORS.get(team, "#A8A8A8") for driver, team in driver_to_team.items()}
        
        fig_drivers = px.line(
            top_5_df,
            x="round",
            y="Cumulative Points",
            color="driver",
            markers=True,
            color_discrete_map=color_map,
            labels={"round": "Race Round", "Cumulative Points": "Total Points", "driver": "Driver"}
        )
        
        # Inject Secondary Colors for Seat 2 Drivers to differentiate teammate markers
        for trace in fig_drivers.data:
            driver_name = trace.name
            seat_num = '1'
            # Look up which seat this driver occupies
            for seat_key, seat_data in config_data["seats"].items():
                if seat_data["current_driver"] == driver_name:
                    seat_num = seat_key.split("_")[-1]
                    break
            
            if seat_num == '2':
                driver_team = driver_to_team.get(driver_name)
                sec_color = TEAM_SECONDARY_COLORS.get(driver_team, "#FFFFFF")
                # Apply secondary color inside the marker, with primary color as the border
                trace.update(
                    marker=dict(color=sec_color, size=9, line=dict(width=2, color=trace.line.color))
                )
            else:
                trace.update(marker=dict(size=8))
                
        fig_drivers.update_layout(
            hovermode="x unified",
            xaxis=dict(tickmode='linear', tick0=1, dtick=1),
            legend=dict(orientation="h", yanchor="top", y=-0.2, xanchor="center", x=0.5, title=None)
        )
        st.plotly_chart(fig_drivers, use_container_width=True)

        st.divider()

        # 4. Driver Breakdown Table
        st.subheader("Complete Driver Breakdown")
        driver_totals = processed_results.groupby(["driver", "team"])["points"].sum().reset_index()
        driver_totals = driver_totals.sort_values(by="points", ascending=False).reset_index(drop=True)
        driver_totals.index += 1
        driver_totals.rename(columns={"driver": "Driver", "team": "Team", "points": "Total Points"}, inplace=True)
        st.dataframe(driver_totals, use_container_width=True)

    # --- TAB 2: MONTE CARLO SIMULATION ---
    with tab_monte_carlo:
        st.header("Rest-of-Season Projections")
        st.write("Simulating the remaining races based on current season performance...")
        
        completed_rounds = processed_results["round"].nunique()
        remaining_races = max(0, 24 - completed_rounds)
        
        if remaining_races > 0:
            driver_stats = processed_results.groupby("driver")["points"].agg(['mean']).reset_index()
            drivers = driver_stats["driver"].tolist()
            weights = driver_stats["mean"].tolist()
            
            # Safe Probability Normalization
            weights = np.array(weights) + 0.01 
            prob_dist = weights / weights.sum()
            prob_dist = prob_dist / prob_dist.sum() 
            
            num_simulations = 1000
            simulation_results = []
            driver_owner_map = {seat_data["current_driver"]: seat_data["player_owner"] for seat_id, seat_data in config_data["seats"].items()}
            
            progress_bar = st.progress(0)
            for i in range(num_simulations):
                sim_scores = {p: 0 for p in ["Chief", "Carly", "Stuebe", "Kennedy", "Unassigned"]}
                
                for _ in range(remaining_races):
                    simmed_finish = np.random.choice(drivers, size=len(drivers), replace=False, p=prob_dist)
                    for pos, driver in enumerate(simmed_finish):
                        points_awarded = max(0, 22 - pos)
                        owner = driver_owner_map.get(driver, "Unassigned")
                        sim_scores[owner] += points_awarded
                        
                simulation_results.append(sim_scores)
                if i % 100 == 0:
                    progress_bar.progress((i + 1) / num_simulations)
            progress_bar.empty()
            
            sim_df = pd.DataFrame(simulation_results)
            current_totals = standings.set_index("player_owner")["points"].to_dict()
            for player in sim_df.columns:
                sim_df[player] = sim_df[player] + current_totals.get(player, 0)
                
            win_counts = sim_df.idxmax(axis=1).value_counts(normalize=True) * 100
            
            # Explicitly map the emoji-formatted names to their hex colors for the pie chart
            pie_color_map = {f"{PLAYER_FORMAT.get(p, PLAYER_FORMAT['Unassigned'])['emoji']} {p}": PLAYER_FORMAT.get(p, PLAYER_FORMAT['Unassigned'])["color"] for p in ["Chief", "Carly", "Stuebe", "Kennedy", "Unassigned"]}
            
            col_sim1, col_sim2 = st.columns(2)
            with col_sim1:
                st.subheader("Championship Probability")
                win_df = win_counts.reset_index()
                win_df.columns = ["Player", "Win Probability (%)"]
                win_df["Player"] = win_df["Player"].apply(lambda p: f"{PLAYER_FORMAT.get(p, PLAYER_FORMAT['Unassigned'])['emoji']} {p}")
                
                fig_pie = px.pie(
                    win_df, 
                    names="Player", 
                    values="Win Probability (%)", 
                    hole=0.4,
                    color="Player",
                    color_discrete_map=pie_color_map
                )
                st.plotly_chart(fig_pie, use_container_width=True)
                
            with col_sim2:
                st.subheader("Projected Final Points (Average)")
                avg_final = sim_df.mean().sort_values(ascending=False).reset_index()
                avg_final.columns = ["Player", "Projected Points"]
                avg_final["Player"] = avg_final["Player"].apply(lambda p: f"{PLAYER_FORMAT.get(p, PLAYER_FORMAT['Unassigned'])['emoji']} {p}")
                st.dataframe(avg_final.style.format({"Projected Points": "{:.0f}"}), use_container_width=True)
        else:
            st.success("The season is complete! No remaining races to simulate.")
            
# --- TAB 3: TELEMETRY LAB ---
    with tab_telemetry:
        st.header("Driver Telemetry & Track Analysis")
        st.write("Visualizing lap-by-lap racing lines. Older laps fade into the background, with the final lap showing brightest. Green = Accelerating, Yellow = Coasting, Red = Braking.")
        
        try:
            with open("telemetry_summary.json", "r") as f:
                telemetry_data = json.load(f)
                
            race_name = telemetry_data.get("race_name", "Latest Race")
            st.subheader(f"Grand Prix: {race_name}")
            
            drivers_dict = telemetry_data.get("drivers", {})
            driver_options = list(drivers_dict.keys())
            
            if driver_options:
                selected_driver = st.selectbox("Select Driver", driver_options, format_func=lambda x: drivers_dict[x]["name"])
                driver_info = drivers_dict[selected_driver]
                
                # Metrics Row
                col_met1, col_met2, col_met3, col_met4 = st.columns(4)
                col_met1.metric("Total Race Time", driver_info["total_time"])
                col_met2.metric("Best Lap Time", driver_info["best_lap"])
                col_met3.metric("Top Speed (km/h)", f"{driver_info['top_speed_kph']} km/h")
                col_met4.metric("Top Speed (mph)", f"{driver_info['top_speed_mph']} mph")
                
                st.divider()
                
                # Render the 2D Ghost Stack Track Map
                import plotly.graph_objects as go
                fig_track = go.Figure()
                
                laps = driver_info.get("laps", [])
                total_laps = len(laps)
                
                # We draw the laps chronologically so the newest lap renders strictly on top
                for i, lap in enumerate(laps):
                    # Base opacity of 0.15 for lap 1, up to 1.0 for the final lap
                    opacity = 0.15 + (0.85 * (i / max(1, total_laps - 1)))
                    
                    colors = []
                    for state in lap["s"]:
                        if state == 3:
                            colors.append(f"rgba(239, 68, 68, {opacity})") # Red
                        elif state == 1:
                            colors.append(f"rgba(34, 197, 94, {opacity})") # Green
                        else:
                            colors.append(f"rgba(250, 204, 21, {opacity})") # Yellow
                            
                    fig_track.add_trace(go.Scatter(
                        x=lap["x"],
                        y=lap["y"],
                        mode='markers',
                        marker=dict(color=colors, size=3),
                        hoverinfo='skip',
                        name=f"Lap {i+1}",
                        showlegend=False
                    ))
                
                # Lock the aspect ratio so the track doesn't stretch when you resize the window
                fig_track.update_layout(
                    xaxis=dict(visible=False),
                    yaxis=dict(visible=False, scaleanchor="x", scaleratio=1),
                    plot_bgcolor="rgba(0,0,0,0)",
                    paper_bgcolor="rgba(0,0,0,0)",
                    margin=dict(l=0, r=0, t=0, b=0),
                    height=700
                )
                
                st.plotly_chart(fig_track, use_container_width=True)
            else:
                st.info("No telemetry drivers available for this race.")
                
        except FileNotFoundError:
            st.info("Telemetry data is currently being generated. Please check back after the GitHub Action completes.")
            
    # --- TAB 4: ADMIN & DRAFT ---
    with tab_admin:
        st.header("Draft Management & Admin")
        st.write("Modify seat ownership below. Changes will save to the local configuration.")
        
        pwd = st.text_input("Enter Admin Password", type="password")
        
        if pwd == "Kennedy":
            st.success("Access Granted: Administrator Mode Active")
            
            seat_records = []
            for seat_id, data in config_data["seats"].items():
                seat_records.append({"Seat": seat_id, "Current Driver": data["current_driver"], "Player Owner": data["player_owner"]})
            df_seats = pd.DataFrame(seat_records)
            
            st.write("### Edit Seat Ownership")
            st.info("Assign unowned seats or execute mid-season trades here.")
            edited_df = st.data_editor(
                df_seats,
                column_config={
                    "Seat": st.column_config.TextColumn("Seat Designation", disabled=True),
                    "Current Driver": st.column_config.TextColumn("Current Real-World Driver", disabled=True),
                    "Player Owner": st.column_config.SelectboxColumn(
                        "Player Owner",
                        options=["Chief", "Carly", "Stuebe", "Kennedy", "Unassigned"],
                        required=True
                    )
                },
                hide_index=True,
                use_container_width=True
            )
            
            if st.button("Save Draft Configuration", type="primary"):
                for index, row in edited_df.iterrows():
                    config_data["seats"][row["Seat"]]["player_owner"] = row["Player Owner"]
                
                with open("seats_config.json", "w") as f:
                    json.dump(config_data, f, indent=2)
                
                st.success("Configuration successfully updated! Data will reflect immediately upon app reload.")
                st.cache_data.clear()
                st.rerun()
                
        elif pwd:
            st.error("Incorrect Password. Access Denied.")

else:
    st.info("Awaiting race data. Please ensure the GitHub Action has run successfully.")
