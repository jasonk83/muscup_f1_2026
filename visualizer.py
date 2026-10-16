"""
visualizer.py
Interactive Plotly visualizations for F1 Telemetry Lab:
1. 2D Circuit Track Map with Driving State Heatmap (Accelerating/Braking/Coasting),
   turn/corner badges, and real-time vehicle position cursor.
2. Synchronized Multi-Row Telemetry Charts (Speed, Delta Time, Throttle/Brake, Gear).
3. Instantaneous Telemetry HUD & Corner Apex Analysis.
"""

import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from typing import Dict, Any, Optional, Tuple, List


# State color definitions
STATE_COLORS = {
    1: "#22C55E",  # Green: Accelerating (Throttle > 25, Brake == 0)
    2: "#F59E0B",  # Amber/Gold: Coasting (Throttle <= 25, Brake == 0)
    3: "#EF4444"   # Red: Braking (Brake > 0)
}

STATE_NAMES = {
    1: "Accelerating 🟢",
    2: "Coasting 🟡",
    3: "Braking 🔴"
}


# --- 1. 2D INTERACTIVE TRACK MAP ---

def create_track_map_figure(
    tel1: pd.DataFrame,
    tel2: Optional[pd.DataFrame] = None,
    corners_df: Optional[pd.DataFrame] = None,
    scrub_dist: float = 0.0,
    color_mode: str = "Driving State",  # "Driving State" or "Speed"
    driver1_name: str = "Driver 1",
    driver2_name: str = "Driver 2",
    color1: str = "#00D2BE",
    color2: str = "#FF8000",
    speed_unit: str = "km/h"
) -> go.Figure:
    """
    Renders an interactive 2D circuit layout.
    - Path colored by driving state (Accelerating = Green, Coasting = Gold, Braking = Red) or speed.
    - Official corner markers (T1, T2...).
    - Vehicle position marker(s) locked to scrub_dist.
    - True 1:1 geometric aspect ratio (no circuit warping).
    """
    fig = go.Figure()

    if tel1 is None or tel1.empty:
        fig.update_layout(title="No telemetry data available for track map")
        return fig

    # 1. Base Circuit Trace
    if color_mode == "Driving State":
        # Map state colors
        colors = [STATE_COLORS.get(s, "#9CA3AF") for s in tel1["DrivingState"]]
        state_labels = [STATE_NAMES.get(s, "Unknown") for s in tel1["DrivingState"]]
        
        speed_col = "Speed_kmh" if speed_unit == "km/h" else "Speed_mph"
        hover_texts = [
            f"<b>{driver1_name}</b><br>"
            f"Distance: {d}m<br>"
            f"Speed: {spd} {speed_unit}<br>"
            f"Status: {st}<br>"
            f"Throttle: {th}% | Brake: {'ON' if br else 'OFF'}<br>"
            f"Gear: {g} | Track Temp: {tt}°C"
            for d, spd, st, th, br, g, tt in zip(
                tel1["Distance"], tel1[speed_col], state_labels,
                tel1["Throttle"], tel1["Brake"], tel1["nGear"], tel1["TrackTemp"]
            )
        ]

        fig.add_trace(go.Scatter(
            x=tel1["X"],
            y=tel1["Y"],
            mode="lines+markers",
            line=dict(color="rgba(120, 120, 120, 0.4)", width=4),
            marker=dict(
                size=4,
                color=colors,
                showscale=False
            ),
            hoverinfo="text",
            hovertext=hover_texts,
            name=f"{driver1_name} Driving States",
            showlegend=False
        ))
    else:
        # Speed gradient heatmap
        speed_col = "Speed_kmh" if speed_unit == "km/h" else "Speed_mph"
        fig.add_trace(go.Scatter(
            x=tel1["X"],
            y=tel1["Y"],
            mode="markers",
            marker=dict(
                size=5,
                color=tel1[speed_col],
                colorscale="Viridis",
                colorbar=dict(title=f"Speed ({speed_unit})", x=1.02),
                showscale=True
            ),
            hoverinfo="text",
            hovertext=[f"Dist: {d}m | Speed: {s} {speed_unit}" for d, s in zip(tel1["Distance"], tel1[speed_col])],
            name=f"{driver1_name} Speed",
            showlegend=False
        ))

    # Optional Driver 2 line in comparison mode
    if tel2 is not None and not tel2.empty:
        fig.add_trace(go.Scatter(
            x=tel2["X"],
            y=tel2["Y"],
            mode="lines",
            line=dict(color=color2, width=2, dash="dot"),
            name=f"{driver2_name} Line",
            hoverinfo="skip",
            showlegend=True
        ))

    # 2. Corner / Turn Markers
    if corners_df is not None and not corners_df.empty:
        # Add corner number badges
        corner_x = corners_df["X"].tolist()
        corner_y = corners_df["Y"].tolist()
        corner_labels = [f"T{int(num)}" for num in corners_df["Number"]]

        fig.add_trace(go.Scatter(
            x=corner_x,
            y=corner_y,
            mode="markers+text",
            marker=dict(size=14, color="#1E293B", line=dict(color="#F8FAFC", width=1.5)),
            text=corner_labels,
            textposition="middle center",
            textfont=dict(size=8, color="#F8FAFC", family="Arial Black"),
            hoverinfo="text",
            hovertext=[f"Turn {num}" for num in corners_df["Number"]],
            name="Turns",
            showlegend=False
        ))

    # 3. Interactive Vehicle Cursor Marker(s)
    # Find closest row in tel1 to scrub_dist
    idx1 = (tel1["Distance"] - scrub_dist).abs().idxmin()
    car1 = tel1.loc[idx1]

    fig.add_trace(go.Scatter(
        x=[car1["X"]],
        y=[car1["Y"]],
        mode="markers+text",
        marker=dict(
            size=18,
            color=color1,
            symbol="diamond",
            line=dict(color="#FFFFFF", width=2)
        ),
        text=[f" 📍 {driver1_name} ({car1['Speed_kmh' if speed_unit == 'km/h' else 'Speed_mph']:.0f} {speed_unit})"],
        textposition="top right",
        textfont=dict(color="#FFFFFF", size=11, family="Arial Black"),
        hoverinfo="skip",
        name=f"📍 {driver1_name}",
        showlegend=False
    ))

    # If Driver 2 is present, plot car 2 at same scrub_dist
    if tel2 is not None and not tel2.empty:
        idx2 = (tel2["Distance"] - scrub_dist).abs().idxmin()
        car2 = tel2.loc[idx2]
        fig.add_trace(go.Scatter(
            x=[car2["X"]],
            y=[car2["Y"]],
            mode="markers+text",
            marker=dict(
                size=18,
                color=color2,
                symbol="circle",
                line=dict(color="#FFFFFF", width=2)
            ),
            text=[f" 📍 {driver2_name} ({car2['Speed_kmh' if speed_unit == 'km/h' else 'Speed_mph']:.0f} {speed_unit})"],
            textposition="bottom left",
            textfont=dict(color="#FFFFFF", size=11, family="Arial Black"),
            hoverinfo="skip",
            name=f"📍 {driver2_name}",
            showlegend=False
        ))

    # Circuit Layout Styling
    fig.update_layout(
        xaxis=dict(visible=False),
        yaxis=dict(visible=False, scaleanchor="x", scaleratio=1),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=10, r=10, t=10, b=10),
        height=520,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="center",
            x=0.5,
            font=dict(color="#E2E8F0")
        )
    )

    return fig


# --- 2. SYNCHRONIZED MULTI-ROW TELEMETRY TRACES ---

def create_telemetry_traces_figure(
    tel1: pd.DataFrame,
    tel2: Optional[pd.DataFrame] = None,
    delta_df: Optional[pd.DataFrame] = None,
    scrub_dist: float = 0.0,
    driver1_name: str = "Driver 1",
    driver2_name: str = "Driver 2",
    color1: str = "#00D2BE",
    color2: str = "#FF8000",
    speed_unit: str = "km/h"
) -> go.Figure:
    """
    Renders stacked synchronized telemetry charts vs Distance:
    - Row 1: Speed (km/h or mph)
    - Row 2: Delta Time (seconds) [only if comparison mode]
    - Row 3: Throttle & Brake (%)
    - Row 4: Gear (1-8)
    - Vertical line across all subplots indicating current scrubber position.
    """
    is_comparison = tel2 is not None and not tel2.empty and delta_df is not None and not delta_df.empty
    speed_col = "Speed_kmh" if speed_unit == "km/h" else "Speed_mph"

    if is_comparison:
        fig = make_subplots(
            rows=4,
            cols=1,
            shared_xaxes=True,
            vertical_spacing=0.04,
            row_heights=[0.38, 0.20, 0.24, 0.18],
            subplot_titles=[
                f"Speed ({speed_unit})",
                f"Delta Time (s) [▲ {driver1_name} Faster | ▼ {driver2_name} Faster]",
                "Throttle (%) & Brake (ON/OFF)",
                "Gear"
            ]
        )
    else:
        fig = make_subplots(
            rows=3,
            cols=1,
            shared_xaxes=True,
            vertical_spacing=0.05,
            row_heights=[0.50, 0.30, 0.20],
            subplot_titles=[
                f"Speed ({speed_unit})",
                "Throttle (%) & Brake (ON/OFF)",
                "Gear"
            ]
        )

    # --- ROW 1: SPEED ---
    fig.add_trace(
        go.Scatter(
            x=tel1["Distance"],
            y=tel1[speed_col],
            mode="lines",
            line=dict(color=color1, width=2.5),
            name=f"{driver1_name} Speed"
        ),
        row=1, col=1
    )

    if is_comparison:
        fig.add_trace(
            go.Scatter(
                x=tel2["Distance"],
                y=tel2[speed_col],
                mode="lines",
                line=dict(color=color2, width=2, dash="dash"),
                name=f"{driver2_name} Speed"
            ),
            row=1, col=1
        )

    # --- ROW 2: DELTA TIME (If Comparison) ---
    curr_row = 2
    if is_comparison:
        # Delta time trace with zero line
        fig.add_trace(
            go.Scatter(
                x=delta_df["Distance"],
                y=delta_df["DeltaTime"],
                mode="lines",
                line=dict(color="#CBD5E1", width=2),
                fill="tozeroy",
                fillcolor="rgba(148, 163, 184, 0.15)",
                name="Time Delta"
            ),
            row=curr_row, col=1
        )
        # Zero reference line
        fig.add_hline(y=0, line_width=1, line_dash="solid", line_color="rgba(255,255,255,0.3)", row=curr_row, col=1)
        curr_row += 1

    # --- ROW: THROTTLE & BRAKE ---
    # Driver 1 Throttle & Brake
    fig.add_trace(
        go.Scatter(
            x=tel1["Distance"],
            y=tel1["Throttle"],
            mode="lines",
            line=dict(color=color1, width=2),
            name=f"{driver1_name} Throttle %"
        ),
        row=curr_row, col=1
    )
    fig.add_trace(
        go.Scatter(
            x=tel1["Distance"],
            y=tel1["Brake"] * 100,
            mode="lines",
            line=dict(color="#EF4444", width=2),
            fill="tozeroy",
            fillcolor="rgba(239, 68, 68, 0.2)",
            name=f"{driver1_name} Brake"
        ),
        row=curr_row, col=1
    )

    if is_comparison:
        fig.add_trace(
            go.Scatter(
                x=tel2["Distance"],
                y=tel2["Throttle"],
                mode="lines",
                line=dict(color=color2, width=1.5, dash="dot"),
                name=f"{driver2_name} Throttle %"
            ),
            row=curr_row, col=1
        )
        fig.add_trace(
            go.Scatter(
                x=tel2["Distance"],
                y=tel2["Brake"] * 100,
                mode="lines",
                line=dict(color="#DC2626", width=1.5, dash="dot"),
                name=f"{driver2_name} Brake"
            ),
            row=curr_row, col=1
        )
    curr_row += 1

    # --- ROW: GEAR ---
    fig.add_trace(
        go.Scatter(
            x=tel1["Distance"],
            y=tel1["nGear"],
            mode="lines",
            line=dict(color=color1, width=2),
            name=f"{driver1_name} Gear"
        ),
        row=curr_row, col=1
    )
    if is_comparison:
        fig.add_trace(
            go.Scatter(
                x=tel2["Distance"],
                y=tel2["nGear"],
                mode="lines",
                line=dict(color=color2, width=1.5, dash="dash"),
                name=f"{driver2_name} Gear"
            ),
            row=curr_row, col=1
        )

    # --- SYNCHRONIZED SCRUBBER VERTICAL LINE ---
    # Add vertical line at scrub_dist across all subplots
    total_rows = 4 if is_comparison else 3
    for r in range(1, total_rows + 1):
        fig.add_vline(
            x=scrub_dist,
            line_width=1.5,
            line_dash="dash",
            line_color="#F8FAFC",
            row=r, col=1
        )

    fig.update_layout(
        hovermode="x unified",
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=10, r=10, t=30, b=10),
        height=580,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="center",
            x=0.5,
            font=dict(color="#E2E8F0", size=10)
        )
    )

    # Axis formatting
    fig.update_xaxes(title_text="Lap Distance (meters)", row=total_rows, col=1)
    fig.update_yaxes(showgrid=True, gridcolor="rgba(255,255,255,0.08)")
    fig.update_xaxes(showgrid=True, gridcolor="rgba(255,255,255,0.08)")

    return fig


# --- 3. INSTANTANEOUS SCRUB METRICS ---

def get_scrubber_instant_metrics(
    tel1: pd.DataFrame,
    tel2: Optional[pd.DataFrame] = None,
    scrub_dist: float = 0.0,
    speed_unit: str = "km/h"
) -> Dict[str, Any]:
    """
    Extracts instantaneous metrics at scrub_dist for Driver 1 and optional Driver 2.
    """
    metrics = {"driver1": {}, "driver2": {}}
    if tel1 is None or tel1.empty:
        return metrics

    speed_col = "Speed_kmh" if speed_unit == "km/h" else "Speed_mph"

    idx1 = (tel1["Distance"] - scrub_dist).abs().idxmin()
    row1 = tel1.loc[idx1]

    metrics["driver1"] = {
        "speed": f"{row1[speed_col]:.0f} {speed_unit}",
        "throttle": f"{row1['Throttle']:.0f}%",
        "brake": "ON 🔴" if row1["Brake"] > 0 else "OFF ⚪",
        "state": STATE_NAMES.get(row1["DrivingState"], "Unknown"),
        "state_code": row1["DrivingState"],
        "gear": f"Gear {row1['nGear']}",
        "rpm": f"{row1['RPM']} RPM",
        "distance": f"{row1['Distance']:.0f} m",
        "lap_time": f"{row1['LapTime']:.2f} s",
        "track_temp": f"{row1['TrackTemp']:.1f}°C ({row1['TrackTemp'] * 9/5 + 32:.1f}°F)",
        "compound": row1.get("Compound", "UNKNOWN"),
        "tyre_life": f"{row1.get('TyreLife', 0)} laps"
    }

    if tel2 is not None and not tel2.empty:
        idx2 = (tel2["Distance"] - scrub_dist).abs().idxmin()
        row2 = tel2.loc[idx2]
        metrics["driver2"] = {
            "speed": f"{row2[speed_col]:.0f} {speed_unit}",
            "throttle": f"{row2['Throttle']:.0f}%",
            "brake": "ON 🔴" if row2["Brake"] > 0 else "OFF ⚪",
            "state": STATE_NAMES.get(row2["DrivingState"], "Unknown"),
            "state_code": row2["DrivingState"],
            "gear": f"Gear {row2['nGear']}",
            "rpm": f"{row2['RPM']} RPM",
            "distance": f"{row2['Distance']:.0f} m",
            "lap_time": f"{row2['LapTime']:.2f} s",
            "track_temp": f"{row2['TrackTemp']:.1f}°C ({row2['TrackTemp'] * 9/5 + 32:.1f}°F)",
            "compound": row2.get("Compound", "UNKNOWN"),
            "tyre_life": f"{row2.get('TyreLife', 0)} laps"
        }

    return metrics


# --- 4. CORNER-BY-CORNER APEX ANALYSIS ---

def compute_corner_breakdown(
    corners_df: pd.DataFrame,
    tel1: pd.DataFrame,
    tel2: Optional[pd.DataFrame] = None,
    driver1_name: str = "Driver 1",
    driver2_name: str = "Driver 2",
    speed_unit: str = "km/h"
) -> pd.DataFrame:
    """
    Computes corner-by-corner apex analysis:
    - Minimum apex speed (km/h or mph)
    - Minimum speed apex distance
    - Gear at apex
    - Speed delta (Driver 1 vs Driver 2)
    """
    if corners_df is None or corners_df.empty or tel1 is None or tel1.empty:
        return pd.DataFrame()

    speed_col = "Speed_kmh" if speed_unit == "km/h" else "Speed_mph"
    rows = []

    for _, c_row in corners_df.iterrows():
        c_num = int(c_row["Number"])
        c_dist = float(c_row["Distance"])
        
        # Search window +/- 120m around official corner apex distance
        w1 = tel1[(tel1["Distance"] >= c_dist - 120) & (tel1["Distance"] <= c_dist + 120)]
        if w1.empty:
            continue
            
        min_idx1 = w1[speed_col].idxmin()
        apex1 = w1.loc[min_idx1]
        
        entry_spd1 = w1[speed_col].iloc[0]
        apex_spd1 = apex1[speed_col]
        apex_gear1 = int(apex1["nGear"])

        row_data = {
            "Corner": f"Turn {c_num}",
            "Apex Dist (m)": int(apex1["Distance"]),
            f"{driver1_name} Apex Speed": f"{apex_spd1:.1f} {speed_unit}",
            f"{driver1_name} Gear": apex_gear1
        }

        if tel2 is not None and not tel2.empty:
            w2 = tel2[(tel2["Distance"] >= c_dist - 120) & (tel2["Distance"] <= c_dist + 120)]
            if not w2.empty:
                min_idx2 = w2[speed_col].idxmin()
                apex2 = w2.loc[min_idx2]
                apex_spd2 = apex2[speed_col]
                row_data[f"{driver2_name} Apex Speed"] = f"{apex_spd2:.1f} {speed_unit}"
                row_data[f"{driver2_name} Gear"] = int(apex2["nGear"])
                
                delta = apex_spd1 - apex_spd2
                sign = "+" if delta > 0 else ""
                row_data["Speed Delta"] = f"{sign}{delta:.1f} {speed_unit}"

        rows.append(row_data)

    return pd.DataFrame(rows)
