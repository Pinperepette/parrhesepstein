"""
Cache e accesso ai settings dell'applicazione.
"""
import time
from app.extensions import app_settings_collection

_settings_cache = {}
_settings_cache_time = 0


def get_app_settings():
    """Ritorna {model, language} con cache 60s"""
    global _settings_cache, _settings_cache_time
    now = time.time()
    if _settings_cache and (now - _settings_cache_time) < 60:
        return _settings_cache
    doc = app_settings_collection.find_one({"_id": "global"})
    _settings_cache = {
        "model": doc.get("model", "claude-sonnet-4-20250514") if doc else "claude-sonnet-4-20250514",
        "language": doc.get("language", "Italiano") if doc else "Italiano",
    }
    _settings_cache_time = now
    return _settings_cache


def get_model():
    return get_app_settings()["model"]


def get_language():
    return get_app_settings()["language"]


def get_language_instruction():
    lang = get_language()
    mapping = {
        "Italiano": "\n\nIMPORTANT: Rispondi interamente in italiano.",
        "English": "\n\nIMPORTANT: Respond entirely in English.",
        "Español": "\n\nIMPORTANT: Responde completamente en español.",
        "Français": "\n\nIMPORTANT: Réponds entièrement en français.",
        "Deutsch": "\n\nIMPORTANT: Antworte vollständig auf Deutsch.",
        "Português": "\n\nIMPORTANT: Responda inteiramente em português.",
    }
    return mapping.get(lang, mapping["Italiano"])


def invalidate_settings_cache():
    global _settings_cache, _settings_cache_time
    _settings_cache = {}
    _settings_cache_time = 0
