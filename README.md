# EMERGE – Emergency Route Intelligence (frontend-only demo)

A Streamlit prototype of the *Uncertainty-Aware Emergency Route and ETA Prediction System*, styled after the
"Emergency Route Intelligence" Figma Make design. **All data is simulated** – no ML model, routing algorithm, GPS,
backend or database.

## Install & run (Python 3.12+)
```
pip install -r requirements.txt
streamlit run app.py
```

## Demo script
1. **Overview** → *Start emergency navigation* → pick a hospital (nearest is pre-selected) → *Compare routes*.
2. Compare *Fastest* vs *Most reliable* (P10–P90 ETA ranges, reliability) → select one → *Start navigation*.
3. Hands off (~50 s): marker drives the route, an accident appears, EMERGE re-routes, the marker follows the new
   route, then the arrival summary appears. Finished trips are added to **Trip history**.
4. **Trip planner** → choose hospital + window → *Find Best Departure Time* → *Confirm and Start Trip*.
5. Sidebar **Demo scenarios**: GPS unavailable, nearest hospital unreachable, traffic/weather data missing.

Map tiles need internet (OpenStreetMap). Routes are generated from the chosen start/hospital, so they are
illustrative, not real road geometry.
