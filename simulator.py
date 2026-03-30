# # # # import asyncio
# # # # import random
# # # # from asyncua import Server

# # # # async def main():
# # # #     # Initialisation du serveur
# # # #     server = Server()
# # # #     await server.init()
    
# # # #     # Configuration de l'URL du serveur (IP locale)
# # # #     url = "opc.tcp://127.0.0.1:4840/freeopcua/server/"
# # # #     server.set_endpoint(url)
# # # #     server.set_server_name("Simulateur Capteurs Industriels")

# # # #     # Création d'un espace de noms (Namespace)
# # # #     uri = "http://master2.iot.simulation"
# # # #     idx = await server.register_namespace(uri)

# # # #     # Création du dossier "Machine_Alpha" dans l'arborescence
# # # #     machine_obj = await server.nodes.objects.add_object(idx, "Machine_Alpha")

# # # #     # Ajout des variables (Capteurs) avec des valeurs initiales
# # # #     temp_node = await machine_obj.add_variable(idx, "Temperature", 22.0)
# # # #     press_node = await machine_obj.add_variable(idx, "Pression", 1.0)
# # # #     hum_node = await machine_obj.add_variable(idx, "Humidite", 45.0)

# # # #     # On autorise l'écriture sur ces variables si besoin
# # # #     await temp_node.set_writable()
# # # #     await press_node.set_writable()
# # # #     await hum_node.set_writable()

# # # #     async with server:
# # # #         print(f"✅ Serveur OPC UA lancé sur : {url}")
# # # #         print("Appuyez sur Ctrl+C pour arrêter.")
        
# # # #         while True:
# # # #             # Simulation des variations de données
# # # #             new_temp = round(random.uniform(20.0, 28.0), 2)
# # # #             new_press = round(random.uniform(0.8, 1.2), 2)
# # # #             new_hum = round(random.uniform(40.0, 60.0), 1)

# # # #             # Mise à jour des valeurs sur le serveur
# # # #             await temp_node.write_value(new_temp)
# # # #             await press_node.write_value(new_press)
# # # #             await hum_node.write_value(new_hum)

# # # #             print(f"Données envoyées : T={new_temp}°C, P={new_press} bar, H={new_hum}%")
            
# # # #             await asyncio.sleep(2) # Mise à jour toutes les 2 secondes

# # # # if __name__ == "__main__":
# # # #     try:
# # # #         asyncio.run(main())
# # # #     except KeyboardInterrupt:
# # # #         print("\nServeur arrêté.")

# # # import asyncio
# # # import random
# # # from asyncua import Server

# # # async def main():
# # #     server = Server()
# # #     await server.init()
# # #     server.set_endpoint("opc.tcp://127.0.0.1:4840/freeopcua/server/")
    
# # #     uri = "http://examples.freeopcua.github.io"
# # #     idx = await server.register_namespace(uri)

# # #     # Création de l'objet machine
# # #     machine = await server.nodes.objects.add_object(idx, "Machine_Alpha")
    
# # #     # Ajout des variables (NodeIDs: ns=2;i=2, i=3, i=4)
# # #     temp_var = await machine.add_variable(idx, "Temperature", 20.0)
# # #     press_var = await machine.add_variable(idx, "Pression", 1.2)
# # #     hum_var = await machine.add_variable(idx, "Humidite", 45.0)

# # #     await temp_var.set_writable()
# # #     await press_var.set_writable()
# # #     await hum_var.set_writable()

# # #     async with server:
# # #         print("Serveur OPC UA lancé (Port 4840)...")
# # #         while True:
# # #             # Simulation d'anomalies aléatoires
# # #             is_anomaly = random.random() < 0.05
            
# # #             if is_anomaly:
# # #                 temp = random.uniform(35, 45)  # Zone de danger
# # #                 press = random.uniform(4, 5)   # Zone de danger
# # #             else:
# # #                 temp = random.uniform(20, 26)  # Normal
# # #                 press = random.uniform(1.0, 2.0) # Normal
            
# # #             hum = random.uniform(40, 60)

# # #             await temp_var.write_value(temp)
# # #             await press_var.write_value(press)
# # #             await hum_var.write_value(hum)
            
# # #             print(f"OPC UA Out -> T:{temp:.2f}, P:{press:.2f}, H:{hum:.2f}")
# # #             await asyncio.sleep(2)

# # # if __name__ == "__main__":
# # #     asyncio.run(main())









# # import asyncio
# # import random
# # from asyncua import Server, ua

# # async def main():
# #     server = Server()
# #     await server.init()
# #     server.set_endpoint("opc.tcp://127.0.0.1:4840/freeopcua/server/")
    
# #     uri = "http://master2.iot.simulation"
# #     idx = await server.register_namespace(uri)
# #     machine = await server.nodes.objects.add_object(idx, "Machine_Alpha")

# #     configs = {
# #         "TEMP": {"range": (20, 25), "danger": (35, 50)},
# #         "PRES": {"range": (1.0, 1.5), "danger": (4.0, 6.0)},
# #         "HUMI": {"range": (40, 50), "danger": (80, 95)},
# #         "CO2":  {"range": (400, 600), "danger": (1500, 3000)}
# #     }

# #     nodes = []
# #     for prefix, cfg in configs.items():
# #         for i in range(1, 5):
# #             name = f"{prefix}_{0 if i < 10 else ''}{i}" # Matches TEMP_01, TEMP_02...
# #             # Initialize explicitly as Double
# #             init_val = float(cfg["range"][0])
# #             node = await machine.add_variable(idx, name, init_val)
# #             await node.set_writable()
# #             nodes.append({"node": node, "name": name, "cfg": cfg})

# #     async with server:
# #         print("Industrial Simulator Running: 16 Sensors")
# #         while True:
# #             for item in nodes:
# #                 cfg = item["cfg"]
# #                 is_danger = random.random() < 0.05
                
# #                 if is_danger:
# #                     val = random.uniform(*cfg["danger"])
# #                 else:
# #                     val = random.uniform(*cfg["range"])
                
# #                 # THE FIX: Wrap the value in a DataValue with an explicit Double type
# #                 new_val = ua.DataValue(ua.Variant(float(val), ua.VariantType.Double))
# #                 await item["node"].write_value(new_val)
                
# #             print(f"Update: 16 values sent to OPC Expert at {datetime.now().strftime('%H:%M:%S')}")
# #             await asyncio.sleep(2)

# # if __name__ == "__main__":
# #     from datetime import datetime # Added for the print
# #     asyncio.run(main())

# import asyncio
# import random
# from datetime import datetime
# from asyncua import Server, ua

# # Importation de ta configuration de base de données
# from database import SessionLocal
# import models

# # Configuration des plages de simulation par type de capteur
# # On se base sur le préfixe du code_unique (ex: TEMP, PRES)
# SIM_CONFIGS = {
#     "TEMP": {"range": (20, 25), "danger": (35, 50), "unit": "°C"},
#     "PRES": {"range": (1.0, 1.5), "danger": (4.0, 6.0), "unit": "bar"},
#     "HUMI": {"range": (40, 50), "danger": (80, 95), "unit": "%"},
#     "CO2":  {"range": (400, 600), "danger": (1500, 3000), "unit": "ppm"},
#     "DEFAULT": {"range": (0, 100), "danger": (110, 150), "unit": "pts"}
# }

# def get_config(code_unique):
#     """ Récupère la config de simulation selon le nom du capteur """
#     for key in SIM_CONFIGS:
#         if key in code_unique.upper():
#             return SIM_CONFIGS[key]
#     return SIM_CONFIGS["DEFAULT"]

# async def main():
#     # 1. Initialisation du Serveur OPC UA
#     server = Server()
#     await server.init()
#     server.set_endpoint("opc.tcp://127.0.0.1:4840/freeopcua/server/")
    
#     uri = "http://master2.iot.simulation"
#     idx = await server.register_namespace(uri)
    
#     # Création du dossier racine pour les capteurs
#     machine_obj = await server.nodes.objects.add_object(idx, "Machine_Alpha")

#     # 2. Lecture de la Base de Données pour générer les nœuds
#     print("🔍 Lecture de la base de données pour synchronisation...")
#     db = SessionLocal()
#     try:
#         db_sensors = db.query(models.Capteur).all()
#     finally:
#         db.close()

#     if not db_sensors:
#         print("❌ AUCUN CAPTEUR trouvé en base de données ! Arrêt du simulateur.")
#         return

#     # 3. Création dynamique des nœuds OPC UA
#     sim_nodes = []
#     for s in db_sensors:
#         # Initialisation à 0.0
#         node = await machine_obj.add_variable(idx, s.code_unique, 0.0)
#         await node.set_writable()
        
#         sim_nodes.append({
#             "node": node,
#             "code": s.code_unique,
#             "cfg": get_config(s.code_unique)
#         })
#         print(f"✅ Nœud créé : {s.code_unique}")

#     # 4. Boucle de simulation
#     async with server:
#         print(f"\n🚀 Serveur OPC UA lancé avec {len(sim_nodes)} capteurs.")
#         print("--------------------------------------------------")
        
#         while True:
#             for item in sim_nodes:
#                 cfg = item["cfg"]
#                 # Probabilité de 5% de générer une anomalie (zone danger)
#                 is_danger = random.random() < 0.05
                
#                 if is_danger:
#                     val = random.uniform(*cfg["danger"])
#                 else:
#                     val = random.uniform(*cfg["range"])
                
#                 # Écriture de la valeur au format Double (nécessaire pour OPC Expert/React)
#                 new_val = ua.DataValue(ua.Variant(float(val), ua.VariantType.Double))
#                 await item["node"].write_value(new_val)
                
#             print(f"📊 [{datetime.now().strftime('%H:%M:%S')}] Mise à jour de {len(sim_nodes)} capteurs envoyée.")
#             await asyncio.sleep(2)

# if __name__ == "__main__":
#     try:
#         asyncio.run(main())
#     except KeyboardInterrupt:
#         print("\n🛑 Simulateur arrêté.")


# simulator.py
import asyncio
import random
import math
from datetime import datetime
from asyncua import Server, ua

# Import from the new app structure
from app.database import SessionLocal
from app.models import Capteur

# Configuration des plages de simulation par type de capteur (plus réaliste)
SIM_CONFIGS = {
    "TEMP": {
        "normal_range": (20.0, 26.0),    # °C – plage normale
        "warning_range": (26.0, 30.0),   # zone d'attention
        "danger_range": (30.0, 35.0),    # zone critique (rare)
        "drift_step": 0.02,              # dérive progressive par cycle
        "unit": "°C"
    },
    "PRES": {
        "normal_range": (1.0, 1.6),
        "warning_range": (1.6, 2.5),
        "danger_range": (2.5, 4.0),
        "drift_step": 0.005,
        "unit": "bar"
    },
    "HUMI": {
        "normal_range": (40.0, 55.0),
        "warning_range": (55.0, 70.0),
        "danger_range": (70.0, 85.0),
        "drift_step": 0.1,
        "unit": "%"
    },
    "CO2": {
        "normal_range": (380, 500),
        "warning_range": (500, 700),
        "danger_range": (700, 900),
        "drift_step": 1.0,
        "unit": "ppm"
    },
    "DEFAULT": {
        "normal_range": (0, 100),
        "warning_range": (100, 120),
        "danger_range": (120, 150),
        "drift_step": 0.5,
        "unit": "pts"
    }
}

# Probabilité d'anomalie (très faible pour simuler un fonctionnement normal)
ANOMALY_PROBABILITY = 0.02  # 2% – rare
# Probabilité de dérive (changement progressif de tendance)
DRIFT_PROBABILITY = 0.01    # 1% par cycle

def get_config(code_unique):
    for key in SIM_CONFIGS:
        if key in code_unique.upper():
            return SIM_CONFIGS[key]
    return SIM_CONFIGS["DEFAULT"]

async def main():
    print("🚀 Démarrage du simulateur industriel réaliste...")
    server = Server()
    await server.init()
    server.set_endpoint("opc.tcp://127.0.0.1:4840/freeopcua/server/")
    
    uri = "http://master2.iot.simulation"
    idx = await server.register_namespace(uri)
    machine_obj = await server.nodes.objects.add_object(idx, "Machine_Alpha")

    # Récupération des capteurs depuis la base de données
    print("🔍 Lecture des capteurs depuis la base de données...")
    db = SessionLocal()
    try:
        db_sensors = db.query(Capteur).filter(Capteur.is_activated == True).all()
    finally:
        db.close()

    if not db_sensors:
        print("❌ Aucun capteur actif trouvé en base de données. Arrêt.")
        return

    # Stockage des tendances de dérive pour chaque capteur
    drift_states = {}
    for s in db_sensors:
        # État initial: valeur "normale" aléatoire, dérive nulle
        config = get_config(s.code_unique)
        base_val = random.uniform(*config["normal_range"])
        drift_states[s.code_unique] = {
            "current": base_val,
            "drift": 0.0,
            "config": config,
            "cycle": 0
        }

    # Création des nœuds OPC UA
    sim_nodes = []
    for s in db_sensors:
        node = await machine_obj.add_variable(idx, s.code_unique, 0.0)
        await node.set_writable()
        sim_nodes.append({
            "node": node,
            "code": s.code_unique,
            "config": get_config(s.code_unique)
        })
        print(f"✅ Nœud créé : {s.code_unique}")

    print(f"\n🏭 Simulateur lancé avec {len(sim_nodes)} capteurs. Anomalies probables : {ANOMALY_PROBABILITY*100:.0f}%")
    print("--------------------------------------------------")

    async with server:
        cycle = 0
        while True:
            cycle += 1
            for item in sim_nodes:
                code = item["code"]
                state = drift_states[code]
                config = state["config"]
                
                # 1. Mise à jour de la dérive (tendance progressive)
                if random.random() < DRIFT_PROBABILITY:
                    # Changement de tendance : +/- petite variation
                    delta_drift = random.uniform(-0.5, 0.5) * config["drift_step"]
                    state["drift"] += delta_drift
                    # Limiter la dérive pour ne pas trop s'écarter
                    state["drift"] = max(-2.0, min(2.0, state["drift"]))
                
                # 2. Valeur de base avec dérive
                base = state["current"] + state["drift"]
                
                # 3. Ajout d'une fluctuation normale (bruit blanc)
                noise = random.gauss(0, config["drift_step"] * 5)
                
                # 4. Déterminer la plage selon que c'est une anomalie ou non
                is_anomaly = random.random() < ANOMALY_PROBABILITY
                
                if is_anomaly:
                    # Anomalie : valeur dans la plage dangereuse
                    val = random.uniform(*config["danger_range"])
                    # On ne garde pas la dérive pour ne pas accumuler
                    state["current"] = val
                    drift_states[code]["drift"] = 0.0  # reset drift after anomaly
                else:
                    # Comportement normal : évolue autour de la valeur actuelle avec bruit
                    # et reste dans la plage normale
                    target = state["current"] + noise * 0.1
                    # Appliquer la dérive
                    target += state["drift"] * 0.05
                    # Rester dans la plage normale
                    target = max(config["normal_range"][0], min(config["normal_range"][1], target))
                    val = target
                    state["current"] = target
                
                # Arrondi à 2 décimales
                val = round(val, 2)
                
                # Écriture sur le serveur OPC UA
                new_val = ua.DataValue(ua.Variant(float(val), ua.VariantType.Double))
                await item["node"].write_value(new_val)
            
            # Affichage périodique (toutes les 10 secondes)
            if cycle % 5 == 0:
                print(f"📊 [{datetime.now().strftime('%H:%M:%S')}] Mise à jour de {len(sim_nodes)} capteurs. Cycle {cycle}")
            
            await asyncio.sleep(2)  # Mise à jour toutes les 2 secondes

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Simulateur arrêté par l'utilisateur.")