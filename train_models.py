# train_models.py
"""
Run this script to train ML models from your existing data.
Usage: python train_models.py
Re-run weekly or after major data accumulation.
"""
import os
import numpy as np
import joblib
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timedelta

# Import your app models
import sys
sys.path.insert(0, os.path.dirname(__file__))
from app.models import Mesure, Capteur
from app.database import engine
from app.services.predictor import build_features

MODEL_DIR = "ml_models"
os.makedirs(MODEL_DIR, exist_ok=True)

CATEGORIES = ["Température", "Pression", "Humidité", "Qualité Air"]
THRESHOLDS = {
    "Température": 85.0,
    "Pression": 6.0,
    "Humidité": 90.0,
    "Qualité Air": 1000.0
}

Session = sessionmaker(bind=engine)

def fetch_training_data(session, category, hours=720):  # 30 days
    end = datetime.utcnow()
    start = end - timedelta(hours=hours)
    rows = session.query(
        func.date_trunc('hour', Mesure.time).label("bucket"),
        func.avg(Mesure.valeur).label("avg_val")
    ).join(Capteur).filter(
        Capteur.type_grandeur == category,
        Mesure.time >= start
    ).group_by("bucket").order_by("bucket").all()
    return [r.avg_val for r in rows if r.avg_val is not None]

def create_supervised_dataset(values, lookahead=6):
    """Turn time series into (features, target) pairs."""
    X, y = [], []
    for i in range(20, len(values) - lookahead):
        window = values[:i]
        feats = build_features(window)
        if feats is not None:
            X.append(feats.flatten())
            y.append(values[i + lookahead - 1])
    return np.array(X), np.array(y)

session = Session()
for category in CATEGORIES:
    print(f"\nTraining model for: {category}")
    values = fetch_training_data(session, category)
    
    if len(values) < 50:
        print(f"  Not enough data ({len(values)} points). Skipping.")
        continue
    
    X, y = create_supervised_dataset(values, lookahead=6)
    if len(X) < 20:
        print(f"  Dataset too small after windowing. Skipping.")
        continue
    
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, shuffle=False)
    
    scaler = StandardScaler()
    X_train_s = scaler.fit_transform(X_train)
    X_test_s = scaler.transform(X_test)
    
    model = GradientBoostingRegressor(
        n_estimators=200, max_depth=4, learning_rate=0.05,
        subsample=0.8, random_state=42
    )
    model.fit(X_train_s, y_train)
    
    preds = model.predict(X_test_s)
    mae = mean_absolute_error(y_test, preds)
    print(f"  MAE on test set: {mae:.3f}")
    
    key = category.lower().replace(' ', '_')
    joblib.dump(model, f"{MODEL_DIR}/{key}_model.pkl")
    joblib.dump(scaler, f"{MODEL_DIR}/{key}_scaler.pkl")
    print(f"  Saved: ml_models/{key}_model.pkl")

session.close()
print("\nDone. Models saved to ml_models/")