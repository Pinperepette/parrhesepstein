"""
/api/flights, /api/flights/passengers
"""
import json
from flask import Blueprint, jsonify
from app.config import FLIGHTS_JSON
import os

bp = Blueprint("flights", __name__)

_flights_cache = {}


def _load_flights_data():
    """Carica e cache i dati voli dal JSON."""
    if _flights_cache.get('data') is not None:
        return _flights_cache['data']
    try:
        if os.path.exists(FLIGHTS_JSON):
            with open(FLIGHTS_JSON, 'r') as f:
                _flights_cache['data'] = json.load(f)
        else:
            _flights_cache['data'] = None
    except Exception:
        _flights_cache['data'] = None
    return _flights_cache['data']


@bp.route('/api/flights')
def api_flights():
    try:
        data = _load_flights_data()
        if data:
            return jsonify(data)
        else:
            return jsonify({"error": "Flight data not found", "flights": [], "route_counts": {}, "passenger_counts": {}})
    except Exception as e:
        return jsonify({"error": str(e), "flights": [], "route_counts": {}, "passenger_counts": {}})


@bp.route('/api/flights/passengers')
def api_flights_passengers():
    """Restituisce tutti i nomi passeggeri unici estratti dai voli."""
    try:
        data = _load_flights_data()
        if not data:
            return jsonify({"passengers": []})

        names = set()
        skip = {'JE', 'GM', 'REPOSITION', 'NO PASSENGERS', 'EMPTY', 'N/A', ''}
        for flight in data.get('flights', []):
            raw = flight.get('passengers', '')
            for part in raw.split(','):
                name = part.strip()
                if name and name.upper() not in skip and len(name) > 2:
                    names.add(name)

        return jsonify({"passengers": sorted(names)})
    except Exception as e:
        return jsonify({"error": str(e), "passengers": []})
