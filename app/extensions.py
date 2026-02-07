"""
Stato condiviso: MongoDB, DataFrame email, flag OCR.
Tutto inizializzato via init_app() o al primo import.
"""
import pandas as pd
from pymongo import MongoClient
from app.config import MONGO_URI, DB_SETTINGS_NAME, DB_EPSTEIN_NAME, EMAILS_PARQUET

# ── MongoDB ────────────────────────────────────────────────────
mongo_client = MongoClient(MONGO_URI)

db_settings = mongo_client[DB_SETTINGS_NAME]
db_epstein = mongo_client[DB_EPSTEIN_NAME]

analyses_collection = db_epstein["analyses"]
deep_analyses_collection = db_epstein["deep_analyses"]
syntheses_collection = db_epstein["syntheses"]
searches_collection = db_epstein["searches"]
crew_investigations_collection = db_epstein["crew_investigations"]
merged_investigations_collection = db_epstein["merged_investigations"]
people_collection = db_epstein["people"]
app_settings_collection = db_epstein["app_settings"]

# ── Email DataFrame ────────────────────────────────────────────
EMAILS_DF = None
try:
    import os
    if os.path.exists(EMAILS_PARQUET):
        EMAILS_DF = pd.read_parquet(EMAILS_PARQUET)
        print(f"✅ Dataset email caricato: {len(EMAILS_DF)} email")
    else:
        print("⚠️  Dataset email non trovato.")
except Exception as e:
    print(f"⚠️  Errore caricamento dataset email: {e}")

# ── OCR flags ──────────────────────────────────────────────────
OCR_AVAILABLE = False
try:
    from pdf2image import convert_from_bytes  # noqa: F401
    import pytesseract  # noqa: F401
    OCR_AVAILABLE = True
except ImportError:
    print("⚠️  OCR non disponibile. Installa: pip install pytesseract pdf2image")

PYMUPDF_AVAILABLE = False
try:
    import fitz  # noqa: F401
    PYMUPDF_AVAILABLE = True
except ImportError:
    print("⚠️  PyMuPDF non disponibile. Installa: pip install PyMuPDF")

# ── PDF cache ──────────────────────────────────────────────────
pdf_cache = {}


def init_app(app):
    """Hook opzionale per inizializzazioni legate all'app Flask."""
    pass
