-- Migration: Add is_admin column to utilisateurs table
-- Run: psql -U postgres -d supervision_industrielle -f migrations/001_add_is_admin.sql

ALTER TABLE utilisateurs
  ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE;

-- Mark existing admin users (those with role_id = admin role id)
UPDATE utilisateurs
  SET is_admin = TRUE
  WHERE role_id = (SELECT id FROM roles WHERE nom = 'admin');
