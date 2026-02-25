from database import SessionLocal, engine
import models

def seed_data():
    db = SessionLocal()
    
    # 1. Vérifier si on a déjà une Zone, sinon la créer
    zone = db.query(models.Zone).first()
    if not zone:
        zone = models.Zone(nom_zone="Zone_Industrielle_Alpha")
        db.add(zone)
        db.commit()
        db.refresh(zone)
        print(f"✅ Zone créée : {zone.nom_zone}")

    # 2. Configuration des 16 capteurs (4x4)
    # On vérifie d'abord si la table est vide pour éviter les doublons
    if db.query(models.Capteur).count() == 0:
        sensor_configs = [
            {"prefix": "TEMP", "type": "Temperature", "unit": "°C"},
            {"prefix": "PRES", "type": "Pression", "unit": "Bar"},
            {"prefix": "HUMI", "type": "Humidite", "unit": "%"},
            {"prefix": "CO2", "type": "CO2", "unit": "ppm"},
        ]

        for config in sensor_configs:
            for i in range(1, 5):
                code = f"{config['prefix']}_{i:02d}"
                new_sensor = models.Capteur(
                    code_unique=code,
                    type_grandeur=config['type'],
                    unite=config['unit'],
                    adresse_ip=f"192.168.1.{10 + i}", # IP fictive
                    zone_id=zone.id
                )
                db.add(new_sensor)
        
        db.commit()
        print(" 16 capteurs insérés avec succès dans la base de données !")
    else:
        print("Les capteurs existent déjà dans la base.")

    db.close()

if __name__ == "__main__":
    seed_data()