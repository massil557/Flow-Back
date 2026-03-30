import asyncio
from collections import deque
from datetime import datetime
from asyncua import Client
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models import Capteur, Alerte, Mesure
from app.config import OPC_URL, get_threshold

live_cache = {}
last_two = {}

async def log_and_cache_forever():
    global live_cache
    while True:
        db = SessionLocal()
        try:
            async with Client(url=OPC_URL) as client:
                sensors = db.query(Capteur).all()
                if not sensors:
                    print("Aucun capteur trouvé en BDD. Lance seed_db.py.")
                for s in sensors:
                    if not s.is_activated:
                        continue
                    try:
                        path = ["0:Objects", "2:Machine_Alpha", f"2:{s.code_unique}"]
                        node = await client.nodes.root.get_child(path)
                        val_brute = await node.read_value()
                        val = round(float(val_brute), 2)
                        current_time = datetime.now().strftime("%H:%M:%S")

                        if s.code_unique not in live_cache:
                            live_cache[s.code_unique] = deque(maxlen=20)
                        live_cache[s.code_unique].append({"v": val, "t": current_time})

                        if s.code_unique not in last_two:
                            last_two[s.code_unique] = []
                        last_two[s.code_unique].append(val)
                        if len(last_two[s.code_unique]) > 2:
                            last_two[s.code_unique].pop(0)

                        sensor_threshold = get_threshold(s.code_unique)
                        if val >= sensor_threshold:
                            prev_vals = last_two.get(s.code_unique, [])
                            prev_val = prev_vals[-2] if len(prev_vals) > 1 else None
                            if prev_val is None or prev_val < sensor_threshold:
                                alert_msg = f"Valeur {val} >= seuil {sensor_threshold}"
                                db_alert = Alerte(
                                    capteur_code=s.code_unique,
                                    valeur=val,
                                    seuil_depasse=sensor_threshold,
                                    message=alert_msg,
                                    time=datetime.utcnow(),
                                    is_resolved=False
                                )
                                db.add(db_alert)
                        new_measure = Mesure(
                            capteur_id=s.id,
                            valeur=val,
                            time=datetime.utcnow(),
                        )
                        db.add(new_measure)
                    except Exception:
                        continue
                db.commit()
        except Exception as e:
            print(f"Erreur de connexion OPC UA : {e}")
        finally:
            db.close()
        await asyncio.sleep(1)

# Additional endpoints that need these caches
def get_live_cache():
    return live_cache

def get_last_two():
    return last_two