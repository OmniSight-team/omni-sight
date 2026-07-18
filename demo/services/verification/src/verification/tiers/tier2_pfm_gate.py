# TODO Phase B
# Tier 2 — PFM Gate
# Calls the Predictive Forecasting Module (services/pfm) on the candidate window.
# Passes the candidate only if max(p) ≥ θ₂ and confidence κ ≥ κ_min.
# Filters low-confidence predictions before invoking the expensive VLM.
