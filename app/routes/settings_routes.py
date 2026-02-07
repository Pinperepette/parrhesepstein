"""
/api/settings GET/POST
"""
from flask import Blueprint, jsonify, request
from app.services.claude import get_claude_api_key
from app.services.settings import get_app_settings, invalidate_settings_cache
from app.extensions import app_settings_collection, db_settings
from app.config import VALID_MODELS, VALID_LANGUAGES

bp = Blueprint("settings_routes", __name__)


@bp.route('/api/settings', methods=['GET'])
def api_get_settings():
    try:
        settings = get_app_settings()
        api_key = get_claude_api_key()
        api_key_masked = ""
        if api_key:
            api_key_masked = api_key[:8] + "..." + api_key[-4:] if len(api_key) > 12 else "***"
        return jsonify({
            'model': settings['model'],
            'language': settings['language'],
            'api_key_masked': api_key_masked,
            'api_key_set': bool(api_key),
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/api/settings', methods=['POST'])
def api_save_settings():
    try:
        data = request.json
        update = {}
        if 'model' in data:
            if data['model'] not in VALID_MODELS:
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
        if update:
            app_settings_collection.update_one(
                {"_id": "global"}, {"$set": update}, upsert=True
            )
        invalidate_settings_cache()
        return jsonify({'success': True, 'message': 'Settings salvati'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
