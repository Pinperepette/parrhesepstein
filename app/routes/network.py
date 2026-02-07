"""
/api/network POST + /api/network/status/<id> — 2 route + worker
"""
import uuid
import threading
from flask import Blueprint, jsonify, request
from app.services.justice_gov import search_justice_gov
from app.services.pdf import download_pdf_text

bp = Blueprint("network", __name__)

network_jobs = {}


def run_network_job(job_id, query, documents, download_full):
    """Esegue la generazione network in background"""
    from app.agents.network_agent import NetworkAgent

    network_jobs[job_id]['status'] = 'running'
    network_jobs[job_id]['progress'] = 'Ricerca documenti...'

    try:
        if not documents and query:
            all_results = []
            for page in range(3):
                network_jobs[job_id]['progress'] = f'Ricerca pagina {page+1}/3...'
                search_results = search_justice_gov(query, page=page)
                all_results.extend(search_results.get('results', []))
            documents = all_results

        network_jobs[job_id]['progress'] = f'Trovati {len(documents)} documenti'

        if download_full:
            docs_to_download = documents[:20]
            for i, doc in enumerate(docs_to_download):
                if doc.get('url') and not doc.get('full_text'):
                    network_jobs[job_id]['progress'] = f'Download PDF {i+1}/{len(docs_to_download)}...'
                    doc['full_text'] = download_pdf_text(doc['url'])

        network_jobs[job_id]['progress'] = 'Generazione grafo relazioni...'
        print(f"[NETWORK JOB {job_id[:8]}] Generazione grafo...", flush=True)

        agent = NetworkAgent()
        result = agent.map_network(documents)

        network_jobs[job_id]['status'] = 'completed'
        network_jobs[job_id]['result'] = result
        network_jobs[job_id]['progress'] = 'Completato!'
        print(f"[NETWORK JOB {job_id[:8]}] Completato!", flush=True)

    except Exception as e:
        import traceback
        traceback.print_exc()
        network_jobs[job_id]['status'] = 'error'
        network_jobs[job_id]['error'] = str(e)
        network_jobs[job_id]['progress'] = f'Errore: {str(e)}'


@bp.route('/api/network', methods=['POST'])
def api_network():
    """Avvia generazione network in background"""
    data = request.json
    documents = data.get('documents', [])
    query = data.get('query', '')
    download_full = data.get('download_full', False)

    job_id = str(uuid.uuid4())
    network_jobs[job_id] = {
        'status': 'pending',
        'progress': 'In coda...',
        'query': query,
        'result': None,
        'error': None
    }

    print(f"[NETWORK] Nuovo job {job_id[:8]} - Query: {query}", flush=True)

    thread = threading.Thread(target=run_network_job, args=(job_id, query, documents, download_full))
    thread.daemon = True
    thread.start()

    return jsonify({'job_id': job_id, 'status': 'started'})


@bp.route('/api/network/status/<job_id>', methods=['GET'])
def api_network_status(job_id):
    """Controlla lo stato di un job network"""
    if job_id not in network_jobs:
        return jsonify({'error': 'Job non trovato'}), 404

    job = network_jobs[job_id]

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
