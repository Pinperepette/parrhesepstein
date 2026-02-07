"""
Configurazione centralizzata per Parrhesepstein.
"""
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DOCUMENTS_DIR = os.path.join(BASE_DIR, "documents")
os.makedirs(DOCUMENTS_DIR, exist_ok=True)

CHROMA_PATH = os.path.join(BASE_DIR, "chroma_db")

ANALYSES_DIR = os.path.join(BASE_DIR, "saved_analyses")
os.makedirs(ANALYSES_DIR, exist_ok=True)

EMAILS_PARQUET = os.path.join(BASE_DIR, "epstein_emails.parquet")
FLIGHTS_JSON = os.path.join(BASE_DIR, "epstein_flights_data.json")

SECRET_KEY = "epstein-files-analyzer-secret-key"

MONGO_URI = "mongodb://localhost:27017/"
DB_SETTINGS_NAME = "SnareSetting"
DB_EPSTEIN_NAME = "EpsteinAnalyses"

VALID_MODELS = [
    "claude-sonnet-4-20250514",
    "claude-opus-4-20250514",
    "claude-haiku-4-5-20251001",
]

VALID_LANGUAGES = [
    "Italiano", "English", "Español", "Français", "Deutsch", "Português"
]
