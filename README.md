# 🏎️ MusCup 2026 F1 Fantasy Tracker

The MusCup 2026 F1 Dashboard is a custom-built, fully automated fantasy Formula 1 tracking application. Built with Python and Streamlit, it replaces manual spreadsheet tracking with a live, interactive web application that pulls real-world race data, resolves substitute drivers dynamically, and projects rest-of-season championship probabilities for the league owners: Chief, Carly, Stuebe, and Kennedy.

## 🎯 Purpose
This application serves as the definitive source of truth for the 2026 MusCup F1 fantasy league. It is designed to automatically ingest race results, calculate custom league scoring, and visualize points progression through interactive charts, eliminating the need for manual data entry and human error.

## 🧮 Scoring System
The MusCup uses a unique reverse-position scoring system designed to reward high finishes while ruthlessly penalizing crashes and retirements. 

**The Formula:** `Points = Max(0, 23 - Finishing Position)`

### Points Breakdown
| Finish | Points | Finish | Points | Finish | Points |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **1st** | 22 | **9th** | 14 | **17th** | 6 |
| **2nd** | 21 | **10th** | 13 | **18th** | 5 |
| **3rd** | 20 | **11th** | 12 | **19th** | 4 |
| **4th** | 19 | **12th** | 11 | **20th** | 3 |
| **5th** | 18 | **13th** | 10 | **21st** | 2 |
| **6th** | 17 | **14th** | 9 | **22nd** | 1 |
| **7th** | 16 | **15th** | 8 | **DNF** | 0 |
| **8th** | 15 | **16th** | 7 | **DNS** | 0 |

### 🚨 Strict DNF Enforcement
In real-world Formula 1, a driver who crashes on the final lap is often still "Classified" with a numerical finish (e.g., 18th place). **The MusCup does not reward crashes.** The ingestion script utilizes a Strict DNF protocol: if a driver's official status is anything other than "Finished" or "+[X] Lap", they are scored as a hard DNF and receive **0 points**.

## ✨ Key Features
* **Automated Data Ingestion:** A GitHub Actions cron job automatically pings the Jolpica/Ergast API daily to fetch the latest sprint and race results.
* **Seat-Inheritance Protocol:** The app tracks *seats*, not just names. If a team uses a reserve/substitute driver for a weekend, the script automatically executes a mid-season swap, ensuring the points correctly route to the player who owns that team's seat.
* **Monte Carlo Projections:** A predictive engine runs 1,000 statistical simulations of the remaining races based on current driver averages to project ultimate championship win probabilities.
* **Interactive Data Visualization:** Features Plotly-powered, color-coordinated line charts tracking both Player points progression and the Top 5 overall drivers across the season.
* **Password-Protected Admin Panel:** A secure UI tab allows the league commissioner to execute trades, assign unowned seats, and update the draft configuration on the fly.

## 🛠️ Architecture & Tech Stack
* **Frontend/UI:** Streamlit
* **Data Processing:** Pandas, NumPy
* **Data Visualization:** Plotly Express
* **Automation:** GitHub Actions (YAML)
* **API Integration:** Jolpica (Ergast F1 API fallback)
* **Data Storage:** Flat files stored in the repository (`seats_config.json` for state management, `race_results.csv` for historical logs).

## 🚀 How It Works
1. **The Trigger:** A daily GitHub Action workflow runs `ingest_results.py`.
2. **The Fetch:** The script pulls the latest race classifications from the API.
3. **The Audit:** The script checks the data against the historical logs in `seats_config.json` to ensure it only processes new races.
4. **The Push:** New race data is calculated, appended to `race_results.csv`, and pushed back to the GitHub repository.
5. **The Display:** Streamlit instantly detects the file change, flushes its cache, and re-renders the live dashboard with the updated standings.
6. 
