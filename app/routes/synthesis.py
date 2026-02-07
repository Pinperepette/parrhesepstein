"""
/api/sintesi/*, /api/analyses/<id> DELETE — 7 route + 1 worker
"""
import uuid
import json
import threading
from datetime import datetime
from flask import Blueprint, jsonify, request
from app.services.claude import get_anthropic_client, call_claude_with_retry
from app.services.settings import get_model, get_language_instruction
from app.extensions import (
    analyses_collection, deep_analyses_collection,
    syntheses_collection,
)

bp = Blueprint("synthesis", __name__)

synthesis_jobs = {}


def run_synthesis_job(job_id, analysis_ids):
    """Esegue la sintesi in background"""
    synthesis_jobs[job_id]['status'] = 'running'
    synthesis_jobs[job_id]['progress'] = 'Raccolta dati...'

    try:
        client = get_anthropic_client()

        all_data = []
        all_persons = set()
        all_orgs = set()
        all_connections = []
        all_documents = []

        synthesis_jobs[job_id]['progress'] = f'Analisi di {len(analysis_ids)} elementi...'

        for aid in analysis_ids:
            analysis = analyses_collection.find_one({'_id': aid})
            if analysis:
                result = analysis.get('result', {})
                for name in result.get('intermediaries', {}).keys():
                    all_persons.add(name)
                for org in result.get('target_organizations', {}).keys():
                    all_orgs.add(org)
                all_connections.extend(result.get('connections', []))
                all_documents.extend(result.get('key_documents', []))
                if result.get('summary'):
                    all_data.append(f"### Analisi Rete ({analysis.get('date', 'N/A')}):\n{result['summary'][:3000]}")

            deep = deep_analyses_collection.find_one({'_id': aid})
            if deep:
                for doc_result in deep.get('results', []):
                    if doc_result.get('analysis'):
                        all_data.append(f"### Documento {doc_result.get('doc_id', 'N/A')}:\n{doc_result['analysis'][:2000]}")
                        all_documents.append({'doc_id': doc_result.get('doc_id'), 'title': doc_result.get('title', '')})


        synthesis_jobs[job_id]['progress'] = 'Generazione sintesi con AI...'

        context = f"""## DATI AGGREGATI DA {len(analysis_ids)} ANALISI

### PERSONE IDENTIFICATE ({len(all_persons)}):
{', '.join(sorted(all_persons))}

### ORGANIZZAZIONI ({len(all_orgs)}):
{', '.join(sorted(all_orgs))}

### CONNESSIONI DOCUMENTATE ({len(all_connections)}):
{chr(10).join([f"- {c.get('from', '?')} → {c.get('to', '?')}" for c in all_connections[:30]])}

### DOCUMENTI CHIAVE ({len(all_documents)}):
{chr(10).join([f"- {d.get('doc_id', d.get('title', 'N/A'))}" for d in all_documents[:20]])}

### ANALISI PRECEDENTI:
{chr(10).join(all_data[:5])}
"""

        prompt = f"""{context}

---

Sei un analista investigativo. Basandoti su TUTTI i dati aggregati sopra, genera una SINTESI FINALE UNIFICATA.

## 1. TESI CENTRALE
Qual è la tesi principale che emerge dall'insieme dei dati? (3-4 frasi potenti)

## 2. MAPPA DEL POTERE
Chi sono i nodi centrali della rete? Come si collegano?

## 3. MECCANISMI OPERATIVI
Come funzionava concretamente questa rete di influenza?

## 4. TIMELINE RICOSTRUITA
Quali eventi chiave emergono in ordine cronologico?

## 5. PROVE DOCUMENTALI PIÙ FORTI
Quali sono i 5 documenti/prove più schiaccianti?

## 6. IMPLICAZIONI
Cosa significa tutto questo per:
- La governance sanitaria globale
- La gestione delle pandemie
- La fiducia nelle istituzioni

## 7. CONCLUSIONI
Sintesi finale in 5 bullet point potenti.

## 8. FRASE D'IMPATTO
Una singola frase che riassuma tutto per un titolo di giornale.

Sii preciso, cita i documenti, non fare speculazioni non supportate dai dati."""

        message = client.messages.create(
            model=get_model(),
            max_tokens=6000,
            messages=[{"role": "user", "content": prompt + get_language_instruction()}]
        )

        synthesis = message.content[0].text

        synthesis_id = str(uuid.uuid4())
        synthesis_data = {
            '_id': synthesis_id,
            'date': datetime.now().isoformat(),
            'analysis_ids': analysis_ids,
            'persons': list(all_persons),
            'organizations': list(all_orgs),
            'connections_count': len(all_connections),
            'documents_count': len(all_documents),
            'synthesis': synthesis
        }
        syntheses_collection.insert_one(synthesis_data)

        synthesis_jobs[job_id]['status'] = 'completed'
        synthesis_jobs[job_id]['result'] = {
            'synthesis_id': synthesis_id,
            'synthesis': synthesis,
            'stats': {
                'persons': len(all_persons),
                'organizations': len(all_orgs),
                'connections': len(all_connections),
                'documents': len(all_documents)
            }
        }
        synthesis_jobs[job_id]['progress'] = 'Completato!'
        print(f"[SYNTHESIS] Completata: {synthesis_id[:8]}", flush=True)

    except Exception as e:
        import traceback
        traceback.print_exc()
        synthesis_jobs[job_id]['status'] = 'error'
        synthesis_jobs[job_id]['error'] = str(e)
        synthesis_jobs[job_id]['progress'] = f'Errore: {str(e)}'


@bp.route('/api/sintesi/all-analyses', methods=['GET'])
def api_get_all_analyses():
    """Recupera tutte le analisi da MongoDB"""
    try:
        network_analyses = list(analyses_collection.find({}, {'result': 0}).sort('date', -1))
        for a in network_analyses:
            a['_id'] = str(a['_id'])

        deep_analyses = list(deep_analyses_collection.find({}, {'results': 0}).sort('date', -1))
        for a in deep_analyses:
            a['_id'] = str(a['_id'])

        return jsonify({
            'network_analyses': network_analyses,
            'deep_analyses': deep_analyses,
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/api/sintesi/analysis/<analysis_id>', methods=['GET'])
def api_get_single_analysis(analysis_id):
    """Recupera una singola analisi completa"""
    try:
        analysis = analyses_collection.find_one({'_id': analysis_id})
        if analysis:
            analysis['_id'] = str(analysis['_id'])
            return jsonify(analysis)

        analysis = deep_analyses_collection.find_one({'_id': analysis_id})
        if analysis:
            analysis['_id'] = str(analysis['_id'])
            return jsonify(analysis)

        return jsonify({'error': 'Analisi non trovata'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/api/sintesi/generate', methods=['POST'])
def api_generate_synthesis():
    """Avvia generazione sintesi in background"""
    data = request.json
    analysis_ids = data.get('analysis_ids', [])

    if not analysis_ids:
        return jsonify({'error': 'Nessuna analisi selezionata'}), 400

    job_id = str(uuid.uuid4())
    synthesis_jobs[job_id] = {
        'status': 'pending',
        'progress': 'In coda...',
        'result': None,
        'error': None
    }

    print(f"[SYNTHESIS] Nuovo job {job_id[:8]} - {len(analysis_ids)} analisi", flush=True)

    thread = threading.Thread(target=run_synthesis_job, args=(job_id, analysis_ids))
    thread.daemon = True
    thread.start()

    return jsonify({'job_id': job_id, 'status': 'started'})


@bp.route('/api/sintesi/generate/<job_id>', methods=['GET'])
def api_synthesis_status(job_id):
    """Controlla lo stato della generazione sintesi"""
    if job_id not in synthesis_jobs:
        return jsonify({'error': 'Job non trovato'}), 404

    job = synthesis_jobs[job_id]

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


@bp.route('/api/sintesi/all', methods=['GET'])
def api_get_all_syntheses():
    """Recupera tutte le sintesi salvate"""
    try:
        syntheses = list(syntheses_collection.find().sort('date', -1))
        for s in syntheses:
            s['_id'] = str(s['_id'])
        return jsonify({'syntheses': syntheses})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/api/sintesi/delete/<item_id>', methods=['DELETE'])
def api_delete_synthesis(item_id):
    """Elimina una sintesi + rimuove da ChromaDB"""
    try:
        result = syntheses_collection.delete_one({'_id': item_id})
        if result.deleted_count > 0:
            try:
                from app.agents.vectordb import delete_from_vectordb
                delete_from_vectordb(f"synthesis://{item_id}")
            except Exception as e:
                print(f"[DELETE] Errore pulizia ChromaDB sintesi: {e}", flush=True)
            return jsonify({'success': True})
        return jsonify({'error': 'Sintesi non trovata'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/api/analyses/<analysis_id>', methods=['DELETE'])
def api_delete_analysis(analysis_id):
    """Elimina un'analisi (rete o deep) + rimuove da ChromaDB"""
    try:
        result = analyses_collection.delete_one({'_id': analysis_id})
        if result.deleted_count > 0:
            try:
                from app.agents.vectordb import delete_from_vectordb
                delete_from_vectordb(f"analysis://{analysis_id}")
            except Exception as e:
                print(f"[DELETE] Errore pulizia ChromaDB analisi: {e}", flush=True)
            return jsonify({'success': True, 'type': 'network'})

        result = deep_analyses_collection.delete_one({'_id': analysis_id})
        if result.deleted_count > 0:
            try:
                from app.agents.vectordb import delete_from_vectordb
                delete_from_vectordb(f"detective://{analysis_id}")
            except Exception as e:
                print(f"[DELETE] Errore pulizia ChromaDB deep: {e}", flush=True)
            return jsonify({'success': True, 'type': 'deep'})

        return jsonify({'error': 'Analisi non trovata'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500
