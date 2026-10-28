
from datetime import datetime


def decide_power_source(timestamp, demand_kw):
    # Convert timestamp into a datetime object
    time = datetime.strptime(
        timestamp, "%Y-%m-%d %H:%M:%S"
    )

    hour = time.hour

    # Check the evening peak window: 18:00 to 22:00
    evening_peak = 18 <= hour <= 22

    # Choose the power source
    if demand_kw > 160 or evening_peak:
        grid_mode = "Renewable Storage"
    else:
        grid_mode = "Main Grid"

    # Check for critical overload
    # Assumption: alert at 200 kW or above
    if demand_kw >= 200:
        alert = "Critical Overload"
    else:
        alert = "Normal"

    return grid_mode, alert


# Test the controller
tests = [
    ("2026-10-24 10:00:00", 120),
    ("2026-10-24 14:00:00", 175),
    ("2026-10-24 19:00:00", 140),
    ("2026-10-24 16:00:00", 205),
]

for timestamp, demand in tests:
    mode, alert = decide_power_source(
        timestamp, demand
    )

    print("Time:", timestamp)
    print("Demand:", demand, "kW")
    print("Power Source:", mode)
    print("Alert:", alert)
    print("-" * 30)
