
import os
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from dotenv import load_dotenv
import requests

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env", override=False)

MODEL_FILE = BASE_DIR / "energy_model.joblib"

ENDPOINT_URL = os.getenv("QUICKML_ENDPOINT_URL")
ENDPOINT_KEY = os.getenv("QUICKML_ENDPOINT_KEY")
ACCESS_TOKEN = os.getenv("ZOHO_ACCESS_TOKEN")
CATALYST_ORG = os.getenv("CATALYST_ORG", "60093109493")
CATALYST_ENVIRONMENT = os.getenv("CATALYST_ENVIRONMENT", "Development")

REQUIRED_COLUMNS = [
    "timestamp",
    "ambient_temp_c",
    "humidity_pct",
    "solar_irradiance_wm2",
]


def prepare_features(df):
    df = df.copy()

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Missing input columns: {missing}")

    timestamp = pd.to_datetime(df["timestamp"], errors="coerce")
    if timestamp.isna().any():
        raise ValueError("Some timestamps are invalid.")

    features = pd.DataFrame(index=df.index)
    for column in REQUIRED_COLUMNS[1:]:
        features[column] = pd.to_numeric(df[column], errors="coerce")

    if features.isna().any().any():
        raise ValueError("Weather inputs contain missing or invalid values.")

    features["hour"] = timestamp.dt.hour
    features["day_of_week"] = timestamp.dt.dayofweek
    features["month"] = timestamp.dt.month
    features["day_of_year"] = timestamp.dt.dayofyear
    features["hour_sin"] = np.sin(2 * np.pi * features["hour"] / 24)
    features["hour_cos"] = np.cos(2 * np.pi * features["hour"] / 24)
    features["day_sin"] = np.sin(2 * np.pi * features["day_of_week"] / 7)
    features["day_cos"] = np.cos(2 * np.pi * features["day_of_week"] / 7)

    return features


def predict_local(input_df):
    if not MODEL_FILE.exists():
        raise FileNotFoundError(f"Local model not found: {MODEL_FILE}")

    saved = joblib.load(MODEL_FILE)
    model = saved["model"]
    features = prepare_features(input_df)
    features = features[saved["feature_columns"]]

    predictions = np.asarray(model.predict(features), dtype=float)
    if len(predictions) != len(input_df) or not np.isfinite(predictions).all():
        raise ValueError("Local model returned invalid predictions.")

    return predictions


def predict_quickml(input_df):
    """Call QuickML for each row. Each row uses one API request."""
    if not ENDPOINT_URL or not ENDPOINT_KEY or not ACCESS_TOKEN:
        raise ValueError("QuickML settings are missing from .env.")

    headers = {
        "X-QUICKML-ENDPOINT-KEY": ENDPOINT_KEY,
        "Authorization": f"Zoho-oauthtoken {ACCESS_TOKEN}",
        "CATALYST-ORG": CATALYST_ORG,
        "Environment": CATALYST_ENVIRONMENT,
        "Content-Type": "application/json",
    }

    predictions = []
    for _, row in input_df.iterrows():
        payload = {
            "data": {
                "timestamp": str(row["timestamp"]),
                "ambient_temp_c": float(row["ambient_temp_c"]),
                "humidity_pct": float(row["humidity_pct"]),
                "solar_irradiance_wm2": float(row["solar_irradiance_wm2"]),
            }
        }
        response = requests.post(
            ENDPOINT_URL, json=payload, headers=headers, timeout=30
        )
        if not response.ok:
            raise RuntimeError(
                f"QuickML returned HTTP {response.status_code}: "
                f"{response.text[:500]}"
            )

        result = response.json().get("result")
        if not isinstance(result, list) or len(result) != 1:
            raise ValueError("Unexpected QuickML response format.")
        predictions.append(float(result[0]))

    predictions = np.asarray(predictions, dtype=float)
    if not np.isfinite(predictions).all():
        raise ValueError("QuickML returned invalid predictions.")
    return predictions


def predict(input_df):
    """Use the explicitly selected prediction backend."""
    backend = os.getenv("PREDICTION_BACKEND", "local").strip().lower()

    if backend == "local":
        return predict_local(input_df)
    if backend == "quickml":
        return predict_quickml(input_df)

    raise ValueError("PREDICTION_BACKEND must be 'local' or 'quickml'.")





