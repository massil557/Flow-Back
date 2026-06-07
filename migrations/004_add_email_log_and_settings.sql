-- Migration 004: Add alert_email_log and app_settings tables

CREATE TABLE IF NOT EXISTS alert_email_log (
    id            SERIAL PRIMARY KEY,
    rule_id       INTEGER REFERENCES alert_rules(id) ON DELETE SET NULL,
    config_id     INTEGER REFERENCES alert_configs(id) ON DELETE SET NULL,
    sensor_code   VARCHAR(50) NOT NULL,
    level         VARCHAR(10) NOT NULL,
    recipient     VARCHAR(255) NOT NULL,
    success       BOOLEAN NOT NULL DEFAULT FALSE,
    error_message TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    last_sent_at  TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_alert_email_log_rule_id    ON alert_email_log(rule_id);
CREATE INDEX IF NOT EXISTS idx_alert_email_log_config_id  ON alert_email_log(config_id);
CREATE INDEX IF NOT EXISTS idx_alert_email_log_sensor     ON alert_email_log(sensor_code, level);
CREATE INDEX IF NOT EXISTS idx_alert_email_log_sent_at    ON alert_email_log(last_sent_at);

CREATE TABLE IF NOT EXISTS app_settings (
    key        VARCHAR(100) PRIMARY KEY,
    value      TEXT NOT NULL DEFAULT '',
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Seed default setting
INSERT INTO app_settings (key, value) VALUES ('default_email_recipient', '')
ON CONFLICT (key) DO NOTHING;
