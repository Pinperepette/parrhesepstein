"""
/api/influence-network/* — 8 route + 2 worker
"""
import json
import uuid
import threading
from datetime import datetime
from pathlib import Path
from flask import Blueprint, jsonify, request, Response
from app.services.claude import get_anthropic_client, call_claude_with_retry
from app.services.settings import get_model, get_language_instruction
from app.services.justice_gov import search_justice_gov
from app.services.pdf import download_pdf_text
from app.config import ANALYSES_DIR
from app.extensions import analyses_collection, deep_analyses_collection

bp = Blueprint("influence", __name__)

influence_jobs = {}
deep_analysis_jobs = {}


def save_analysis_to_disk(job_id, target_orgs, depth, result):
    """Salva l'analisi su disco E su MongoDB"""
    filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{'-'.join(target_orgs[:3])}_{depth}.json"
    filepath = Path(ANALYSES_DIR) / filename

    data = {
        'id': job_id,
        'filename': filename,
        'date': datetime.now().isoformat(),
        'target_orgs': target_orgs,
        'depth': depth,
        'stats': {
            'organizations': len(result.get('target_organizations', {})),
            'intermediaries': len(result.get('intermediaries', {})),
            'connections': len(result.get('connections', [])),
            'key_documents': len(result.get('key_documents', []))
        },
        'result': result
    }

    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    try:
        data['_id'] = job_id
        data['type'] = 'influence_network'
        analyses_collection.replace_one({'_id': job_id}, data, upsert=True)
        print(f"[SAVE] Analisi salvata su MongoDB: {job_id[:8]}", flush=True)
    except Exception as e:
        print(f"[SAVE] Errore MongoDB: {e}", flush=True)

    print(f"[SAVE] Analisi salvata: {filename}", flush=True)
    return filename


def run_influence_analysis(job_id, target_orgs, depth):
    """Esegue l'analisi in background"""
    from app.agents.influence_analyzer import InfluenceNetworkAnalyzer

    influence_jobs[job_id]['status'] = 'running'
    influence_jobs[job_id]['progress'] = 'Avvio analisi...'

    try:
        client = None
        try:
            client = get_anthropic_client()
        except Exception:
            pass

        analyzer = InfluenceNetworkAnalyzer(anthropic_client=client, model=get_model(), lang_instruction=get_language_instruction())

        def progress_callback(msg):
            influence_jobs[job_id]['progress'] = msg
            print(f"[JOB {job_id[:8]}] {msg}", flush=True)

        result = analyzer.analyze_influence_network(
            target_orgs=target_orgs,
            depth=depth,
            progress_callback=progress_callback
        )

        influence_jobs[job_id]['status'] = 'completed'
        influence_jobs[job_id]['result'] = result
        influence_jobs[job_id]['progress'] = 'Completato!'
        print(f"[JOB {job_id[:8]}] Completato!", flush=True)

        save_analysis_to_disk(job_id, target_orgs, depth, result)

    except Exception as e:
        import traceback
        traceback.print_exc()
        influence_jobs[job_id]['status'] = 'error'
        influence_jobs[job_id]['error'] = str(e)
        influence_jobs[job_id]['progress'] = f'Errore: {str(e)}'


def run_deep_analysis(job_id, doc_ids, context):
    """Analizza in profondità i documenti specificati"""
    deep_analysis_jobs[job_id]['status'] = 'running'
    deep_analysis_jobs[job_id]['progress'] = 'Avvio analisi approfondita...'

    results = []

    try:
        client = get_anthropic_client()

        for i, doc_id in enumerate(doc_ids):
            deep_analysis_jobs[job_id]['progress'] = f'Analisi documento {i+1}/{len(doc_ids)}: {doc_id}...'
            print(f"[DEEP] Analisi {doc_id}", flush=True)

            search_result = search_justice_gov(doc_id, 0)

            if search_result.get('results'):
                doc = search_result['results'][0]
                url = doc.get('url', '')

                deep_analysis_jobs[job_id]['progress'] = f'Download {doc_id}...'
                text = download_pdf_text(url, use_ocr=True)

                if text and not text.startswith('[Errore'):
                    deep_analysis_jobs[job_id]['progress'] = f'Analisi AI {doc_id}...'

                    prompt = f"""Analizza questo documento degli Epstein Files in relazione alle connessioni con organizzazioni sanitarie internazionali (WHO, ICRC).

CONTESTO DELL'INDAGINE:
{context}

DOCUMENTO: {doc_id}
CONTENUTO:
{text[:15000]}

---

Fornisci un'analisi strutturata:

## 1. SINTESI DEL DOCUMENTO
Cosa contiene questo documento? (2-3 frasi)

## 2. ATTORI IDENTIFICATI
Lista delle persone/organizzazioni menzionate e il loro ruolo.

## 3. CONNESSIONI RILEVANTI
Quali connessioni emergono tra:
- Epstein/suoi associati e organizzazioni internazionali
- Flussi finanziari
- Eventi/meeting

## 4. DATE E TIMELINE
Quali date sono menzionate? Come si inseriscono nella timeline?

## 5. CITAZIONI CHIAVE
Le 2-3 frasi più significative del documento (cita testualmente).

## 6. LIVELLO DI RILEVANZA
Alto/Medio/Basso - e perché.

## 7. DOMANDE APERTE
Cosa resta da chiarire basandosi su questo documento?
"""

                    message = client.messages.create(
                        model=get_model(),
                        max_tokens=3000,
                        messages=[{"role": "user", "content": prompt + get_language_instruction()}]
                    )

                    results.append({
                        'doc_id': doc_id,
                        'url': url,
                        'title': doc.get('title', doc_id),
                        'text_length': len(text),
                        'analysis': message.content[0].text
                    })
                else:
                    results.append({
                        'doc_id': doc_id,
                        'error': 'Impossibile estrarre testo dal PDF'
                    })
            else:
                results.append({
                    'doc_id': doc_id,
                    'error': 'Documento non trovato'
                })

        deep_analysis_jobs[job_id]['status'] = 'completed'
        deep_analysis_jobs[job_id]['result'] = results
        deep_analysis_jobs[job_id]['progress'] = 'Completato!'
        print(f"[DEEP] Analisi completata: {len(results)} documenti", flush=True)

        try:
            deep_data = {
                '_id': job_id,
                'type': 'deep_analysis',
                'date': datetime.now().isoformat(),
                'doc_ids': doc_ids,
                'context': context,
                'results': results
            }
            deep_analyses_collection.replace_one({'_id': job_id}, deep_data, upsert=True)
            print(f"[DEEP] Salvato su MongoDB: {job_id[:8]}", flush=True)
        except Exception as e:
            print(f"[DEEP] Errore salvataggio MongoDB: {e}", flush=True)

    except Exception as e:
        import traceback
        traceback.print_exc()
        deep_analysis_jobs[job_id]['status'] = 'error'
        deep_analysis_jobs[job_id]['error'] = str(e)


@bp.route('/api/influence-network', methods=['POST'])
def api_influence_network():
    """Avvia analisi in background e restituisce job_id"""
    data = request.json
    target_orgs = data.get('target_orgs', None)
    depth = data.get('depth', 'medium')

    job_id = str(uuid.uuid4())
    influence_jobs[job_id] = {
        'status': 'pending',
        'progress': 'In coda...',
        'target_orgs': target_orgs,
        'depth': depth,
        'result': None,
        'error': None
    }

    print(f"[INFLUENCE] Nuovo job {job_id[:8]} - Orgs: {target_orgs}, Depth: {depth}", flush=True)

    thread = threading.Thread(target=run_influence_analysis, args=(job_id, target_orgs, depth))
    thread.daemon = True
    thread.start()

    return jsonify({'job_id': job_id, 'status': 'started'})


@bp.route('/api/influence-network/status/<job_id>', methods=['GET'])
def api_influence_status(job_id):
    """Controlla lo stato di un job"""
    if job_id not in influence_jobs:
        return jsonify({'error': 'Job non trovato'}), 404

    job = influence_jobs[job_id]

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


@bp.route('/api/influence-network/saved', methods=['GET'])
def api_list_saved_analyses():
    """Lista tutte le analisi salvate"""
    saved = []
    analyses_path = Path(ANALYSES_DIR)
    analyses_path.mkdir(exist_ok=True)

    for filepath in sorted(analyses_path.glob('*.json'), reverse=True):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
                saved.append({
                    'filename': filepath.name,
                    'date': data.get('date'),
                    'target_orgs': data.get('target_orgs', []),
                    'depth': data.get('depth'),
                    'stats': data.get('stats', {})
                })
        except Exception as e:
            print(f"[ERROR] Errore lettura {filepath}: {e}", flush=True)

    return jsonify({'analyses': saved})


@bp.route('/api/influence-network/saved/<filename>', methods=['GET'])
def api_load_saved_analysis(filename):
    """Carica un'analisi salvata"""
    filepath = Path(ANALYSES_DIR) / filename

    if not filepath.exists():
        return jsonify({'error': 'Analisi non trovata'}), 404

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/api/influence-network/saved/<filename>', methods=['DELETE'])
def api_delete_saved_analysis(filename):
    """Elimina un'analisi salvata"""
    filepath = Path(ANALYSES_DIR) / filename

    if not filepath.exists():
        return jsonify({'error': 'Analisi non trovata'}), 404

    try:
        filepath.unlink()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/api/influence-network/deep-analysis', methods=['POST'])
def api_deep_analysis():
    """Avvia analisi approfondita di documenti specifici"""
    data = request.json
    doc_ids = data.get('doc_ids', [])
    context = data.get('context', '')

    if not doc_ids:
        return jsonify({'error': 'Nessun documento specificato'}), 400

    job_id = str(uuid.uuid4())
    deep_analysis_jobs[job_id] = {
        'status': 'pending',
        'progress': 'In coda...',
        'doc_ids': doc_ids,
        'result': None,
        'error': None
    }

    print(f"[DEEP] Nuovo job {job_id[:8]} - Documenti: {doc_ids}", flush=True)

    thread = threading.Thread(target=run_deep_analysis, args=(job_id, doc_ids, context))
    thread.daemon = True
    thread.start()

    return jsonify({'job_id': job_id, 'status': 'started'})


@bp.route('/api/influence-network/deep-analysis/<job_id>', methods=['GET'])
def api_deep_analysis_status(job_id):
    """Controlla lo stato dell'analisi approfondita"""
    if job_id not in deep_analysis_jobs:
        return jsonify({'error': 'Job non trovato'}), 404

    job = deep_analysis_jobs[job_id]

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


@bp.route('/api/influence-network/export', methods=['POST'])
def api_influence_network_export():
    """Esporta l'analisi in formato Markdown"""
    from app.agents.influence_analyzer import InfluenceNetworkAnalyzer

    data = request.json

    try:
        analyzer = InfluenceNetworkAnalyzer()
        markdown = analyzer.export_to_markdown(data)

        return Response(
            markdown,
            mimetype='text/markdown; charset=utf-8',
            headers={'Content-Disposition': 'attachment; filename=analisi_rete_influenza.md'}
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500
