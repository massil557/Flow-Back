from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from pyparsing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timedelta
from app.database import get_db
from app.models import Capteur, Mesure, Zone
from app.schemas import TimeSeriesRequest
from app.services.predictor import predict_future
from app.services.ai_analyzer import analyze_with_ai
import asyncio
import httpx

router = APIRouter(prefix="/api/analytics", tags=["Analytics"])

@router.post("/timeseries")
def get_timeseries_data(req: TimeSeriesRequest, db: Session = Depends(get_db)):
    if req.start and req.end:
        start_dt = req.start
        end_dt = req.end
    elif req.hours is not None and req.hours > 0:
        end_dt = datetime.utcnow()
        start_dt = end_dt - timedelta(hours=req.hours)
    else:
        raise HTTPException(status_code=400, detail="Either start/end or hours must be provided")
    trunc_map = {"minute": "minute", "hour": "hour", "day": "day"}
    trunc = trunc_map.get(req.interval, "hour")
    query = db.query(
        func.date_trunc(trunc, Mesure.time).label("bucket"),
        func.avg(Mesure.valeur).label("avg_value"),
        func.min(Mesure.valeur).label("min_value"),
        func.max(Mesure.valeur).label("max_value"),
        func.count(Mesure.valeur).label("count")
    ).join(Capteur, Mesure.capteur_id == Capteur.id).filter(
        Capteur.type_grandeur == req.category,
        Mesure.time >= start_dt,
        Mesure.time <= end_dt
    )
    if req.zone_id is not None:
        query = query.filter(Capteur.zone_id == req.zone_id)
    results = query.group_by("bucket").order_by("bucket").all()
    return [
        {
            "timestamp": r.bucket,
            "avg_value": r.avg_value,
            "min_value": r.min_value,
            "max_value": r.max_value,
            "count": r.count
        }
        for r in results
    ]

@router.post("/zone-comparison")
def get_zone_comparison(req: TimeSeriesRequest, db: Session = Depends(get_db)):
    if req.start and req.end:
        start_dt = req.start
        end_dt = req.end
    elif req.hours is not None and req.hours > 0:
        end_dt = datetime.utcnow()
        start_dt = end_dt - timedelta(hours=req.hours)
    else:
        raise HTTPException(status_code=400, detail="Either start/end or hours must be provided")
    results = db.query(
        Zone.id.label("zone_id"),
        Zone.nom_zone.label("zone_name"),
        func.avg(Mesure.valeur).label("avg_value"),
        func.count(func.distinct(Capteur.id)).label("sensor_count")
    ).join(Capteur, Capteur.zone_id == Zone.id).join(Mesure, Mesure.capteur_id == Capteur.id).filter(
        Capteur.type_grandeur == req.category,
        Mesure.time >= start_dt,
        Mesure.time <= end_dt
    ).group_by(Zone.id, Zone.nom_zone).order_by(Zone.nom_zone).all()
    return [
        {
            "zone_id": r.zone_id,
            "zone_name": r.zone_name,
            "avg_value": r.avg_value,
            "sensor_count": r.sensor_count
        }
        for r in results
    ]

DANGER_THRESHOLDS = {
    "Température": 85.0,
    "Pression":    6.0,
    "Humidité":    90.0,
    "Qualité Air": 1000.0,
}

# ── BUG 3 FIX : Fonction de calcul du score de danger ────────────────────────
#
# ANCIEN comportement (implicite dans predictor.py) :
#   danger_score = (current_avg / threshold) * 100
#   → Ex : 32°C / 85 * 100 = 37.6%  ← complètement faux si seuil réel = 30
#
# NOUVEAU comportement :
#   - Sous 70% du seuil          → score linéaire 0–40%  (zone verte)
#   - Entre 70% et 100% du seuil → score linéaire 40–79% (zone orange, pré-alerte)
#   - Au-delà du seuil           → score 80–100%, croît rapidement (zone critique)
#
# Ainsi, dépasser le seuil donne TOUJOURS un score ≥ 80% (critique).

def compute_danger_score(current_value: float, threshold: float) -> int:
    """
    Calcule un score de danger (0-100) respectant strictement les seuils.

    Zones :
      0  –  40%  : normal      (valeur < 70% du seuil)
      40 –  79%  : modéré      (valeur entre 70% et 100% du seuil)
      80 – 100%  : critique    (valeur >= seuil)
    """
    if threshold <= 0:
        return 0

    ratio = current_value / threshold  # ex: 32/85 = 0.376 | 32/30 = 1.066

    if ratio >= 1.0:
        # Zone critique : 80% de base + jusqu'à 20 pts supplémentaires
        # Croît de 80 → 100 sur un dépassement de 0 → 25% au-dessus du seuil
        overshoot = (ratio - 1.0) / 0.25          # 0.0 → 1.0 sur 25% de dépassement
        score = 80 + min(20, round(overshoot * 20))
    elif ratio >= 0.70:
        # Zone modérée : 40% → 79%
        # Interpolation linéaire entre 70% et 100% du seuil
        normalized = (ratio - 0.70) / 0.30        # 0.0 → 1.0
        score = 40 + round(normalized * 39)
    else:
        # Zone normale : 0% → 39%
        normalized = ratio / 0.70                 # 0.0 → 1.0
        score = round(normalized * 39)

    return max(0, min(100, score))


class PredictionRequest(BaseModel):
    category: str
    zone_id: int | None = None
    horizons: list[int] | None = [1, 6, 24]


@router.post("/predict")
async def get_prediction(req: PredictionRequest, db: Session = Depends(get_db)):
    threshold = DANGER_THRESHOLDS.get(req.category, 100.0)
    unit_map  = {"Température": "°C", "Pression": "bar", "Humidité": "%", "Qualité Air": "ppm"}
    unit      = unit_map.get(req.category, "u")
    horizons  = req.horizons if req.horizons else [1, 6, 24]

    try:
        result = predict_future(
            db=db,
            category=req.category,
            threshold=threshold,
            zone_id=req.zone_id,
            horizons_hours=horizons
        )
    except Exception as e:
        print(f"predict_future crashed: {e}")
        result = None

    if result is None:
        return {
            "predictions":  {str(h): 0.0 for h in horizons},
            "danger_score": 0,
            "current_avg":  0.0,
            "threshold":    threshold,
            "narrative":    "Données insuffisantes pour la prévision.",
            "category":     req.category,
            "unit":         unit,
        }

    # ── BUG 3 FIX : recalcul du score avec la nouvelle fonction ──────────────
    # On écrase le danger_score éventuellement renvoyé par predict_future
    # pour garantir la cohérence avec nos seuils définis dans DANGER_THRESHOLDS.
    corrected_danger_score = compute_danger_score(
        current_value=result.get("current_avg", 0.0),
        threshold=threshold
    )

    preds_text = ", ".join([f"dans {h}h: {v:.2f}" for h, v in result["predictions"].items()])
    ollama_prompt = (
        f"Capteur {req.category}. Valeur actuelle: {result['current_avg']}{unit}. "
        f"Seuil danger: {threshold}{unit}. "
        f"Prévisions ML: {preds_text}{unit}. "
        f"Score danger: {corrected_danger_score}%. "
        f"Donne UNE phrase d'alerte préventive en français pour l'opérateur."
    )

    narrative = "Analyse IA non disponible."
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post("http://localhost:11434/api/generate", json={
                "model":   "gemma2:2b",
                "prompt":  ollama_prompt,
                "stream":  False,
                "options": {"num_predict": 80, "temperature": 0.1}
            })
            narrative = r.json()["response"].strip()
    except Exception as e:
        print(f"Ollama narrative error: {e}")

    return {
        **result,
        "predictions":  {str(k): v for k, v in result["predictions"].items()},
        "danger_score": corrected_danger_score,   # ← score corrigé
        "category":     req.category,
        "unit":         unit,
        "threshold":    threshold,                # ← toujours retourné pour sync frontend
        "narrative":    narrative,
    }
