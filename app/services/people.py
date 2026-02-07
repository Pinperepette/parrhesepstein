"""
Gestione collection people in MongoDB.
"""
import re
from datetime import datetime
from app.extensions import people_collection


def normalize_person_id(name):
    """Normalizza il nome per usarlo come _id nella collection people"""
    return re.sub(r'\s+', '_', name.strip().lower())


def upsert_person(name, role=None, relevance='media', investigation_id=None, evidence_doc=None):
    """Inserisce o aggiorna una persona nella collection people"""
    if not name or not name.strip():
        return

    person_id = normalize_person_id(name)
    now = datetime.now()

    relevance_order = {'alta': 3, 'media': 2, 'bassa': 1}

    existing = people_collection.find_one({'_id': person_id})

    if existing:
        update = {'$set': {'last_updated': now}}

        if role:
            update.setdefault('$addToSet', {})['roles'] = role

        current_rel = existing.get('relevance', 'bassa')
        if relevance_order.get(relevance, 0) > relevance_order.get(current_rel, 0):
            update['$set']['relevance'] = relevance

        if investigation_id:
            inv_entry = {
                'investigation_id': investigation_id,
                'role': role or '',
                'evidence_doc': evidence_doc or '',
                'date': now,
            }
            update.setdefault('$push', {})['investigations'] = inv_entry

        if evidence_doc:
            update.setdefault('$addToSet', {})['all_documents'] = evidence_doc

        people_collection.update_one({'_id': person_id}, update)
    else:
        doc = {
            '_id': person_id,
            'name': name.strip(),
            'aliases': [],
            'roles': [role] if role else [],
            'relevance': relevance or 'media',
            'investigations': [],
            'dossier': None,
            'all_connections': [],
            'all_documents': [evidence_doc] if evidence_doc else [],
            'first_seen': now,
            'last_updated': now,
        }
        if investigation_id:
            doc['investigations'].append({
                'investigation_id': investigation_id,
                'role': role or '',
                'evidence_doc': evidence_doc or '',
                'date': now,
            })
        people_collection.insert_one(doc)


def upsert_people_from_investigation(investigation_id, analysis):
    """Estrae key_people dall'analisi e li inserisce/aggiorna nella collection people."""
    key_people = analysis.get('key_people', [])
    connections = analysis.get('connections', [])

    for person in key_people:
        name = person.get('name', '')
        if not name:
            continue
        upsert_person(
            name=name,
            role=person.get('role', ''),
            relevance=person.get('relevance', 'media'),
            investigation_id=investigation_id,
            evidence_doc=person.get('evidence_doc', ''),
        )

    for conn in connections:
        from_name = conn.get('from', '')
        to_name = conn.get('to', '')
        if from_name and to_name:
            from_id = normalize_person_id(from_name)
            to_id = normalize_person_id(to_name)
            people_collection.update_one(
                {'_id': from_id},
                {'$addToSet': {'all_connections': to_name}},
            )
            people_collection.update_one(
                {'_id': to_id},
                {'$addToSet': {'all_connections': from_name}},
            )

    identities = analysis.get('identities', {})
    if isinstance(identities, dict):
        for identity in identities.get('identities', []):
            canonical = identity.get('canonical_name', '')
            aliases = identity.get('aliases', [])
            if canonical and aliases:
                person_id = normalize_person_id(canonical)
                for alias in aliases:
                    if alias:
                        people_collection.update_one(
                            {'_id': person_id},
                            {'$addToSet': {'aliases': alias}},
                        )
