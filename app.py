
import os
import math
import time
from pathlib import Path

import pandas as pd
from flask import Flask, jsonify, request, send_from_directory
from predict import predict

BASE_DIR = Path(__file__).resolve().parent

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024

REQUIRED_COLUMNS = [
    "timestamp",
    "ambient_temp_c",
    "humidity_pct",
    "solar_irradiance_wm2",
]

LIVE_TELEMETRY_URL = os.getenv("LIVE_TELEMETRY_URL", "").strip()
LIVE_TELEMETRY_TOKEN = os.getenv("LIVE_TELEMETRY_TOKEN", "").strip()

# Demonstration battery settings.
# These are assumptions, not measurements from a physical battery.
BATTERY_CAPACITY_KWH = 500.0
BATTERY_INITIAL_SOC = 78.0
BATTERY_MAX_CHARGE_KW = 100.0
BATTERY_MAX_DISCHARGE_KW = 100.0
BATTERY_EFFICIENCY = 0.90


def get_telemetry():
    """Get live telemetry when configured; otherwise use demo telemetry."""

    if LIVE_TELEMETRY_URL:
        import json
        from urllib.request import Request, urlopen
        from urllib.error import URLError, HTTPError

        headers = {"Accept": "application/json"}

        if LIVE_TELEMETRY_TOKEN:
            headers["Authorization"] = f"Bearer {LIVE_TELEMETRY_TOKEN}"

        req = Request(LIVE_TELEMETRY_URL, headers=headers)

        try:
            with urlopen(req, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))

            if isinstance(payload, dict):
                payload = payload.get(
                    "data",
                    payload.get("telemetry", [payload])
                )

            if isinstance(payload, dict):
                payload = [payload]

            if not isinstance(payload, list) or not payload:
                raise ValueError(
                    "The live API returned no telemetry rows."
                )

            data = pd.DataFrame(payload)
            return data, "LIVE API", True

        except (HTTPError, URLError, TimeoutError, ValueError) as error:
            raise RuntimeError(
                f"Live telemetry API failed: {error}"
            ) from error

    # Demo telemetry only; no physical sensors are connected.
    sample_path = BASE_DIR / "sample_test_input.csv"
    data = pd.read_csv(sample_path)

    if data.empty:
        raise ValueError("sample_test_input.csv contains no rows.")

    now = pd.Timestamp.now().floor("h")
    data = data.head(24).copy()

    original_times = pd.to_datetime(
        data["timestamp"], errors="coerce"
    )

    if original_times.notna().any():
        first_time = original_times.dropna().iloc[0]
        offsets = (
            original_times - first_time
        ).dt.total_seconds() / 3600
        offsets = offsets.fillna(0)
    else:
        offsets = pd.Series(range(len(data)), index=data.index)

    data["timestamp"] = [
        now + pd.Timedelta(hours=float(offset))
        for offset in offsets
    ]

    elapsed = int(time.time() // 5)

    data["ambient_temp_c"] = (
        pd.to_numeric(data["ambient_temp_c"], errors="coerce")
        + 0.3 * math.sin(elapsed / 3)
    )

    data["humidity_pct"] = (
        pd.to_numeric(data["humidity_pct"], errors="coerce")
        + 1.0 * math.sin(elapsed / 4)
    ).clip(0, 100)

    data["solar_irradiance_wm2"] = (
        pd.to_numeric(
            data["solar_irradiance_wm2"], errors="coerce"
        )
        * (1 + 0.03 * math.sin(elapsed / 5))
    ).clip(lower=0)

    return data, "SIMULATED DEMO", False


def make_forecast(data):
    """Clean telemetry, predict demand, and apply controller rules."""

    if data.empty:
        raise ValueError("No telemetry rows were provided.")

    missing = [
        column for column in REQUIRED_COLUMNS
        if column not in data.columns
    ]

    if missing:
        raise ValueError(
            f"Missing columns: {', '.join(missing)}"
        )

    data = data[REQUIRED_COLUMNS].copy()

    data["timestamp"] = pd.to_datetime(
        data["timestamp"], errors="coerce"
    )

    for column in REQUIRED_COLUMNS[1:]:
        data[column] = pd.to_numeric(
            data[column], errors="coerce"
        )

    # Remove rows with missing or invalid values.
    data = data.dropna(subset=REQUIRED_COLUMNS)

    # Reject impossible weather values.
    data = data[
        data["humidity_pct"].between(0, 100)
        & data["solar_irradiance_wm2"].ge(0)
        & data["ambient_temp_c"].between(-80, 80)
    ]

    data = data.drop_duplicates(
        subset=["timestamp"]
    )

    data = data.sort_values(
        "timestamp"
    ).head(24).reset_index(drop=True)

    if data.empty:
        raise ValueError(
            "No valid telemetry rows remain after cleaning."
        )

    predictions = predict(data)

    if len(predictions) != len(data):
        raise ValueError(
            "Prediction count does not match input row count."
        )

    forecast = []

    for i, (_, row) in enumerate(data.iterrows()):
        timestamp = row["timestamp"]
        demand = float(predictions[i])

        if not math.isfinite(demand) or demand < 0:
            raise ValueError(
                "The model returned an invalid demand prediction."
            )

        hour = int(timestamp.hour)

        # Required HackSphere controller rule.
        mode = (
            "Renewable Storage"
            if demand > 160 or 18 <= hour <= 22
            else "Main Grid"
        )

        # Independent overload alert.
        alert = (
            "Critical Overload"
            if demand >= 200
            else "Normal"
        )

        forecast.append({
            "time": timestamp.strftime("%H:%M"),
            "timestamp": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            "demand": round(demand, 2),
            "mode": mode,
            "alert": alert,
            "solar_irradiance_wm2": round(
                float(row["solar_irradiance_wm2"]), 2
            ),
        })

    return forecast


def simulate_battery(forecast):
    """
    Simulate battery SOC over the forecast horizon.

    This is a demonstration model, not a real battery controller.
    The SOC starts at 78% for each generated forecast.
    """

    soc = BATTERY_INITIAL_SOC
    results = []

    for item in forecast:
        hour = int(item["timestamp"][11:13])
        demand = item["demand"]
        mode = item["mode"]
        solar = item["solar_irradiance_wm2"]

        # Estimate available solar charging power using a
        # simplified mapping. This is not measured power output.
        estimated_solar_kw = min(
            BATTERY_MAX_CHARGE_KW,
            max(0.0, solar / 10.0)
        )

        if mode == "Renewable Storage":
            # Assumption: storage supplies part of demand above
            # a 100 kW reference level.
            discharge_kw = min(
                BATTERY_MAX_DISCHARGE_KW,
                max(0.0, demand - 100.0)
            )

            # Energy used during one forecast hour.
            energy_used_kwh = discharge_kw / BATTERY_EFFICIENCY
            soc -= (
                energy_used_kwh / BATTERY_CAPACITY_KWH
            ) * 100.0

            battery_power_kw = -discharge_kw

        else:
            # Charge only during daytime when solar is available.
            if 9 <= hour <= 15:
                charge_kw = estimated_solar_kw
            else:
                charge_kw = 0.0

            energy_added_kwh = (
                charge_kw * BATTERY_EFFICIENCY
            )

            soc += (
                energy_added_kwh / BATTERY_CAPACITY_KWH
            ) * 100.0

            battery_power_kw = charge_kw

        soc = max(0.0, min(100.0, soc))

        if soc < 20:
            battery_status = "Low Battery"
        elif soc <= 30:
            battery_status = "Battery Reserve"
        else:
            battery_status = "Normal"

        item["battery_soc"] = round(soc, 1)
        item["battery_status"] = battery_status
        item["battery_power_kw"] = round(
            battery_power_kw, 2
        )

        # Keep overload alerts independent from battery status.
        results.append(item)

    return results


def build_forecast_response(data, source, is_live):
    """Create the common API response for forecast data."""

    forecast = simulate_battery(make_forecast(data))

    return {
        "forecast": forecast,
        "source": source,
        "is_live": is_live,
        "battery_soc": (
            forecast[0]["battery_soc"]
            if forecast else BATTERY_INITIAL_SOC
        ),
        "battery_status": (
            forecast[0]["battery_status"]
            if forecast else "Normal"
        ),
        "updated_at": pd.Timestamp.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
    }


@app.route("/")
def home():
    return send_from_directory(
        str(BASE_DIR), "index.html"
    )


@app.route("/style.css")
def style():
    return send_from_directory(
        str(BASE_DIR), "style.css"
    )


@app.route("/script.js")
def script():
    return send_from_directory(
        str(BASE_DIR), "script.js"
    )


@app.route("/api/status")
def api_status():
    return jsonify({
        "mode": (
            "LIVE API"
            if LIVE_TELEMETRY_URL
            else "SIMULATED DEMO"
        ),
        "is_live": bool(LIVE_TELEMETRY_URL),
        "refresh_seconds": 5,
        "battery_simulation": True,
    })


@app.route("/api/forecast")
def get_forecast():
    try:
        data, source, is_live = get_telemetry()

        return jsonify(
            build_forecast_response(data, source, is_live)
        )

    except Exception as error:
        app.logger.exception(
            "Forecast generation failed"
        )
        return jsonify({"error": str(error)}), 400


@app.route("/api/upload-telemetry", methods=["POST"])
def upload_telemetry():
    if "file" not in request.files:
        return jsonify({
            "error": "Choose a CSV file to upload."
        }), 400

    file = request.files["file"]

    if (
        not file.filename
        or not file.filename.lower().endswith(".csv")
    ):
        return jsonify({
            "error": "Please upload a CSV file."
        }), 400

    try:
        data = pd.read_csv(file)

        response = build_forecast_response(
            data,
            "CSV UPLOAD",
            False
        )

        response["message"] = (
            "Telemetry processed successfully."
        )
        response["rows_used"] = len(
            response["forecast"]
        )

        return jsonify(response)

    except Exception as error:
        app.logger.exception(
            "Telemetry upload failed"
        )
        return jsonify({"error": str(error)}), 400


@app.errorhandler(413)
def file_too_large(_error):
    return jsonify({
        "error": "File is too large. Maximum size is 5 MB."
    }), 413


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("X_ZOHO_CATALYST_LISTEN_PORT", os.environ.get("PORT", "5000"))),
        debug=False
    )

