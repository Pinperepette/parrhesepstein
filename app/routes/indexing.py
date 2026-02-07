"""
/api/index-document, /api/index-batch,
/api/vectordb/index-all-local POST+GET — 4 route
"""
import os
import uuid
import threading
from flask import Blueprint, jsonify, request
from app.config import DOCUMENTS_DIR
from app.services.pdf import download_pdf_text
from app.services.jobs import job_manager

bp = Blueprint("indexing", __name__)


@bp.route('/api/index-document', methods=['POST'])
def api_index_document():
    """Indicizza un documento nel database vettoriale"""
    from app.agents.vectordb import add_document_to_vectordb

    data = request.json
    url = data.get('url', '')
    title = data.get('title', '')

    if not url:
        return jsonify({"error": "URL richiesto"}), 400

    text = download_pdf_text(url)

    if text.startswith('[Errore'):
        return jsonify({"error": text}), 500

    try:
        chunks = add_document_to_vectordb(url, title, text)
        return jsonify({"status": "ok", "chunks_indexed": chunks})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route('/api/index-batch', methods=['POST'])
def api_index_batch():
    """Indicizza un batch di documenti"""
    from app.agents.vectordb import add_document_to_vectordb

    data = request.json
    documents = data.get('documents', [])

    indexed = 0
    errors = []

    for doc in documents:
        url = doc.get('url', '')
        title = doc.get('title', '')

        if not url:
            continue

        text = download_pdf_text(url)

        if text.startswith('[Errore'):
            errors.append({"url": url, "error": text})
            continue

        try:
            add_document_to_vectordb(url, title, text)
            indexed += 1
        except Exception as e:
            errors.append({"url": url, "error": str(e)})

    return jsonify({
        "indexed": indexed,
        "errors": errors,
        "total": len(documents)
    })


vectordb_index_jobs = {}


@bp.route('/api/vectordb/index-all-local', methods=['POST'])
def api_vectordb_index_all_local():
    """Indicizza tutti i documenti locali in background"""
    from app.agents.vectordb import add_document_to_vectordb

    job_id = str(uuid.uuid4())
    vectordb_index_jobs[job_id] = {
        'status': 'running',
        'progress': 'Avvio indicizzazione...',
        'indexed': 0,
        'skipped': 0,
        'errors': [],
        'total': 0
    }

    def _index_all():
        try:
            txt_files = [f for f in os.listdir(DOCUMENTS_DIR) if f.endswith('.txt')]
            vectordb_index_jobs[job_id]['total'] = len(txt_files)

            for i, filename in enumerate(txt_files):
                doc_id = filename.replace('.txt', '')
                vectordb_index_jobs[job_id]['progress'] = f'Indicizzazione {i+1}/{len(txt_files)}: {doc_id}'

                try:
                    txt_path = os.path.join(DOCUMENTS_DIR, filename)
                    with open(txt_path, 'r', encoding='utf-8') as f:
                        text = f.read()

                    if not text.strip() or text.startswith('[Errore'):
                        vectordb_index_jobs[job_id]['skipped'] += 1
                        continue

                    url = f"local://documents/{doc_id}"
                    add_document_to_vectordb(url, doc_id, text, {'doc_id': doc_id})
                    vectordb_index_jobs[job_id]['indexed'] += 1
                except Exception as e:
                    vectordb_index_jobs[job_id]['errors'].append({'doc_id': doc_id, 'error': str(e)})

            vectordb_index_jobs[job_id]['status'] = 'completed'
            vectordb_index_jobs[job_id]['progress'] = 'Completato!'
            print(f"[INDEX-ALL] Completato: {vectordb_index_jobs[job_id]['indexed']} indicizzati", flush=True)
        except Exception as e:
            vectordb_index_jobs[job_id]['status'] = 'error'
            vectordb_index_jobs[job_id]['progress'] = f'Errore: {str(e)}'

    threading.Thread(target=_index_all, daemon=True).start()
    return jsonify({'job_id': job_id, 'status': 'started'})


@bp.route('/api/vectordb/index-all-local/<job_id>', methods=['GET'])
def api_vectordb_index_status(job_id):
    """Controlla stato indicizzazione"""
    if job_id not in vectordb_index_jobs:
        return jsonify({'error': 'Job non trovato'}), 404
    return jsonify(vectordb_index_jobs[job_id])
