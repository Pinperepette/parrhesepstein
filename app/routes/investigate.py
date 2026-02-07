"""
/api/investigate POST + /api/investigate/status/<id> — 2 route + worker
"""
import uuid
import threading
from datetime import datetime
from flask import Blueprint, jsonify, request
from app.services.justice_gov import search_justice_gov
from app.services.pdf import download_pdf_text
from app.services.claude import get_anthropic_client
from app.services.settings import get_model, get_language_instruction
from app.services.people import normalize_person_id
from app.extensions import people_collection

bp = Blueprint("investigate", __name__)

investigate_jobs = {}


def run_investigate_job(job_id, name, documents, download_full):
    """Esegue investigazione in background"""
    from app.agents.investigator import InvestigatorAgent

    investigate_jobs[job_id]['status'] = 'running'
    investigate_jobs[job_id]['progress'] = f'Ricerca documenti su {name}...'

    try:
        if not documents:
            investigate_jobs[job_id]['progress'] = f'Ricerca documenti su {name}...'
            search_results = search_justice_gov(name, page=0)
            documents = search_results.get('results', [])

        investigate_jobs[job_id]['progress'] = f'Trovati {len(documents)} documenti'

        if download_full:
            docs_to_download = documents[:10]
            for i, doc in enumerate(docs_to_download):
                if doc.get('url') and not doc.get('full_text'):
                    investigate_jobs[job_id]['progress'] = f'Download PDF {i+1}/{len(docs_to_download)}...'
                    doc['full_text'] = download_pdf_text(doc['url'])

        investigate_jobs[job_id]['progress'] = f'Generazione dossier su {name}...'
        print(f"[INVESTIGATE JOB {job_id[:8]}] Generazione dossier per {name}...", flush=True)

        client = get_anthropic_client()
        agent = InvestigatorAgent(client, model=get_model(), lang_instruction=get_language_instruction())

        person_id = normalize_person_id(name)
        existing_person = people_collection.find_one({'_id': person_id})
        existing_info = None
        if existing_person and existing_person.get('dossier'):
            existing_info = existing_person

        dossier = agent.investigate(name, documents, existing_info=existing_info)

        try:
            dossier_data = {
                'generated_at': datetime.now(),
                'documents_found': dossier.get('documents_found', 0),
                'ai_analysis': dossier.get('ai_analysis', ''),
                'mentions': dossier.get('mentions', []),
                'connections': dossier.get('connections', []),
                'timeline': dossier.get('timeline', []),
                'financial': dossier.get('financial', []),
                'red_flags': dossier.get('red_flags', []),
                'wikipedia': dossier.get('wikipedia', None)
            }
            people_collection.update_one(
                {'_id': person_id},
                {
                    '$set': {
                        'name': name.strip(),
                        'dossier': dossier_data,
                        'last_updated': datetime.now()
                    },
                    '$addToSet': {
                        'all_connections': {'$each': dossier.get('connections', [])[:20]}
                    }
                },
                upsert=True
            )
            people_collection.update_one(
                {'_id': person_id, 'first_seen': {'$exists': False}},
                {'$set': {'first_seen': datetime.now()}}
            )
            print(f"[INVESTIGATE JOB {job_id[:8]}] Dossier salvato nella collection people", flush=True)
        except Exception as pe:
            print(f"[INVESTIGATE JOB {job_id[:8]}] Errore salvataggio dossier people: {pe}", flush=True)

        investigate_jobs[job_id]['status'] = 'completed'
        investigate_jobs[job_id]['result'] = dossier
        investigate_jobs[job_id]['progress'] = 'Completato!'
        print(f"[INVESTIGATE JOB {job_id[:8]}] Completato!", flush=True)

    except Exception as e:
        import traceback
        traceback.print_exc()
        investigate_jobs[job_id]['status'] = 'error'
        investigate_jobs[job_id]['error'] = str(e)
        investigate_jobs[job_id]['progress'] = f'Errore: {str(e)}'


@bp.route('/api/investigate', methods=['POST'])
def api_investigate():
    """Avvia generazione dossier in background"""
    data = request.json
    name = data.get('name', '')
    documents = data.get('documents', [])
    download_full = data.get('download_full', True)

    if not name:
        return jsonify({"error": "Nome richiesto"}), 400

    job_id = str(uuid.uuid4())
    investigate_jobs[job_id] = {
        'status': 'pending',
        'progress': 'In coda...',
        'name': name,
        'result': None,
        'error': None
    }

    print(f"[INVESTIGATE] Nuovo job {job_id[:8]} - Nome: {name}", flush=True)

    thread = threading.Thread(target=run_investigate_job, args=(job_id, name, documents, download_full))
    thread.daemon = True
    thread.start()

    return jsonify({'job_id': job_id, 'status': 'started'})


@bp.route('/api/investigate/status/<job_id>', methods=['GET'])
def api_investigate_status(job_id):
    """Controlla lo stato di un job investigate"""
    if job_id not in investigate_jobs:
        return jsonify({'error': 'Job non trovato'}), 404

    job = investigate_jobs[job_id]

    response = {
        'job_id': job_id,
        'status': job['status'],
        'progress': job['progress']
    }

    if job['status'] == 'completed':
        response['result'] = job['result']
    elif job['status'] == 'error':
        response['error'] = job['error']

    return jsonify(response)
