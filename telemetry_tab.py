"""
telemetry_tab.py
Reusable module that embeds the complete interactive F1 Telemetry Lab
directly into existing Streamlit applications (such as muscup_f1_2026/app.py).
"""

import streamlit as st
import pandas as pd
import numpy as np
import fastf1
import sys
import os

# Add package directory to sys.path so modules resolve whether imported locally or externally
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

import telemetry_service as ts
import visualizer as viz


def render_telemetry_tab(default_year: int = 2026):
    """
    Renders the full interactive week-by-week F1 Telemetry Lab inside any Streamlit container or tab.
    """
    st.subheader("🏎️ Interactive F1 Telemetry Lab")
    st.write(
        "Analyze moment-by-moment driver behavior across any race weekend. "
        "Observe when cars are accelerating, coasting, or braking through corners, "
        "monitor track temperatures and tyre life, and scrub through laps synchronously on the track map."
    )

    # Top Controls Bar: Season, Round, Session, Mode
    col_c1, col_c2, col_c3, col_c4 = st.columns([1, 2, 1.2, 1.5])

    available_seasons = ts.get_available_seasons()
    with col_c1:
        selected_year = st.selectbox(
            "Season",
            available_seasons,
            index=available_seasons.index(default_year) if default_year in available_seasons else 0,
            key="tab_season"
        )

    schedule_df = ts.get_season_schedule(selected_year)
    if schedule_df.empty:
        st.info(f"Schedule for {selected_year} is not yet available.")
        return

    round_options = schedule_df["RoundNumber"].tolist()
    round_display_map = schedule_df.set_index("RoundNumber")["DisplayName"].to_dict()
    default_idx = len(round_options) - 1 if selected_year < 2026 else 0

    with col_c2:
        selected_round = st.selectbox(
            "Grand Prix Weekend",
            round_options,
            index=min(default_idx, len(round_options) - 1),
            format_func=lambda r: round_display_map.get(r, f"Round {r}"),
            key="tab_round"
        )

    with col_c3:
        session_options = {"R": "🏁 Race", "Q": "⏱️ Qualifying", "S": "⚡ Sprint"}
        selected_session = st.selectbox(
            "Session",
            list(session_options.keys()),
            format_func=lambda s: session_options[s],
            key="tab_session"
        )

    with col_c4:
        analysis_mode = st.radio(
            "Mode",
            ["Single Driver", "Head-to-Head Comparison"],
            horizontal=True,
            key="tab_mode"
        )

    # Load FastF1 Session
    with st.spinner("Fetching synchronized telemetry data..."):
        session = ts.load_session(selected_year, selected_round, selected_session)

    if session is None:
        st.warning(f"Telemetry data has not yet been published for {selected_year} Round {selected_round}. Please pick another round.")
        return

    drivers_dict = ts.get_session_drivers(session)
    if not drivers_dict:
        st.info("No driver telemetry found for this session.")
        return

    driver_codes = list(drivers_dict.keys())

    # Driver & Lap Selectors
    col_d1, col_d2 = st.columns(2)

    with col_d1:
        st.markdown("**Driver 1 (Primary)**")
        driver1_code = st.selectbox(
            "Select Driver 1",
            driver_codes,
            format_func=lambda c: f"{drivers_dict[c]['name']} ({c}) - {drivers_dict[c]['team']}",
            key="tab_driver1"
        )
        driver1_info = drivers_dict[driver1_code]
        laps1_df = ts.get_driver_laps_summary(session, driver1_code)
        
        if laps1_df.empty:
            st.warning(f"No completed laps recorded for {driver1_info['name']}.")
            return
            
        fastest_row1 = laps1_df[laps1_df["IsFastest"]]
        def_idx1 = int(fastest_row1.index[0]) if not fastest_row1.empty else 0
        lap1_num = st.selectbox(
            "Select Lap 1",
            laps1_df["LapNumber"].tolist(),
            index=def_idx1,
            format_func=lambda n: laps1_df[laps1_df["LapNumber"] == n]["DisplayLabel"].values[0],
            key="tab_lap1"
        )

    driver2_code = None
    driver2_info = None
    lap2_obj = None

    if "Head-to-Head" in analysis_mode:
        with col_d2:
            st.markdown("**Driver 2 (Comparison)**")
            default_d2_idx = 1 if len(driver_codes) > 1 else 0
            driver2_code = st.selectbox(
                "Select Driver 2",
                driver_codes,
                index=default_d2_idx,
                format_func=lambda c: f"{drivers_dict[c]['name']} ({c}) - {drivers_dict[c]['team']}",
                key="tab_driver2"
            )
            driver2_info = drivers_dict[driver2_code]
            laps2_df = ts.get_driver_laps_summary(session, driver2_code)
            
            if laps2_df.empty:
                st.warning(f"No completed laps recorded for {driver2_info['name']}.")
                return
                
            fastest_row2 = laps2_df[laps2_df["IsFastest"]]
            def_idx2 = int(fastest_row2.index[0]) if not fastest_row2.empty else 0
            lap2_num = st.selectbox(
                "Select Lap 2",
                laps2_df["LapNumber"].tolist(),
                index=def_idx2,
                format_func=lambda n: laps2_df[laps2_df["LapNumber"] == n]["DisplayLabel"].values[0],
                key="tab_lap2"
            )

    # Extract Telemetry
    lap1_obj = session.laps.pick_drivers(driver1_code).pick_laps(lap1_num).iloc[0]
    tel1 = ts.extract_lap_telemetry(lap1_obj, session)

    tel2 = None
    delta_df = None
    if driver2_code:
        lap2_obj = session.laps.pick_drivers(driver2_code).pick_laps(lap2_num).iloc[0]
        tel2 = ts.extract_lap_telemetry(lap2_obj, session)
        h2h_data = ts.compute_head_to_head_telemetry(lap1_obj, lap2_obj, session)
        delta_df = h2h_data.get("delta")

    if tel1.empty:
        st.error("Telemetry channels could not be extracted for this lap.")
        return

    corners_df, _ = ts.get_circuit_layout_and_corners(session)

    # Scrubber
    max_lap_dist = float(tel1["Distance"].max())
    scrub_dist = st.slider(
        "📍 Lap Distance Scrubber (meters)",
        min_value=0.0,
        max_value=max_lap_dist,
        value=min(600.0, max_lap_dist),
        step=15.0,
        key="tab_scrubber"
    )

    # Instantaneous HUD
    metrics = viz.get_scrubber_instant_metrics(tel1, tel2, scrub_dist, "km/h")
    m1 = metrics.get("driver1", {})
    m2 = metrics.get("driver2", {})

    st.markdown(f"""
    <div style="background-color:#1E293B; padding:12px; border-radius:8px; margin-bottom:12px;">
        <span style="color:#38BDF8; font-weight:700;">🏎️ {driver1_info['name']}:</span> 
        <b>{m1.get('speed', '')}</b> | 
        State: <b>{m1.get('state', '')}</b> | 
        Throttle: <b>{m1.get('throttle', '')}</b> | 
        Brake: <b>{m1.get('brake', '')}</b> | 
        {m1.get('gear', '')} | 
        Track Temp: <b>{m1.get('track_temp', '')}</b> | 
        Tyre: <b>{m1.get('compound', '')} ({m1.get('tyre_life', '')})</b>
        {f"<br><span style='color:#F59E0B; font-weight:700;'>🏎️ {driver2_info['name']}:</span> <b>{m2.get('speed', '')}</b> | State: <b>{m2.get('state', '')}</b> | Throttle: <b>{m2.get('throttle', '')}</b> | Brake: <b>{m2.get('brake', '')}</b>" if driver2_code and m2 else ""}
    </div>
    """, unsafe_allow_html=True)

    # Visualizations
    col_v1, col_v2 = st.columns([1, 1.2])

    with col_v1:
        st.markdown("**2D Circuit Layout (Driving State Overlay)**")
        fig_track = viz.create_track_map_figure(
            tel1=tel1,
            tel2=tel2,
            corners_df=corners_df,
            scrub_dist=scrub_dist,
            color_mode="Driving State",
            driver1_name=driver1_info["name"],
            driver2_name=driver2_info["name"] if driver2_info else "",
            color1=driver1_info["color"],
            color2=driver2_info["color"] if driver2_info else "#FF8000"
        )
        st.plotly_chart(fig_track, use_container_width=True)

    with col_v2:
        st.markdown("**Synchronized Multi-Channel Telemetry**")
        fig_traces = viz.create_telemetry_traces_figure(
            tel1=tel1,
            tel2=tel2,
            delta_df=delta_df,
            scrub_dist=scrub_dist,
            driver1_name=driver1_info["name"],
            driver2_name=driver2_info["name"] if driver2_info else "",
            color1=driver1_info["color"],
            color2=driver2_info["color"] if driver2_info else "#FF8000"
        )
        st.plotly_chart(fig_traces, use_container_width=True)

    # Corner Breakdown
    if corners_df is not None and not corners_df.empty:
        with st.expander("📊 Corner Apex Speed & Behavior Breakdown", expanded=False):
            corner_table = viz.compute_corner_breakdown(
                corners_df=corners_df,
                tel1=tel1,
                tel2=tel2,
                driver1_name=driver1_info["name"],
                driver2_name=driver2_info["name"] if driver2_info else "",
                speed_unit="km/h"
            )
            st.dataframe(corner_table, use_container_width=True, hide_index=True)
