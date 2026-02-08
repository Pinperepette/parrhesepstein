"""
/api/settings GET/POST
"""
from flask import Blueprint, jsonify, request
from app.services.claude import get_claude_api_key, get_anthropic_base_url
from app.services.settings import get_app_settings, invalidate_settings_cache
from app.extensions import app_settings_collection, db_settings
from app.config import VALID_MODELS, VALID_LANGUAGES

bp = Blueprint("settings_routes", __name__)


@bp.route('/api/settings', methods=['GET'])
def api_get_settings():
    try:
        settings = get_app_settings()
        api_key = get_claude_api_key()
        base_url = get_anthropic_base_url()
        api_key_masked = ""
        if api_key:
            api_key_masked = api_key[:8] + "..." + api_key[-4:] if len(api_key) > 12 else "***"
        return jsonify({
            'model': settings['model'],
            'language': settings['language'],
            'api_key_masked': api_key_masked,
            'api_key_set': bool(api_key),
            'base_url': base_url or '',
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/api/settings', methods=['POST'])
def api_save_settings():
    try:
        data = request.json
        update = {}

        # Determine if a custom base_url is being set (or already set)
        incoming_base_url = data.get('base_url', '').strip() if 'base_url' in data else None
        current_base_url = get_anthropic_base_url()
        has_custom_endpoint = bool(incoming_base_url) if incoming_base_url is not None else bool(current_base_url)

        if 'model' in data:
            # Skip VALID_MODELS check when using a custom endpoint (local models)
            if not has_custom_endpoint and data['model'] not in VALID_MODELS:
                return jsonify({'error': f'Modello non valido: {data["model"]}'}), 400
            update['model'] = data['model']
        if 'language' in data:
            if data['language'] not in VALID_LANGUAGES:
                return jsonify({'error': f'Lingua non valida: {data["language"]}'}), 400
            update['language'] = data['language']
        if 'api_key' in data and data['api_key'].strip():
            new_key = data['api_key'].strip()
            db_settings["api_keys"].update_one(
                {"service": "claude"}, {"$set": {"key": new_key}}, upsert=True
            )
        if 'base_url' in data:
            base_url_val = data['base_url'].strip()
            db_settings["api_keys"].update_one(
                {"service": "claude"}, {"$set": {"base_url": base_url_val}}, upsert=True
            )
        if update:
            app_settings_collection.update_one(
                {"_id": "global"}, {"$set": update}, upsert=True
            )
        invalidate_settings_cache()
        return jsonify({'success': True, 'message': 'Settings salvati'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
