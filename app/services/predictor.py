# app/services/predictor.py
import numpy as np
import joblib
import os
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.models import Mesure, Capteur

MODEL_DIR = os.path.join(os.path.dirname(__file__), "../../ml_models")

def get_historical_data(db: Session, category: str, zone_id: int = None, hours: int = 48):
    """Fetch recent sensor readings for a given category."""
    end = datetime.utcnow()
    start = end - timedelta(hours=hours)
    
    query = db.query(
        func.date_trunc('hour', Mesure.time).label("bucket"),
        func.avg(Mesure.valeur).label("avg_val")
    ).join(Capteur, Mesure.capteur_id == Capteur.id).filter(
        Capteur.type_grandeur == category,
        Mesure.time >= start,
        Mesure.time <= end
    )
    if zone_id:
        query = query.filter(Capteur.zone_id == zone_id)
    
    rows = query.group_by("bucket").order_by("bucket").all()
    return [(r.bucket, r.avg_val) for r in rows if r.avg_val is not None]

def build_features(values: list[float]) -> np.ndarray:
    """Engineer features from a time series of values."""
    v = np.array(values)
    if len(v) < 6:
        return None
    
    features = []
    # Last known values (recent window)
    features.extend(v[-6:].tolist())
    # Rolling statistics
    features.append(float(np.mean(v[-12:])) if len(v) >= 12 else float(np.mean(v)))
    features.append(float(np.std(v[-12:])) if len(v) >= 12 else float(np.std(v)))
    # Rate of change (last 3 steps)
    features.append(float(v[-1] - v[-4]) if len(v) >= 4 else 0.0)
    # Time of day (hour encoding)
    hour = datetime.utcnow().hour
    features.append(np.sin(2 * np.pi * hour / 24))
    features.append(np.cos(2 * np.pi * hour / 24))
    
    return np.array(features).reshape(1, -1)

def predict_future(db: Session, category: str, threshold: float, 
                   zone_id: int = None, horizons_hours: list = [1, 6, 24]):
    """
    Returns predicted values for future time horizons
    and a danger probability score.
    """
    model_path = os.path.join(MODEL_DIR, f"{category.lower().replace(' ', '_')}_model.pkl")
    scaler_path = os.path.join(MODEL_DIR, f"{category.lower().replace(' ', '_')}_scaler.pkl")
    
    # Fallback: statistical prediction if no trained model yet
    rows = get_historical_data(db, category, zone_id, hours=72)
    if len(rows) < 10:
        return None
    
    values = [r[1] for r in rows]
    
    if not os.path.exists(model_path):
        # Simple statistical fallback (linear trend extrapolation)
        return _statistical_fallback(values, threshold, horizons_hours)
    
    try:
        model = joblib.load(model_path)
        scaler = joblib.load(scaler_path)
        features = build_features(values)
        if features is None:
            return None
        features_scaled = scaler.transform(features)
        
        predictions = {}
        for h in horizons_hours:
            pred = float(model.predict(features_scaled)[0])
            # Adjust for horizon (simple decay toward mean)
            mean = np.mean(values[-24:])
            decay = 0.85 ** h
            adjusted = pred * decay + mean * (1 - decay)
            predictions[h] = round(adjusted, 2)
        
        # Danger probability: how close is prediction to threshold
        max_pred = max(predictions.values())
        danger_pct = min(100, max(0, int((max_pred / threshold) * 100)))
        
        return {
            "predictions": predictions,
            "danger_score": danger_pct,
            "current_avg": round(np.mean(values[-3:]), 2),
            "threshold": threshold
        }
    except Exception as e:
        print(f"Model prediction error: {e}")
        return _statistical_fallback(values, threshold, horizons_hours)

def _statistical_fallback(values, threshold, horizons_hours):
    """Linear regression fallback — no trained model needed."""
    v = np.array(values[-24:])
    x = np.arange(len(v))
    coeffs = np.polyfit(x, v, 1)  # slope, intercept
    slope, intercept = coeffs
    
    predictions = {}
    for h in horizons_hours:
        future_x = len(v) + h
        pred = slope * future_x + intercept
        predictions[h] = round(float(pred), 2)
    
    max_pred = max(predictions.values())
    danger_pct = min(100, max(0, int((max_pred / threshold) * 100)))
    
    return {
        "predictions": predictions,
        "danger_score": danger_pct,
        "current_avg": round(float(np.mean(v[-3:])), 2),
        "threshold": threshold,
        "method": "statistical_fallback"
    }