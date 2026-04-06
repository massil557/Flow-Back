# app/services/ai_analyzer.py
import asyncio
import httpx
from typing import List
from app.schemas import GraphPoint

# ------------------------------------------------------------------------------
# ORIGINAL COMMENTED CODE (preserved exactly as in your main.py)
# ------------------------------------------------------------------------------
# ... (your existing commented blocks, unchanged) ...

# ------------------------------------------------------------------------------
# ORIGINAL WORKING OLLAMA PROMPT (with added system message)
# ------------------------------------------------------------------------------
async def analyze_with_ai(points: List[GraphPoint], sensor_name: str, threshold: float) -> str:
    try:
        import httpx
        all_values = [p.y for p in points]
        if not all_values:
            return "1) DIAGNOSTIC: Aucune donnee disponible.\n2) TENDANCE: Aucune donnee.\n3) RECOMMANDATION: Verifier la connexion du capteur."

        # Smart sampling (same as before)
        MAX_SAMPLE = 60
        if len(all_values) <= MAX_SAMPLE:
            sampled = all_values
        else:
            step = len(all_values) / MAX_SAMPLE
            sampled = [all_values[int(i * step)] for i in range(MAX_SAMPLE)]

        # Stats
        min_val   = round(min(all_values), 2)
        max_val   = round(max(all_values), 2)
        avg_val   = round(sum(all_values) / len(all_values), 2)
        over_threshold = len([v for v in all_values if v >= threshold])
        third = max(1, len(sampled) // 3)
        avg_start = sum(sampled[:third]) / third
        avg_end   = sum(sampled[-third:]) / third
        trend_hint = "montee" if avg_end > avg_start * 1.05 else "descente" if avg_end < avg_start * 0.95 else "stable"
        is_alert  = over_threshold > 0

        # Sensor type detection (industrial context)
        code = sensor_name.upper()
        if "TEMP" in code:
            sensor_type = "temperature (C)"
            context     = "surchauffe moteur, panne refroidissement, isolation defectueuse"
            unit        = "°C"
        elif "PRES" in code:
            sensor_type = "pression (bar)"
            context     = "surpression, fuite de circuit, obstruction conduite"
            unit        = "bar"
        elif "HUMI" in code:
            sensor_type = "humidite (%)"
            context     = "condensation, corrosion equipements, infiltration eau"
            unit        = "%"
        elif "CO2" in code:
            sensor_type = "qualite air CO2 (ppm)"
            context     = "ventilation insuffisante, accumulation gaz, danger respiratoire"
            unit        = "ppm"
        else:
            sensor_type = "grandeur industrielle"
            context     = "anomalie capteur, derive mesure, dysfonctionnement equipement"
            unit        = "u"

        status = "ALERTE CRITIQUE" if is_alert else "STABLE"
        base = f"Capteur {sensor_type} '{sensor_name}'. Min={min_val}{unit} Max={max_val}{unit} Moy={avg_val}{unit} Seuil={threshold}{unit} Depassements={over_threshold}/{len(all_values)} mesures. Tendance={trend_hint}. Etat={status}."

        async with httpx.AsyncClient(timeout=300.0) as client:
            async def ask(prompt: str, tokens: int) -> str:
                # Add a system message to force industrial context
                system_msg = "Tu es un expert en maintenance industrielle pour une usine (Cevital). Tu ne donnes jamais de conseils pour des véhicules automobiles. Tu réponds uniquement en français."
                r = await client.post("http://localhost:11434/api/generate", json={
                    "model": "gemma2:2b",
                    "prompt": f"{system_msg}\n\n{prompt}",
                    "stream": False,
                    "options": {"num_predict": tokens, "temperature": 0.1}
                })
                return r.json()["response"].strip()

            # ── 1. Diagnostic global ──────────────────────────────────────────
            diagnostic = await ask(
                f"{base} Ecris UNE phrase de diagnostic technique en francais.",
                80
            )

            # ── 2. Gravite ────────────────────────────────────────────────────
            gravite = await ask(
                f"{base} Evalue la gravite de la situation: Faible, Moderee ou Critique. "
                f"Explique en UNE phrase pourquoi.",
                80
            )

            # ── 3. Tendance ───────────────────────────────────────────────────
            tendance = await ask(
                f"{base} Decris en UNE phrase la tendance d evolution "
                f"(montee, descente, stable, oscillation).",
                80
            )

            # ── 4. Cause probable ─────────────────────────────────────────────
            cause = await ask(
                f"{base} Contexte: {context}. "
                f"Cite la cause industrielle la plus probable en UNE phrase.",
                80
            )

            # ── 5. Actions immediates ─────────────────────────────────────────
            actions = await ask(
                f"Capteur {sensor_type} en {status}. Contexte industriel: {context}. "
                f"Donne 3 actions immediates pour une usine. Format:\n"
                f"- action 1\n- action 2\n- action 3\n"
                f"Maximum 10 mots par action. Rien d autre.",
                150
            )

            # ── 6. Prevention long terme ──────────────────────────────────────
            prevention = await ask(
                f"Capteur {sensor_type} en {status}. Contexte industriel: {context}. "
                f"Donne 3 mesures preventives long terme pour une usine. Format:\n"
                f"- mesure 1\n- mesure 2\n- mesure 3\n"
                f"Maximum 10 mots par mesure. Rien d autre.",
                150
            )

        return (
            f"1) DIAGNOSTIC:\n{diagnostic}\n\n"
            f"2) GRAVITE:\n{gravite}\n\n"
            f"3) TENDANCE:\n{tendance}\n\n"
            f"4) CAUSE PROBABLE:\n{cause}\n\n"
            f"5) ACTIONS IMMEDIATES:\n{actions}\n\n"
            f"6) PREVENTION LONG TERME:\n{prevention}"
        )

    except Exception as e:
        print(f"--- ERREUR IA COMPLETE ---: {repr(e)}")
        return (
            f"1) DIAGNOSTIC:\nImpossible de contacter Ollama.\n\n"
            f"2) GRAVITE:\nInconnue.\n\n"
            f"3) TENDANCE:\nVerifiez qu Ollama est lance.\n\n"
            f"4) CAUSE PROBABLE:\nConnexion Ollama impossible.\n\n"
            f"5) ACTIONS IMMEDIATES:\n- Lancer ollama serve\n- Verifier gemma2:2b\n- Relancer uvicorn\n\n"
            f"6) PREVENTION LONG TERME:\n- Configurer Ollama au demarrage\n- Monitorer le service\n- Verifier les logs"
        )

async def analyze_with_ai_summary(prompt: str) -> str:
    """Generate a short AI summary using the local Ollama model."""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=300) as client:  # increase to 120 seconds
            response = await client.post(
                "http://localhost:11434/api/generate",
                json={
                    "model": "gemma2:2b",
                    "prompt": prompt,
                    "stream": False,
                    "options": {"num_predict": 200, "temperature": 0.3}
                }
            )
            if response.status_code == 200:
                return response.json()["response"].strip()
            else:
                return "Analyse IA temporairement indisponible."
    except httpx.TimeoutException:
        print("AI summary timeout: Ollama took too long to respond")
        return "Analyse IA non disponible (délai dépassé)."
    except Exception as e:
        print(f"AI summary error: {e}")
        return "Analyse IA non disponible."