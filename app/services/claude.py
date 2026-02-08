"""
Client Anthropic centralizzato + retry.
"""
import time
from anthropic import Anthropic
from app.extensions import db_settings


def get_claude_api_key():
    """Recupera la chiave API di Claude dal database"""
    key_data = db_settings["api_keys"].find_one({"service": "claude"})
    if key_data and "key" in key_data:
        return key_data["key"]
    return None


def get_anthropic_base_url():
    """Recupera il base_url personalizzato dal database (per modelli locali)"""
    key_data = db_settings["api_keys"].find_one({"service": "claude"})
    if key_data and key_data.get("base_url"):
        return key_data["base_url"]
    return None


def get_anthropic_client():
    """Crea il client Anthropic con la chiave dal database"""
    api_key = get_claude_api_key()
    if not api_key:
        raise ValueError("Chiave API Claude non trovata nel database.")
    base_url = get_anthropic_base_url()
    if base_url:
        return Anthropic(api_key=api_key, base_url=base_url)
    return Anthropic(api_key=api_key)


def call_claude_with_retry(client, max_retries=3, **kwargs):
    """Chiama l'API Claude con retry automatico per errori 500"""
    last_error = None
    for attempt in range(max_retries):
        try:
            response = client.messages.create(**kwargs)
            return response
        except Exception as e:
            last_error = e
            error_str = str(e)
            if "500" in error_str or "Internal server error" in error_str:
                wait_time = (attempt + 1) * 2
                print(f"[CLAUDE] Errore 500, retry {attempt + 1}/{max_retries} tra {wait_time}s...")
                time.sleep(wait_time)
            else:
                raise e
    raise last_error
