"""
/api/people — 3 route
"""
from flask import Blueprint, jsonify, request
from app.extensions import people_collection

bp = Blueprint("people_routes", __name__)


@bp.route('/api/people', methods=['GET'])
def api_people_list():
    search = request.args.get('search', '').strip()
    relevance = request.args.get('relevance', '').strip()
    query = {}
    if search:
        query['$or'] = [
            {'name': {'$regex': search, '$options': 'i'}},
            {'aliases': {'$regex': search, '$options': 'i'}},
            {'roles': {'$regex': search, '$options': 'i'}},
        ]
    if relevance:
        query['relevance'] = relevance

    people = list(people_collection.find(query).sort('last_updated', -1))
    for p in people:
        p['id'] = p['_id']
        if p.get('first_seen'):
            p['first_seen'] = p['first_seen'].isoformat()
        if p.get('last_updated'):
            p['last_updated'] = p['last_updated'].isoformat()
        if p.get('dossier') and p['dossier'].get('generated_at'):
            p['dossier']['generated_at'] = p['dossier']['generated_at'].isoformat()
        for inv in p.get('investigations', []):
            if inv.get('date'):
                inv['date'] = inv['date'].isoformat()
        p['investigation_count'] = len(p.get('investigations', []))
        p['connection_count'] = len(p.get('all_connections', []))
        p['has_dossier'] = p.get('dossier') is not None

    return jsonify({'people': people, 'total': len(people)})


@bp.route('/api/people/<person_id>', methods=['GET'])
def api_person_detail(person_id):
    person = people_collection.find_one({'_id': person_id})
    if not person:
        return jsonify({'error': 'Persona non trovata'}), 404

    person['id'] = person['_id']
    if person.get('first_seen'):
        person['first_seen'] = person['first_seen'].isoformat()
    if person.get('last_updated'):
        person['last_updated'] = person['last_updated'].isoformat()
    if person.get('dossier') and person['dossier'].get('generated_at'):
        person['dossier']['generated_at'] = person['dossier']['generated_at'].isoformat()
    for inv in person.get('investigations', []):
        if inv.get('date'):
            inv['date'] = inv['date'].isoformat()
    person['investigation_count'] = len(person.get('investigations', []))
    person['connection_count'] = len(person.get('all_connections', []))
    person['has_dossier'] = person.get('dossier') is not None

    return jsonify(person)


@bp.route('/api/people/<person_id>', methods=['DELETE'])
def api_person_delete(person_id):
    result = people_collection.delete_one({'_id': person_id})
    if result.deleted_count == 0:
        return jsonify({'error': 'Persona non trovata'}), 404
    return jsonify({'success': True, 'deleted': person_id})
