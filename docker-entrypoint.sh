#!/bin/sh
set -e

# Apply any pending database migrations before the server starts. Idempotent —
# a no-op when the database is already at the latest revision. Without this a
# fresh deployment has no tables and every page 500s.
flask db upgrade

# Seed default site settings (idempotent; leaves existing values untouched).
flask seed-settings || true

exec gunicorn --bind 0.0.0.0:8000 "app:create_app()"
