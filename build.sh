#!/usr/bin/env bash
# Render build script for PrintMax Django app
set -o errexit

# Install Python dependencies
pip install -r requirements.txt

# Navigate to Django project directory
cd smartprint

# Collect static files (required for WhiteNoise)
python manage.py collectstatic --noinput --clear

# Run database migrations (uses SQLite by default; set DATABASE_URL for PostgreSQL)
python manage.py migrate --noinput
