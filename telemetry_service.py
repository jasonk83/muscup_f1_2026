"""
telemetry_service.py
Core telemetry service for week-by-week F1 data extraction, lap processing,
driving-state classification, circuit geometry, and head-to-head comparison.
Powered by FastF1 with local caching and OpenF1 REST fallback support.
"""

import os
import sys
import logging
import numpy as np

# NumPy 2.0+ compatibility patch for FastF1
for _alias, _target in [("NaN", np.nan), ("Inf", np.inf), ("PINF", np.inf), ("NINF", -np.inf)]:
    if not hasattr(np, _alias):
        setattr(np, _alias, _target)

import fastf1
from fastf1 import plotting, utils
import pandas as pd
import requests
from typing import Dict, List, Optional, Tuple, Any

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("telemetry_service")

# Setup local FastF1 cache directory
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fastf1_cache")
os.makedirs(CACHE_DIR, exist_ok=True)
try:
    fastf1.Cache.enable_cache(CACHE_DIR)
    logger.info(f"FastF1 cache enabled at: {CACHE_DIR}")
except Exception as e:
    logger.warning(f"Could not enable FastF1 cache: {e}")

# Default F1 Team Colors fallback
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

TYRE_COLORS = {
    "SOFT": "#FF3333",        # Red
    "MEDIUM": "#FFF200",      # Yellow
    "HARD": "#FFFFFF",        # White
    "INTERMEDIATE": "#39B54A",# Green
    "WET": "#00AEEF",         # Blue
    "UNKNOWN": "#A0A0A0"
}


# --- CALENDAR & SCHEDULE ---

def get_available_seasons() -> List[int]:
    """Returns supported seasons for exploration (from current 2026 back to 2023)."""
    return [2026, 2025, 2024, 2023]


def get_season_schedule(year: int) -> pd.DataFrame:
    """
    Fetches the event schedule for the requested year using FastF1.
    Returns a clean DataFrame with EventName, RoundNumber, Country, Location, EventDate.
    """
    try:
        schedule = fastf1.get_event_schedule(year, include_testing=False)
        # Filter valid rounds
        valid_events = schedule[schedule["RoundNumber"] > 0].copy()
        valid_events["RoundNumber"] = valid_events["RoundNumber"].astype(int)
        valid_events["DisplayName"] = valid_events.apply(
            lambda row: f"Round {row['RoundNumber']}: {row['EventName']} ({row['Location']})",
            axis=1
        )
        return valid_events
    except Exception as e:
        logger.error(f"Error fetching schedule for {year}: {e}")
        return pd.DataFrame()


# --- SESSION LOADER ---

def load_session(year: int, round_id: int | str, session_type: str = "R") -> Optional[fastf1.core.Session]:
    """
    Loads an F1 session with telemetry and weather data.
    session_type: 'R' (Race), 'Q' (Qualifying), 'FP1', 'FP2', 'FP3', 'S' (Sprint), 'SQ' (Sprint Shootout)
    """
    try:
        session = fastf1.get_session(year, round_id, session_type)
        session.load(telemetry=True, weather=True, messages=False)
        return session
    except Exception as e:
        logger.warning(f"Session data not available or failed to load for {year} Round {round_id} [{session_type}]: {e}")
        return None


# --- DRIVER & LAP RESOLUTION ---

def get_session_drivers(session: fastf1.core.Session) -> Dict[str, Dict[str, Any]]:
    """
    Returns a dictionary of drivers in the session mapped by abbreviation (e.g. 'VER', 'NOR').
    Contains code, number, full name, team name, and team color.
    """
    drivers_dict = {}
    if session is None or session.results is None or session.results.empty:
        return drivers_dict

    for _, row in session.results.iterrows():
        code = str(row.get("Abbreviation", "")).strip()
        if not code or code == "nan":
            continue
            
        team_name = str(row.get("TeamName", "Unknown Team"))
        # Resolve team color via fastf1.plotting or our fallback dictionary
        try:
            team_color = plotting.get_team_color(team_name, session)
        except:
            team_color = TEAM_COLORS.get(team_name, "#7F7F7F")
            
        full_name = str(row.get("FullName", code))
        number = str(row.get("DriverNumber", ""))
        position = row.get("Position", None)
        
        drivers_dict[code] = {
            "code": code,
            "number": number,
            "name": full_name,
            "team": team_name,
            "color": team_color,
            "position": int(position) if pd.notna(position) and str(position).isdigit() else position
        }
        
    return drivers_dict


def get_driver_laps_summary(session: fastf1.core.Session, driver_code: str) -> pd.DataFrame:
    """
    Retrieves all valid laps for a driver with key timing, compound, and stint info.
    """
    if session is None or session.laps is None or session.laps.empty:
        return pd.DataFrame()
        
    driver_laps = session.laps.pick_drivers(driver_code)
    if driver_laps.empty:
        return pd.DataFrame()

    fastest_lap_num = None
    try:
        fastest_lap = driver_laps.pick_fastest()
        if fastest_lap is not None and pd.notna(fastest_lap["LapNumber"]):
            fastest_lap_num = int(fastest_lap["LapNumber"])
    except:
        pass

    records = []
    for _, lap in driver_laps.iterlaps():
        lap_num = int(lap["LapNumber"])
        lap_time = lap["LapTime"]
        
        # Format lap time string (e.g. "1:23.456")
        time_str = "No Time"
        time_sec = None
        if pd.notna(lap_time):
            total_sec = lap_time.total_seconds()
            time_sec = round(total_sec, 3)
            mins = int(total_sec // 60)
            secs = total_sec % 60
            time_str = f"{mins}:{secs:06.3f}"
            
        compound = str(lap.get("Compound", "UNKNOWN")).upper()
        tyre_life = int(lap.get("TyreLife", 0)) if pd.notna(lap.get("TyreLife")) else 0
        stint = int(lap.get("Stint", 1)) if pd.notna(lap.get("Stint")) else 1
        is_pit_out = bool(lap.get("PitOutTime") is not pd.NaT and pd.notna(lap.get("PitOutTime")))
        is_pit_in = bool(lap.get("PitInTime") is not pd.NaT and pd.notna(lap.get("PitInTime")))
        is_deleted = bool(lap.get("Deleted", False))

        label = f"Lap {lap_num} ({time_str})"
        if lap_num == fastest_lap_num:
            label += " 🟣 Fastest"
        if compound != "UNKNOWN":
            label += f" [{compound} - L{tyre_life}]"

        records.append({
            "LapNumber": lap_num,
            "LapTimeStr": time_str,
            "LapTimeSec": time_sec,
            "Compound": compound,
            "TyreLife": tyre_life,
            "Stint": stint,
            "IsFastest": (lap_num == fastest_lap_num),
            "IsPitOut": is_pit_out,
            "IsPitIn": is_pit_in,
            "IsDeleted": is_deleted,
            "DisplayLabel": label
        })
        
    return pd.DataFrame(records)


# --- TELEMETRY EXTRACTION & DRIVING STATE CLASSIFICATION ---

def extract_lap_telemetry(lap: fastf1.core.Lap, session: Optional[fastf1.core.Session] = None) -> pd.DataFrame:
    """
    Extracts high-resolution synchronized telemetry from a FastF1 lap and computes:
    - Distance (m), Time (s), Speed (km/h & mph)
    - Throttle (0-100), Brake (0-1), Gear (1-8), RPM
    - X, Y, Z coordinates
    - Driving State:
        1 = Accelerating (Green): Throttle > 25 and Brake == 0
        2 = Coasting (Amber): Throttle <= 25 and Brake == 0
        3 = Braking (Red): Brake > 0
    - Track & Air Temperature (°C) interpolated from session weather
    """
    try:
        tel = lap.get_telemetry()
    except Exception as e:
        logger.error(f"Failed to get telemetry for lap: {e}")
        return pd.DataFrame()

    if tel.empty:
        return pd.DataFrame()

    df = pd.DataFrame()
    df["Distance"] = tel["Distance"].round(1)
    df["Time"] = tel["Time"].dt.total_seconds().round(3)
    
    # Calculate Relative Time from start of lap (0.0 to LapTime)
    df["LapTime"] = (df["Time"] - df["Time"].iloc[0]).round(3)
    
    df["Speed_kmh"] = tel["Speed"].round(1)
    df["Speed_mph"] = (tel["Speed"] * 0.621371).round(1)
    df["Throttle"] = tel["Throttle"].round(1)
    df["Brake"] = tel["Brake"].astype(int)
    df["nGear"] = tel["nGear"].astype(int)
    df["RPM"] = tel["RPM"].astype(int) if "RPM" in tel.columns else 0
    df["DRS"] = tel["DRS"].astype(int) if "DRS" in tel.columns else 0
    df["X"] = tel["X"].round(1)
    df["Y"] = tel["Y"].round(1)
    df["Z"] = tel["Z"].round(1) if "Z" in tel.columns else 0

    # Driving State Classification
    # 1: Accelerating, 2: Coasting, 3: Braking
    def classify_state(row):
        if row["Brake"] > 0:
            return 3  # Braking
        elif row["Throttle"] > 25:
            return 1  # Accelerating
        else:
            return 2  # Coasting

    df["DrivingState"] = df.apply(classify_state, axis=1)

    # Weather & Track Temperature Interpolation
    if session is not None and hasattr(session, "weather_data") and session.weather_data is not None and not session.weather_data.empty:
        try:
            weather_df = session.weather_data
            # Convert Time to seconds
            weather_df_time = weather_df["Time"].dt.total_seconds()
            
            # Interpolate TrackTemperature and AirTemperature
            df["TrackTemp"] = np.interp(df["Time"], weather_df_time, weather_df["TrackTemperature"]).round(1)
            df["AirTemp"] = np.interp(df["Time"], weather_df_time, weather_df["AirTemperature"]).round(1)
        except Exception as e:
            df["TrackTemp"] = round(float(session.weather_data["TrackTemperature"].mean()), 1)
            df["AirTemp"] = round(float(session.weather_data["AirTemperature"].mean()), 1)
    else:
        df["TrackTemp"] = 35.0  # Reasonable default if weather unrecorded
        df["AirTemp"] = 25.0

    # Attach Lap Metadata
    df["Compound"] = str(lap.get("Compound", "UNKNOWN")).upper()
    df["TyreLife"] = int(lap.get("TyreLife", 0)) if pd.notna(lap.get("TyreLife")) else 0
    df["LapNumber"] = int(lap["LapNumber"])
    df["Driver"] = str(lap.get("Driver", ""))

    return df


# --- CIRCUIT GEOMETRY & CORNERS ---

def get_circuit_layout_and_corners(session: fastf1.core.Session) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Extracts official circuit corner annotations and track bounds.
    Returns:
    - corners_df: DataFrame with Number, Letter, Distance, X, Y, Angle
    - reference_track: DataFrame with reference X, Y coordinates
    """
    corners_df = pd.DataFrame()
    ref_track = pd.DataFrame()

    if session is None:
        return corners_df, ref_track

    # Extract circuit info
    try:
        circuit_info = session.get_circuit_info()
        if circuit_info is not None and circuit_info.corners is not None and not circuit_info.corners.empty:
            corners_df = circuit_info.corners.copy()
            # Rotation angle if track needs rotating
            corners_df["Angle"] = circuit_info.rotation
    except Exception as e:
        logger.info(f"Circuit info corners not directly provided by FastF1 for session: {e}")

    # Reference track from fastest lap
    try:
        fastest_lap = session.laps.pick_fastest()
        if fastest_lap is not None:
            tel = fastest_lap.get_telemetry()
            ref_track = pd.DataFrame({"X": tel["X"], "Y": tel["Y"], "Distance": tel["Distance"]})
    except:
        pass

    return corners_df, ref_track


# --- DUAL-DRIVER COMPARISON & DELTA CALCULATION ---

def compute_head_to_head_telemetry(
    lap1: fastf1.core.Lap,
    lap2: fastf1.core.Lap,
    session: Optional[fastf1.core.Session] = None
) -> Dict[str, Any]:
    """
    Computes synchronized head-to-head telemetry and instantaneous Delta Time
    between Driver 1 (reference) and Driver 2 (comparison).
    Delta Time > 0 means Driver 1 is slower (Driver 2 is ahead).
    Delta Time < 0 means Driver 1 is faster (Driver 1 is ahead).
    """
    tel1 = extract_lap_telemetry(lap1, session)
    tel2 = extract_lap_telemetry(lap2, session)

    if tel1.empty or tel2.empty:
        return {"error": "Telemetry missing for one or both laps"}

    # Calculate Delta Time via FastF1 utils or distance interpolation
    try:
        delta_series, ref_tel, comp_tel = utils.delta_time(lap1, lap2)
        # Re-align on reference distance
        delta_df = pd.DataFrame({
            "Distance": ref_tel["Distance"].round(1),
            "DeltaTime": delta_series.round(3)
        })
    except Exception as e:
        logger.warning(f"FastF1 delta_time calculation failed, computing fallback interpolation: {e}")
        # Fallback: Resample both onto uniform distance grid
        max_dist = min(tel1["Distance"].max(), tel2["Distance"].max())
        common_dist = np.linspace(0, max_dist, num=min(len(tel1), len(tel2)))
        t1_interp = np.interp(common_dist, tel1["Distance"], tel1["LapTime"])
        t2_interp = np.interp(common_dist, tel2["Distance"], tel2["LapTime"])
        delta_df = pd.DataFrame({
            "Distance": common_dist.round(1),
            "DeltaTime": (t1_interp - t2_interp).round(3)
        })

    return {
        "tel1": tel1,
        "tel2": tel2,
        "delta": delta_df,
        "lap1_meta": {
            "driver": str(lap1.get("Driver", "Driver 1")),
            "lap_number": int(lap1["LapNumber"]),
            "time_str": str(lap1["LapTime"]).split("days ")[-1][:12] if pd.notna(lap1["LapTime"]) else "N/A",
            "compound": str(lap1.get("Compound", "UNKNOWN")).upper(),
            "tyre_life": int(lap1.get("TyreLife", 0)) if pd.notna(lap1.get("TyreLife")) else 0
        },
        "lap2_meta": {
            "driver": str(lap2.get("Driver", "Driver 2")),
            "lap_number": int(lap2["LapNumber"]),
            "time_str": str(lap2["LapTime"]).split("days ")[-1][:12] if pd.notna(lap2["LapTime"]) else "N/A",
            "compound": str(lap2.get("Compound", "UNKNOWN")).upper(),
            "tyre_life": int(lap2.get("TyreLife", 0)) if pd.notna(lap2.get("TyreLife")) else 0
        }
    }


# --- OPENF1 REST API CLIENT (FALLBACK & SUPPLEMENTAL) ---

class OpenF1Client:
    """Lightweight REST client for OpenF1 API (https://api.openf1.org/v1)."""
    BASE_URL = "https://api.openf1.org/v1"

    @classmethod
    def get_sessions(cls, year: int) -> List[Dict[str, Any]]:
        try:
            res = requests.get(f"{cls.BASE_URL}/sessions?year={year}", timeout=5)
            if res.status_code == 200:
                return res.json()
        except Exception as e:
            logger.warning(f"OpenF1 get_sessions error: {e}")
        return []

    @classmethod
    def get_weather(cls, session_key: int) -> List[Dict[str, Any]]:
        try:
            res = requests.get(f"{cls.BASE_URL}/weather?session_key={session_key}", timeout=5)
            if res.status_code == 200:
                return res.json()
        except Exception as e:
            logger.warning(f"OpenF1 get_weather error: {e}")
        return []

    @classmethod
    def get_car_telemetry(cls, session_key: int, driver_number: int) -> List[Dict[str, Any]]:
        try:
            res = requests.get(
                f"{cls.BASE_URL}/car_data?session_key={session_key}&driver_number={driver_number}",
                timeout=8
            )
            if res.status_code == 200:
                return res.json()
        except Exception as e:
            logger.warning(f"OpenF1 get_car_telemetry error: {e}")
        return []
