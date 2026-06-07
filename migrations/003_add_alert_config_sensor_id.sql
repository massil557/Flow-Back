-- Migration 003: Add sensor_id to alert_configs
ALTER TABLE alert_configs ADD COLUMN IF NOT EXISTS sensor_id INTEGER REFERENCES capteurs(id) ON DELETE SET NULL;

-- Index (must be separate statement after column exists)
CREATE INDEX IF NOT EXISTS idx_alert_configs_sensor_id ON alert_configs(sensor_id);
