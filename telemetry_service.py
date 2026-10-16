"""
telemetry_service.py
Hybrid F1 Telemetry Service:
- Seamlessly uses OpenF1 REST API for 2026 season (which contains all active 2026 telemetry,
  drivers, lap times, speeds, throttle, brake, track temperatures, and tyre compounds).
- Uses FastF1 with local caching for historical seasons (2023-2025) with automatic OpenF1 fallback.
- Classifies driving states: Accelerating (1), Coasting (2), Braking (3).
- Computes synchronized head-to-head delta times and corner apex speeds.
"""

import os
import sys
import logging
import requests
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple, Any

# NumPy 2.0+ compatibility patch for FastF1
for _alias, _target in [("NaN", np.nan), ("Inf", np.inf), ("PINF", np.inf), ("NINF", -np.inf)]:
    if not hasattr(np, _alias):
        setattr(np, _alias, _target)

import fastf1
from fastf1 import plotting, utils
from scipy.signal import find_peaks

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("telemetry_service")

# Setup local FastF1 cache directory
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fastf1_cache")
os.makedirs(CACHE_DIR, exist_ok=True)
try:
    fastf1.Cache.enable_cache(CACHE_DIR)
except Exception as e:
    logger.warning(f"Could not enable FastF1 cache: {e}")

OPENF1_BASE = "https://api.openf1.org/v1"

# F1 Team Colors
TEAM_COLORS = {
    "Mercedes": "#00D2BE",
    "McLaren": "#FF8000",
    "Ferrari": "#DC0000",
    "Red Bull Racing": "#3671C6",
    "Red Bull": "#3671C6",
    "Williams": "#005AFF",
    "Alpine": "#FF87BC",
    "Alpine F1 Team": "#FF87BC",
    "Haas F1 Team": "#E6002B",
    "Haas": "#E6002B",
    "Kick Sauber": "#00E701",
    "Sauber": "#00E701",
    "Audi": "#00E701",
    "Aston Martin": "#229971",
    "RB": "#6692FF",
    "RB F1 Team": "#6692FF",
    "Racing Bulls": "#6692FF",
    "Cadillac": "#FFB81C",
    "Cadillac F1 Team": "#FFB81C"
}


# --- OPENF1 SESSION ADAPTER ---

class OpenF1Session:
    """Wrapper that represents an OpenF1 session and provides identical interface to FastF1."""
    def __init__(self, session_key: int, event_name: str, year: int, round_number: int, session_type: str = "Race"):
        self.session_key = session_key
        self.name = event_name
        self.year = year
        self.round_number = round_number
        self.session_type = session_type
        self.is_openf1 = True
        self.drivers = {}
        self.stints = {}
        self.weather_track_temp = 35.0
        self.weather_air_temp = 25.0
        self._laps_cache = {}
        self._load_metadata()

    def _load_metadata(self):
        # 1. Weather
        try:
            w_res = requests.get(f"{OPENF1_BASE}/weather?session_key={self.session_key}", timeout=6).json()
            if w_res and isinstance(w_res, list):
                w_df = pd.DataFrame(w_res)
                if "track_temperature" in w_df.columns:
                    self.weather_track_temp = round(float(w_df["track_temperature"].mean()), 1)
                if "air_temperature" in w_df.columns:
                    self.weather_air_temp = round(float(w_df["air_temperature"].mean()), 1)
        except Exception as e:
            logger.warning(f"Could not load OpenF1 weather: {e}")

        # 2. Drivers
        try:
            d_res = requests.get(f"{OPENF1_BASE}/drivers?session_key={self.session_key}", timeout=6).json()
            if d_res and isinstance(d_res, list):
                for d in d_res:
                    num = int(d["driver_number"])
                    code = str(d.get("name_acronym", f"D{num}")).strip().upper()
                    team = str(d.get("team_name", "Unknown Team"))
                    team_color = d.get("team_colour")
                    if team_color:
                        team_color = f"#{team_color.lstrip('#')}"
                    else:
                        team_color = TEAM_COLORS.get(team, "#7F7F7F")

                    self.drivers[code] = {
                        "code": code,
                        "number": num,
                        "name": str(d.get("full_name", code)),
                        "team": team,
                        "color": team_color,
                        "position": None
                    }
        except Exception as e:
            logger.warning(f"Could not load OpenF1 drivers: {e}")

        # 3. Stints
        try:
            st_res = requests.get(f"{OPENF1_BASE}/stints?session_key={self.session_key}", timeout=6).json()
            if st_res and isinstance(st_res, list):
                for st in st_res:
                    drv_num = int(st["driver_number"])
                    self.stints.setdefault(drv_num, []).append(st)
        except Exception as e:
            logger.warning(f"Could not load OpenF1 stints: {e}")


# --- CALENDAR & SCHEDULE ---

def get_available_seasons() -> List[int]:
    """Returns supported seasons (2026, 2025, 2024, 2023)."""
    return [2026, 2025, 2024, 2023]


def get_season_schedule(year: int) -> pd.DataFrame:
    """
    Fetches the championship schedule for the requested year.
    For 2026, extracts complete calendar from OpenF1.
    For 2023-2025, uses FastF1 with OpenF1 fallback.
    """
    if year == 2026:
        # Load from OpenF1
        try:
            res = requests.get(f"{OPENF1_BASE}/sessions?year=2026", timeout=8).json()
            if res and isinstance(res, list):
                races = [s for s in res if s.get("session_type") == "Race" and not s.get("is_cancelled", False)]
                # Sort by date
                races = sorted(races, key=lambda s: s.get("date_start", ""))
                
                records = []
                seen_meetings = set()
                round_num = 1
                for r in races:
                    m_key = r.get("meeting_key", r.get("session_key"))
                    if m_key in seen_meetings:
                        continue
                    seen_meetings.add(m_key)
                    
                    c_name = r.get("country_name", "Grand Prix")
                    loc = r.get("location", "")
                    event_name = f"{c_name} Grand Prix"
                    records.append({
                        "RoundNumber": round_num,
                        "EventName": event_name,
                        "Country": c_name,
                        "Location": loc,
                        "EventDate": r.get("date_start", "")[:10],
                        "DisplayName": f"Round {round_num}: {event_name} ({loc})",
                        "session_key": r.get("session_key")
                    })
                    round_num += 1
                if records:
                    return pd.DataFrame(records)
        except Exception as e:
            logger.warning(f"OpenF1 2026 schedule query error: {e}")

    # Historical FastF1 schedule
    try:
        schedule = fastf1.get_event_schedule(year, include_testing=False)
        valid_events = schedule[schedule["RoundNumber"] > 0].copy()
        valid_events["RoundNumber"] = valid_events["RoundNumber"].astype(int)
        valid_events["DisplayName"] = valid_events.apply(
            lambda row: f"Round {row['RoundNumber']}: {row['EventName']} ({row['Location']})",
            axis=1
        )
        return valid_events
    except Exception as e:
        logger.error(f"Error fetching FastF1 schedule for {year}: {e}")
        return pd.DataFrame()


# --- SESSION LOADER ---

def load_session(year: int, round_id: int | str, session_type: str = "R") -> Optional[Any]:
    """
    Loads telemetry session. Automatically uses OpenF1 for 2026 or whenever FastF1 has no telemetry.
    """
    # 2026 Season -> OpenF1 Direct
    if year == 2026:
        try:
            sched = get_season_schedule(2026)
            match = sched[sched["RoundNumber"] == int(round_id)]
            if not match.empty:
                s_key = int(match["session_key"].values[0])
                ev_name = str(match["EventName"].values[0])
                return OpenF1Session(s_key, ev_name, year, int(round_id), "Race")
        except Exception as e:
            logger.error(f"Failed to load OpenF1 2026 session: {e}")

    # Historical Seasons -> FastF1 with OpenF1 fallback
    try:
        session = fastf1.get_session(year, round_id, session_type)
        session.load(telemetry=True, weather=True, messages=False)
        if hasattr(session, "laps") and not session.laps.empty:
            return session
    except Exception as e:
        logger.warning(f"FastF1 load failed for {year} Round {round_id}: {e}")

    # Fallback to OpenF1 for historical if FastF1 fails
    try:
        res = requests.get(f"{OPENF1_BASE}/sessions?year={year}", timeout=6).json()
        if res and isinstance(res, list):
            races = [s for s in res if s.get("session_type") == "Race" and not s.get("is_cancelled", False)]
            races = sorted(races, key=lambda s: s.get("date_start", ""))
            idx = int(round_id) - 1
            if 0 <= idx < len(races):
                s_info = races[idx]
                return OpenF1Session(
                    s_info["session_key"],
                    f"{s_info.get('country_name', '')} Grand Prix",
                    year, int(round_id), "Race"
                )
    except Exception as e:
        logger.warning(f"OpenF1 fallback load failed: {e}")

    return None


# --- DRIVER & LAP RESOLUTION ---

def get_session_drivers(session: Any) -> Dict[str, Dict[str, Any]]:
    """Returns drivers dictionary mapped by code."""
    if session is None:
        return {}

    # OpenF1 Session
    if getattr(session, "is_openf1", False):
        return session.drivers

    # FastF1 Session
    drivers_dict = {}
    if session.results is None or session.results.empty:
        return drivers_dict

    for _, row in session.results.iterrows():
        code = str(row.get("Abbreviation", "")).strip()
        if not code or code == "nan":
            continue
        team_name = str(row.get("TeamName", "Unknown Team"))
        try:
            team_color = plotting.get_team_color(team_name, session)
        except:
            team_color = TEAM_COLORS.get(team_name, "#7F7F7F")

        drivers_dict[code] = {
            "code": code,
            "number": str(row.get("DriverNumber", "")),
            "name": str(row.get("FullName", code)),
            "team": team_name,
            "color": team_color,
            "position": row.get("Position", None)
        }
    return drivers_dict


def get_driver_laps_summary(session: Any, driver_code: str) -> pd.DataFrame:
    """Returns summary of laps with lap number, time, compound, and stint info."""
    if session is None:
        return pd.DataFrame()

    # OpenF1 Session
    if getattr(session, "is_openf1", False):
        drv_info = session.drivers.get(driver_code)
        if not drv_info:
            return pd.DataFrame()
        drv_num = drv_info["number"]
        try:
            url = f"{OPENF1_BASE}/laps?session_key={session.session_key}&driver_number={drv_num}"
            laps_raw = requests.get(url, timeout=8).json()
            if not laps_raw or not isinstance(laps_raw, list):
                return pd.DataFrame()

            laps_raw = sorted(laps_raw, key=lambda x: x.get("lap_number", 0))
            drv_stints = session.stints.get(drv_num, [])

            valid_laps = [l for l in laps_raw if l.get("lap_duration") and not l.get("is_pit_out_lap")]
            fastest_lap_num = min(valid_laps, key=lambda x: x["lap_duration"])["lap_number"] if valid_laps else None

            records = []
            for lap in laps_raw:
                lap_num = int(lap.get("lap_number", 0))
                dur = lap.get("lap_duration")
                if dur:
                    dur_sec = round(float(dur), 3)
                    mins = int(dur_sec // 60)
                    secs = dur_sec % 60
                    time_str = f"{mins}:{secs:06.3f}"
                else:
                    dur_sec = None
                    time_str = "No Time"

                compound = "UNKNOWN"
                tyre_life = 0
                stint_idx = 1
                for s in drv_stints:
                    l_start = s.get("lap_start", 1)
                    l_end = s.get("lap_end", 999)
                    if l_start <= lap_num <= l_end:
                        compound = str(s.get("compound", "UNKNOWN")).upper()
                        age_start = s.get("tyre_age_at_start", 0) or 0
                        tyre_life = age_start + (lap_num - l_start)
                        stint_idx = s.get("stint_number", 1)
                        break

                is_fastest = (lap_num == fastest_lap_num)
                label = f"Lap {lap_num} ({time_str})"
                if is_fastest:
                    label += " 🟣 Fastest"
                if compound != "UNKNOWN":
                    label += f" [{compound} - L{tyre_life}]"

                records.append({
                    "LapNumber": lap_num,
                    "LapTimeStr": time_str,
                    "LapTimeSec": dur_sec,
                    "Compound": compound,
                    "TyreLife": tyre_life,
                    "Stint": stint_idx,
                    "IsFastest": is_fastest,
                    "IsPitOut": bool(lap.get("is_pit_out_lap", False)),
                    "IsPitIn": False,
                    "IsDeleted": False,
                    "DisplayLabel": label
                })
            return pd.DataFrame(records)
        except Exception as e:
            logger.error(f"Error getting OpenF1 laps for {driver_code}: {e}")
            return pd.DataFrame()

    # FastF1 Session
    if session.laps is None or session.laps.empty:
        return pd.DataFrame()
    driver_laps = session.laps.pick_drivers(driver_code)
    if driver_laps.empty:
        return pd.DataFrame()

    fastest_lap_num = None
    try:
        fl = driver_laps.pick_fastest()
        if fl is not None and pd.notna(fl["LapNumber"]):
            fastest_lap_num = int(fl["LapNumber"])
    except:
        pass

    records = []
    for _, lap in driver_laps.iterlaps():
        lap_num = int(lap["LapNumber"])
        lap_time = lap["LapTime"]
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
            "DisplayLabel": label
        })
    return pd.DataFrame(records)


# --- TELEMETRY EXTRACTION ---

def extract_lap_telemetry(lap_obj_or_spec: Any, session: Any, driver_code: Optional[str] = None, lap_number: Optional[int] = None) -> pd.DataFrame:
    """
    Extracts synchronized telemetry from OpenF1 or FastF1:
    - Distance, Time, Speed (km/h & mph), Throttle, Brake, Gear, RPM
    - Driving State: Accelerating (1), Coasting (2), Braking (3)
    - Track & Air Temperature (°C)
    """
    # OpenF1 Session Extraction
    if getattr(session, "is_openf1", False):
        if isinstance(lap_obj_or_spec, dict):
            drv_code = lap_obj_or_spec.get("driver", driver_code)
            l_num = lap_obj_or_spec.get("lap", lap_number)
        else:
            drv_code = driver_code
            l_num = lap_number

        drv_info = session.drivers.get(drv_code)
        if not drv_info:
            return pd.DataFrame()
        drv_num = drv_info["number"]

        try:
            laps_raw = requests.get(f"{OPENF1_BASE}/laps?session_key={session.session_key}&driver_number={drv_num}", timeout=8).json()
            curr_lap = next((l for l in laps_raw if l.get("lap_number") == l_num), None)
            if not curr_lap or not curr_lap.get("date_start"):
                return pd.DataFrame()

            t_start = curr_lap["date_start"]
            next_lap = next((l for l in laps_raw if l.get("lap_number") == l_num + 1), None)
            if next_lap and next_lap.get("date_start"):
                t_end = next_lap["date_start"]
            elif curr_lap.get("lap_duration"):
                start_dt = pd.to_datetime(t_start)
                end_dt = start_dt + pd.Timedelta(seconds=float(curr_lap["lap_duration"]))
                t_end = end_dt.isoformat()
            else:
                t_end = None

            car_url = f"{OPENF1_BASE}/car_data?session_key={session.session_key}&driver_number={drv_num}&date>={t_start}"
            if t_end: car_url += f"&date<={t_end}"
            loc_url = f"{OPENF1_BASE}/location?session_key={session.session_key}&driver_number={drv_num}&date>={t_start}"
            if t_end: loc_url += f"&date<={t_end}"

            car_data = requests.get(car_url, timeout=10).json()
            loc_data = requests.get(loc_url, timeout=10).json()

            if not car_data:
                return pd.DataFrame()

            car_df = pd.DataFrame(car_data)
            loc_df = pd.DataFrame(loc_data) if loc_data else pd.DataFrame(columns=["date", "x", "y", "z"])

            car_df["date"] = pd.to_datetime(car_df["date"])
            car_df = car_df.sort_values("date")

            if not loc_df.empty:
                loc_df["date"] = pd.to_datetime(loc_df["date"])
                loc_df = loc_df.sort_values("date")
                merged = pd.merge_asof(car_df, loc_df[["date", "x", "y", "z"]], on="date", direction="nearest")
                merged["x"] = merged["x"].ffill().bfill()
                merged["y"] = merged["y"].ffill().bfill()
                merged["z"] = merged["z"].ffill().bfill() if "z" in merged.columns else 0
            else:
                merged = car_df
                merged["x"] = 0.0
                merged["y"] = 0.0
                merged["z"] = 0.0

            # Elapsed time and Distance
            t0 = merged["date"].iloc[0]
            time_sec = (merged["date"] - t0).dt.total_seconds().values
            dt = np.diff(time_sec, prepend=0.0)
            dt[dt < 0] = 0.0
            dt[dt > 2.0] = 0.26

            speed_ms = merged["speed"].values / 3.6
            dist = np.cumsum(speed_ms * dt).round(1)

            df = pd.DataFrame()
            df["Distance"] = dist
            df["Time"] = time_sec.round(3)
            df["LapTime"] = time_sec.round(3)
            df["Speed_kmh"] = merged["speed"].round(1)
            df["Speed_mph"] = (merged["speed"] * 0.621371).round(1)
            df["Throttle"] = merged["throttle"].round(1)
            df["Brake"] = (merged["brake"] > 0).astype(int)
            df["nGear"] = merged["n_gear"].astype(int) if "n_gear" in merged.columns else 1
            df["RPM"] = merged["rpm"].astype(int) if "rpm" in merged.columns else 0
            df["DRS"] = merged["drs"].fillna(0).astype(int) if "drs" in merged.columns else 0
            df["X"] = merged["x"].round(1)
            df["Y"] = merged["y"].round(1)
            df["Z"] = merged["z"].round(1)

            # State: 1 Accel, 2 Coast, 3 Brake
            def classify(row):
                if row["Brake"] > 0:
                    return 3
                elif row["Throttle"] > 25:
                    return 1
                else:
                    return 2
            df["DrivingState"] = df.apply(classify, axis=1)

            df["TrackTemp"] = session.weather_track_temp
            df["AirTemp"] = session.weather_air_temp

            # Stint / Compound
            compound = "UNKNOWN"
            tyre_life = 0
            for s in session.stints.get(drv_num, []):
                if s.get("lap_start", 1) <= l_num <= s.get("lap_end", 999):
                    compound = str(s.get("compound", "UNKNOWN")).upper()
                    tyre_life = (s.get("tyre_age_at_start", 0) or 0) + (l_num - s.get("lap_start", 1))
                    break
            df["Compound"] = compound
            df["TyreLife"] = tyre_life
            df["LapNumber"] = l_num
            df["Driver"] = drv_code
            return df
        except Exception as e:
            logger.error(f"Error extracting OpenF1 telemetry for {drv_code} L{l_num}: {e}")
            return pd.DataFrame()

    # FastF1 Session Extraction
    try:
        tel = lap_obj_or_spec.get_telemetry()
        if tel.empty:
            return pd.DataFrame()

        df = pd.DataFrame()
        df["Distance"] = tel["Distance"].round(1)
        df["Time"] = tel["Time"].dt.total_seconds().round(3)
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

        def classify(row):
            if row["Brake"] > 0:
                return 3
            elif row["Throttle"] > 25:
                return 1
            else:
                return 2
        df["DrivingState"] = df.apply(classify, axis=1)

        if session is not None and hasattr(session, "weather_data") and session.weather_data is not None and not session.weather_data.empty:
            try:
                w_time = session.weather_data["Time"].dt.total_seconds()
                df["TrackTemp"] = np.interp(df["Time"], w_time, session.weather_data["TrackTemperature"]).round(1)
                df["AirTemp"] = np.interp(df["Time"], w_time, session.weather_data["AirTemperature"]).round(1)
            except:
                df["TrackTemp"] = round(float(session.weather_data["TrackTemperature"].mean()), 1)
                df["AirTemp"] = round(float(session.weather_data["AirTemperature"].mean()), 1)
        else:
            df["TrackTemp"] = 35.0
            df["AirTemp"] = 25.0

        df["Compound"] = str(lap_obj_or_spec.get("Compound", "UNKNOWN")).upper()
        df["TyreLife"] = int(lap_obj_or_spec.get("TyreLife", 0)) if pd.notna(lap_obj_or_spec.get("TyreLife")) else 0
        df["LapNumber"] = int(lap_obj_or_spec["LapNumber"])
        df["Driver"] = str(lap_obj_or_spec.get("Driver", ""))
        return df
    except Exception as e:
        logger.error(f"Error extracting FastF1 telemetry: {e}")
        return pd.DataFrame()


# --- CIRCUIT CORNERS & LAYOUT ---

def get_circuit_layout_and_corners(session: Any, ref_tel: Optional[pd.DataFrame] = None) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Returns official circuit corner annotations and track reference."""
    corners_df = pd.DataFrame()
    ref_track = pd.DataFrame()

    if session is None:
        return corners_df, ref_track

    # FastF1 Circuit Info
    if not getattr(session, "is_openf1", False):
        try:
            circuit_info = session.get_circuit_info()
            if circuit_info is not None and circuit_info.corners is not None and not circuit_info.corners.empty:
                corners_df = circuit_info.corners.copy()
                corners_df["Angle"] = circuit_info.rotation
                return corners_df, ref_track
        except:
            pass

    # OpenF1 Corner Detection via Speed Valleys
    if ref_tel is not None and not ref_tel.empty and len(ref_tel) > 20:
        try:
            valleys, _ = find_peaks(-ref_tel["Speed_kmh"].values, distance=10, prominence=15)
            c_list = []
            for i, v_idx in enumerate(valleys):
                c_list.append({
                    "Number": i + 1,
                    "Distance": ref_tel["Distance"].iloc[v_idx],
                    "X": ref_tel["X"].iloc[v_idx],
                    "Y": ref_tel["Y"].iloc[v_idx],
                    "Angle": 0
                })
            corners_df = pd.DataFrame(c_list)
        except Exception as e:
            logger.info(f"Corner detection fallback error: {e}")

    return corners_df, ref_track


# --- HEAD-TO-HEAD DELTA CALCULATION ---

def compute_head_to_head_telemetry(tel1: pd.DataFrame, tel2: pd.DataFrame) -> Dict[str, Any]:
    """
    Computes synchronized head-to-head delta time between Driver 1 and Driver 2.
    """
    if tel1.empty or tel2.empty:
        return {"error": "Telemetry missing for comparison"}

    max_dist = min(tel1["Distance"].max(), tel2["Distance"].max())
    grid_size = min(len(tel1), len(tel2))
    common_dist = np.linspace(0, max_dist, num=grid_size)

    t1_interp = np.interp(common_dist, tel1["Distance"], tel1["LapTime"])
    t2_interp = np.interp(common_dist, tel2["Distance"], tel2["LapTime"])
    delta_time = (t1_interp - t2_interp).round(3)

    delta_df = pd.DataFrame({
        "Distance": common_dist.round(1),
        "DeltaTime": delta_time
    })

    return {
        "tel1": tel1,
        "tel2": tel2,
        "delta": delta_df
    }
