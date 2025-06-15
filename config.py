# config.py

import os

class Config:
    # Flask Secret Key (Important for session security)
    # This MUST be set via environment variable SECRET_KEY on Render.
    SECRET_KEY = os.environ.get('SECRET_KEY')

    # Database Configuration (PostgreSQL)
    # This MUST be set via environment variable DATABASE_URL on Render.
    # If DATABASE_URL is not set, SQLALCHEMY_DATABASE_URI will be None, leading to an error.
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL')

    SQLALCHEMY_TRACK_MODIFICATIONS = False # Recommended to keep False for performance

    # Arkesel SMS API Configuration
    ARKESEL_API_KEY = os.environ.get('ARKESEL_API_KEY')
    ARKESEL_SENDER_ID = os.environ.get('ARKESEL_SENDER_ID')

    # Google Sheets Configuration
    GOOGLE_SHEET_URL = os.environ.get('GOOGLE_SHEET_URL')
    # On Render, the service account JSON content should be in GOOGLE_CREDENTIALS_JSON env var.
    # This GOOGLE_SERVICE_ACCOUNT_PATH is mainly for local development setups
    # where you store the JSON key file on disk.
    GOOGLE_SERVICE_ACCOUNT_PATH = os.environ.get('GOOGLE_SERVICE_ACCOUNT_PATH')

    # Flask Debug Mode (Set to False for production)
    FLASK_DEBUG = os.environ.get('FLASK_DEBUG') == 'True' # Reads "True" string as boolean
