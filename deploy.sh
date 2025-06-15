#!/bin/bash

# Navigate to your application directory
cd /path/to/your/app

# Activate virtual environment
source venv/bin/activate

# Optional: Stop existing Gunicorn process
# pkill gunicorn

# Delete old database (for a clean slate on deploy, be cautious in production)
rm -f community.db

# Initialize or upgrade the database
flask init-db

# Start Gunicorn
gunicorn app:app -w 4 -b 0.0.0.0:5000 --timeout 120