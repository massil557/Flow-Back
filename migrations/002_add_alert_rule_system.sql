-- Migration 002: Add AlertRule system and new columns to alertes

CREATE TABLE IF NOT EXISTS alert_rules (
    id               SERIAL PRIMARY KEY,
    sensor_id        INTEGER NOT NULL REFERENCES capteurs(id) ON DELETE CASCADE,
    condition        VARCHAR(10) NOT NULL CHECK (condition IN ('>', '<', '>=', '<=', '==')),
    threshold        DOUBLE PRECISION NOT NULL,
    severity         VARCHAR(10) NOT NULL CHECK (severity IN ('danger', 'warning')),
    cooldown_seconds INTEGER DEFAULT 0,
    active           BOOLEAN DEFAULT TRUE,
    created_at       TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_alert_rules_sensor_id ON alert_rules(sensor_id);
CREATE INDEX IF NOT EXISTS idx_alert_rules_active ON alert_rules(active);

ALTER TABLE alertes ADD COLUMN IF NOT EXISTS severity VARCHAR(10) DEFAULT 'danger';
ALTER TABLE alertes ADD COLUMN IF NOT EXISTS rule_id INTEGER REFERENCES alert_rules(id) ON DELETE SET NULL;
ALTER TABLE alertes ADD COLUMN IF NOT EXISTS is_rule_based BOOLEAN DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_alertes_rule_id ON alertes(rule_id);
