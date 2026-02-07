"""
/api/analyze POST + /api/analyze/status/<id> — 2 route + worker
"""
import uuid
import json
import threading
from datetime import datetime
from flask import Blueprint, jsonify, request
from app.services.pdf import download_pdf_text
from app.services.claude import get_anthropic_client, call_claude_with_retry
from app.services.settings import get_model, get_language_instruction
from app.extensions import analyses_collection

bp = Blueprint("analyze", __name__)

analyze_jobs = {}


def analyze_with_claude(documents, question):
    """Analizza documenti con Claude"""
    client = get_anthropic_client()

    context = ""
    for i, doc in enumerate(documents, 1):
        text = doc.get('full_text', '') or doc.get('text', '') or ''
        snippets = doc.get('snippets', [])
        if not text and snippets:
            text = '\n'.join(snippets)
        context += f"### Document {i}: {doc.get('title', 'Unknown')}\n{text[:5000]}\n\n---\n\n"

    prompt = f"""{context}

---

Analyze these documents from the Epstein Files and answer the following question.
Always cite the specific EFTA document code when referencing information.

QUESTION: {question}"""

    message = call_claude_with_retry(
        client, model=get_model(), max_tokens=4096,
        messages=[{"role": "user", "content": prompt + get_language_instruction()}],
    )
    return message.content[0].text


def run_analyze_job(job_id, documents, question, download_full):
    """Esegue analisi in background"""
    analyze_jobs[job_id]['status'] = 'running'
    analyze_jobs[job_id]['progress'] = 'Preparazione analisi...'

    try:
        if download_full:
            for i, doc in enumerate(documents):
                if doc.get('url') and not doc.get('full_text'):
                    analyze_jobs[job_id]['progress'] = f'Download PDF {i+1}/{len(documents)}...'
                    doc['full_text'] = download_pdf_text(doc['url'])

        analyze_jobs[job_id]['progress'] = 'Analisi AI in corso...'
        print(f"[ANALYZE JOB {job_id[:8]}] Analisi AI...", flush=True)

        result = analyze_with_claude(documents, question)

        analyze_jobs[job_id]['status'] = 'completed'
        analyze_jobs[job_id]['result'] = result
        analyze_jobs[job_id]['progress'] = 'Completato!'
        print(f"[ANALYZE JOB {job_id[:8]}] Completato!", flush=True)

        try:
            result_text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, default=str)
            analyses_collection.insert_one({
                'job_id': job_id,
                'date': datetime.now(),
                'question': question,
                'num_documents': len(documents),
                'result_text': result_text[:50000],
                'type': 'analysis'
            })
            print(f"[ANALYZE JOB {job_id[:8]}] Salvato in MongoDB", flush=True)
        except Exception as save_err:
            print(f"[ANALYZE JOB {job_id[:8]}] Errore salvataggio MongoDB: {save_err}", flush=True)

        try:
            from app.agents.vectordb import add_document_to_vectordb
            index_text = result_text[:15000] if isinstance(result_text, str) else str(result)[:15000]
            add_document_to_vectordb(
                url=f"analysis://{job_id}",
                title=f"Analisi: {question[:100]}",
                text=index_text,
                metadata={"type": "analysis", "job_id": job_id, "question": question[:200]}
            )
            print(f"[ANALYZE JOB {job_id[:8]}] Indicizzato in ChromaDB", flush=True)
        except Exception as idx_err:
            print(f"[ANALYZE JOB {job_id[:8]}] Errore indicizzazione ChromaDB: {idx_err}", flush=True)

    except Exception as e:
        import traceback
        traceback.print_exc()
        analyze_jobs[job_id]['status'] = 'error'
        analyze_jobs[job_id]['error'] = str(e)
        analyze_jobs[job_id]['progress'] = f'Errore: {str(e)}'


@bp.route('/api/analyze', methods=['POST'])
def api_analyze():
    """Avvia analisi in background"""
    data = request.json
    documents = data.get('documents', [])
    question = data.get('question', '')
    download_full = data.get('download_full', False)

    if not documents:
        return jsonify({"error": "Nessun documento selezionato"}), 400

    job_id = str(uuid.uuid4())
    analyze_jobs[job_id] = {
        'status': 'pending',
        'progress': 'In coda...',
        'result': None,
        'error': None
    }

    print(f"[ANALYZE] Nuovo job {job_id[:8]} - {len(documents)} documenti", flush=True)

    thread = threading.Thread(target=run_analyze_job, args=(job_id, documents, question, download_full))
    thread.daemon = True
    thread.start()

    return jsonify({'job_id': job_id, 'status': 'started'})


@bp.route('/api/analyze/status/<job_id>', methods=['GET'])
def api_analyze_status(job_id):
    """Controlla lo stato di un job analyze"""
    if job_id not in analyze_jobs:
        return jsonify({'error': 'Job non trovato'}), 404

    job = analyze_jobs[job_id]

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
