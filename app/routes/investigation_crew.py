"""
/api/investigation/*, /api/meta-investigation/*, /api/investigations/delete-all — 12 route + 3 worker
"""
import re
import json
import uuid
import threading
from datetime import datetime
from flask import Blueprint, jsonify, request, Response
from app.services.claude import get_anthropic_client, get_claude_api_key, get_anthropic_base_url, call_claude_with_retry
from app.services.settings import get_model, get_language_instruction
from app.services.people import upsert_people_from_investigation
from app.services.fact_checker import verify_citations
from app.services.network_builder import build_investigation_network
from app.services.merge_logic import build_continuation_context, merge_investigation_results, resynthesize_report
from app.extensions import (
    crew_investigations_collection, people_collection,
    analyses_collection, deep_analyses_collection,
    merged_investigations_collection, syntheses_collection,
    searches_collection, db_epstein,
)

bp = Blueprint("investigation_crew", __name__)

investigation_jobs = {}
continuation_jobs = {}
meta_investigation_jobs = {}


def run_investigation_job(job_id, objective):
    """Esegue l'investigazione multi-agente in background"""
    from app.agents.investigation_crew import run_investigation

    investigation_jobs[job_id]['status'] = 'running'
    investigation_jobs[job_id]['progress'] = 'Avvio team investigativo...'

    def progress_callback(msg):
        investigation_jobs[job_id]['progress'] = msg
        print(f"[INVESTIGATION {job_id[:8]}] {msg}", flush=True)

    try:
        api_key = get_claude_api_key()
        if not api_key:
            raise ValueError("Chiave API Claude non configurata")

        known_people = None
        try:
            known_people_cursor = people_collection.find(
                {},
                {'name': 1, 'roles': 1, 'relevance': 1, 'all_connections': 1}
            ).sort('last_updated', -1).limit(30)
            known_people = list(known_people_cursor)
            if known_people:
                progress_callback(f"Caricate {len(known_people)} persone note come contesto")
        except Exception as pe:
            print(f"[INVESTIGATION {job_id[:8]}] Errore caricamento persone note: {pe}", flush=True)

        base_url = get_anthropic_base_url()
        result = run_investigation(objective, api_key, progress_callback, known_people=known_people,
                                   model=get_model(), lang_instruction=get_language_instruction(),
                                   base_url=base_url)

        if result.get('success'):
            investigation_id = str(uuid.uuid4())
            investigation_data = {
                '_id': investigation_id,
                'date': datetime.now(),
                'objective': objective,
                'strategy': result.get('strategy', {}),
                'documents_found': result.get('documents_found', 0),
                'search_stats': result.get('search_stats', []),
                'analysis': result.get('analysis', {}),
                'follow_up': result.get('follow_up', {}),
                'report': result.get('report', ''),
                'banking': result.get('banking', {}),
                'identities': result.get('identities', {}),
                'cipher': result.get('cipher', {}),
                'network_data': build_investigation_network(result.get('analysis', {}), result.get('banking', {}))
            }

            try:
                progress_callback("Fact-checker: Verifica citazioni EFTA...")
                citation_check = verify_citations(result.get('report', ''))
                investigation_data['citation_verification'] = citation_check
                v = citation_check['verified']
                t = citation_check['total_citations']
                progress_callback(f"Fact-checker: {v}/{t} citazioni verificate")
            except Exception as fc_err:
                print(f"[INVESTIGATION {job_id[:8]}] Errore fact-checker: {fc_err}", flush=True)

            crew_investigations_collection.insert_one(investigation_data)
            result['investigation_id'] = investigation_id
            if investigation_data.get('citation_verification'):
                result['citation_verification'] = investigation_data['citation_verification']
            print(f"[INVESTIGATION {job_id[:8]}] Salvato con ID: {investigation_id}", flush=True)

            try:
                from app.agents.vectordb import add_document_to_vectordb
                report_text = result.get('report', '')
                if report_text and len(report_text) > 50:
                    add_document_to_vectordb(
                        url=f"investigation://{investigation_id}",
                        title=f"Investigazione: {objective[:100]}",
                        text=report_text[:15000],
                        metadata={"type": "crew_investigation", "investigation_id": investigation_id, "objective": objective[:200]}
                    )
                    print(f"[INVESTIGATION {job_id[:8]}] Indicizzato in ChromaDB", flush=True)
            except Exception as idx_err:
                print(f"[INVESTIGATION {job_id[:8]}] Errore indicizzazione ChromaDB: {idx_err}", flush=True)

            try:
                analysis_with_identities = dict(result.get('analysis', {}))
                analysis_with_identities['identities'] = result.get('identities', {})
                upsert_people_from_investigation(investigation_id, analysis_with_identities)
                print(f"[INVESTIGATION {job_id[:8]}] Persone salvate nella collection people", flush=True)
            except Exception as pe:
                print(f"[INVESTIGATION {job_id[:8]}] Errore salvataggio persone: {pe}", flush=True)

        investigation_jobs[job_id]['status'] = 'completed'
        investigation_jobs[job_id]['result'] = result
        investigation_jobs[job_id]['progress'] = 'Investigazione completata!'
        print(f"[INVESTIGATION {job_id[:8]}] Completato!", flush=True)

    except Exception as e:
        import traceback
        traceback.print_exc()
        investigation_jobs[job_id]['status'] = 'error'
        investigation_jobs[job_id]['error'] = str(e)
        investigation_jobs[job_id]['progress'] = f'Errore: {str(e)}'


def run_continuation_job(job_id, investigation_id, new_objective):
    """Esegue la continuazione dell'investigazione in background"""
    from app.agents.investigation_crew import run_investigation_with_context

    continuation_jobs[job_id]['status'] = 'running'
    continuation_jobs[job_id]['progress'] = 'Caricamento investigazione precedente...'

    def progress_callback(msg):
        continuation_jobs[job_id]['progress'] = msg
        print(f"[CONTINUATION {job_id[:8]}] {msg}", flush=True)

    try:
        api_key = get_claude_api_key()
        if not api_key:
            raise ValueError("Chiave API Claude non configurata")

        investigation = crew_investigations_collection.find_one({'_id': investigation_id})
        if not investigation:
            raise ValueError("Investigazione non trovata")

        progress_callback("Costruzione contesto investigativo...")
        context = build_continuation_context(investigation)

        known_people = None
        try:
            known_people_cursor = people_collection.find(
                {},
                {'name': 1, 'roles': 1, 'relevance': 1, 'all_connections': 1}
            ).sort('last_updated', -1).limit(30)
            known_people = list(known_people_cursor)
        except Exception as pe:
            print(f"[CONTINUATION {job_id[:8]}] Errore caricamento persone note: {pe}", flush=True)

        base_url = get_anthropic_base_url()
        new_result = run_investigation_with_context(new_objective, context, api_key, progress_callback, known_people=known_people,
                                                    model=get_model(), lang_instruction=get_language_instruction(),
                                                    base_url=base_url)

        if not new_result.get('success'):
            raise ValueError(new_result.get('error', 'Investigazione fallita'))

        progress_callback("Sintetizzatore: Unione risultati...")
        merged = merge_investigation_results(investigation, new_result, new_objective)

        progress_callback("Sintetizzatore: Riscrittura report unificato...")
        merged_report = resynthesize_report(
            investigation, new_result,
            merged['analysis'], merged['follow_up'],
            new_objective
        )

        update_data = {
            'analysis': merged['analysis'],
            'strategy': merged['strategy'],
            'follow_up': merged['follow_up'],
            'search_stats': merged['search_stats'],
            'documents_found': merged['documents_found'],
            'continuation_history': merged['continuation_history'],
            'network_data': merged['network_data'],
            'banking': merged.get('banking', {}),
            'identities': merged.get('identities', {}),
            'cipher': merged.get('cipher', {}),
            'report': merged_report,
            'last_updated': datetime.now()
        }

        try:
            progress_callback("Fact-checker: Verifica citazioni EFTA...")
            citation_check = verify_citations(merged_report)
            update_data['citation_verification'] = citation_check
            v = citation_check['verified']
            t = citation_check['total_citations']
            progress_callback(f"Fact-checker: {v}/{t} citazioni verificate")
        except Exception as fc_err:
            print(f"[CONTINUATION {job_id[:8]}] Errore fact-checker: {fc_err}", flush=True)

        crew_investigations_collection.update_one(
            {'_id': investigation_id},
            {'$set': update_data}
        )

        try:
            from app.agents.vectordb import add_document_to_vectordb
            if merged_report and len(merged_report) > 50:
                add_document_to_vectordb(
                    url=f"investigation://{investigation_id}",
                    title=f"Investigazione (aggiornata): {new_objective[:100]}",
                    text=merged_report[:15000],
                    metadata={"type": "crew_investigation", "investigation_id": investigation_id, "objective": new_objective[:200], "continuation": True}
                )
                print(f"[CONTINUATION {job_id[:8]}] Report aggiornato indicizzato in ChromaDB", flush=True)
        except Exception as idx_err:
            print(f"[CONTINUATION {job_id[:8]}] Errore indicizzazione ChromaDB: {idx_err}", flush=True)

        try:
            merged_analysis_with_identities = dict(merged['analysis'])
            merged_analysis_with_identities['identities'] = merged.get('identities', {})
            upsert_people_from_investigation(investigation_id, merged_analysis_with_identities)
            print(f"[CONTINUATION {job_id[:8]}] Persone aggiornate nella collection people", flush=True)
        except Exception as pe:
            print(f"[CONTINUATION {job_id[:8]}] Errore salvataggio persone: {pe}", flush=True)

        result = {
            'success': True,
            'investigation_id': investigation_id,
            'documents_found': merged['documents_found'],
            'analysis': merged['analysis'],
            'follow_up': merged['follow_up'],
            'report': merged_report,
            'network_data': merged['network_data'],
            'search_stats': merged['search_stats'],
            'continuation_history': merged['continuation_history'],
            'banking': merged.get('banking', {}),
            'identities': merged.get('identities', {}),
            'cipher': merged.get('cipher', {}),
            'deep_dives': investigation.get('deep_dives', []),
            'citation_verification': update_data.get('citation_verification'),
        }

        continuation_jobs[job_id]['status'] = 'completed'
        continuation_jobs[job_id]['result'] = result
        continuation_jobs[job_id]['progress'] = 'Investigazione completata!'
        print(f"[CONTINUATION {job_id[:8]}] Completato!", flush=True)

    except Exception as e:
        import traceback
        traceback.print_exc()
        continuation_jobs[job_id]['status'] = 'error'
        continuation_jobs[job_id]['error'] = str(e)
        continuation_jobs[job_id]['progress'] = f'Errore: {str(e)}'


def run_meta_investigation_job(job_id, investigation_ids=None):
    """Esegue la meta-investigazione in background"""
    from app.agents.meta_investigator import run_meta_investigation

    meta_investigation_jobs[job_id]['status'] = 'running'
    meta_investigation_jobs[job_id]['progress'] = 'Caricamento investigazioni...'

    def progress_callback(msg):
        meta_investigation_jobs[job_id]['progress'] = msg
        print(f"[META {job_id[:8]}] {msg}", flush=True)

    try:
        api_key = get_claude_api_key()
        if not api_key:
            raise ValueError("Chiave API Claude non configurata")

        if investigation_ids:
            investigations = list(crew_investigations_collection.find({'_id': {'$in': investigation_ids}}))
        else:
            investigations = list(crew_investigations_collection.find().sort('date', -1).limit(10))

        if len(investigations) < 2:
            raise ValueError("Servono almeno 2 investigazioni da confrontare")

        progress_callback(f"Analisi di {len(investigations)} investigazioni...")

        base_url = get_anthropic_base_url()
        result = run_meta_investigation(investigations, api_key, progress_callback,
                                        model=get_model(), lang_instruction=get_language_instruction(),
                                        base_url=base_url)

        if result.get('success'):
            meta_id = str(uuid.uuid4())
            meta_data = {
                '_id': meta_id,
                'date': datetime.now(),
                'investigations_analyzed': result.get('investigations_analyzed', 0),
                'analysis': result.get('analysis', {}),
                'verdict': result.get('verdict', '')
            }
            db_epstein["meta_investigations"].insert_one(meta_data)
            result['meta_id'] = meta_id

        meta_investigation_jobs[job_id]['status'] = 'completed'
        meta_investigation_jobs[job_id]['result'] = result
        meta_investigation_jobs[job_id]['progress'] = 'Meta-investigazione completata!'

    except Exception as e:
        import traceback
        traceback.print_exc()
        meta_investigation_jobs[job_id]['status'] = 'error'
        meta_investigation_jobs[job_id]['error'] = str(e)
        meta_investigation_jobs[job_id]['progress'] = f'Errore: {str(e)}'


@bp.route('/api/investigation', methods=['POST'])
def api_investigation():
    """Avvia un'investigazione multi-agente"""
    data = request.json
    objective = data.get('objective', '')

    if not objective:
        return jsonify({"error": "Obiettivo richiesto"}), 400

    job_id = str(uuid.uuid4())
    investigation_jobs[job_id] = {
        'status': 'pending',
        'progress': 'In coda...',
        'objective': objective,
        'result': None,
        'error': None
    }

    print(f"[INVESTIGATION] Nuovo job {job_id[:8]} - Obiettivo: {objective[:50]}...", flush=True)

    thread = threading.Thread(target=run_investigation_job, args=(job_id, objective))
    thread.daemon = True
    thread.start()

    return jsonify({'job_id': job_id, 'status': 'started'})


@bp.route('/api/investigation/status/<job_id>', methods=['GET'])
def api_investigation_status(job_id):
    """Controlla lo stato di un'investigazione"""
    if job_id not in investigation_jobs:
        return jsonify({'error': 'Job non trovato'}), 404

    job = investigation_jobs[job_id]

    response = {
        'job_id': job_id,
        'status': job['status'],
        'progress': job['progress']
    }

    if job['status'] == 'completed':
        response['result'] = job['result']
    elif job['status'] == 'error':
        response['error'] = job['error']

    return Response(
        json.dumps(response, ensure_ascii=False),
        mimetype='application/json; charset=utf-8'
    )


@bp.route('/api/investigation/list', methods=['GET'])
def api_investigation_list():
    """Lista tutte le investigazioni salvate in MongoDB"""
    try:
        investigations = list(crew_investigations_collection.find().sort('date', -1))
        result = []
        for inv in investigations:
            result.append({
                'id': inv['_id'],
                'date': inv['date'].isoformat() if inv.get('date') else '',
                'objective': inv.get('objective', ''),
                'documents_found': inv.get('documents_found', 0),
                'connections_count': len(inv.get('network_data', {}).get('edges', [])),
                'people_count': len(inv.get('analysis', {}).get('key_people', []))
            })
        return jsonify({'investigations': result})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/api/investigation/<investigation_id>', methods=['GET'])
def api_get_investigation(investigation_id):
    """Recupera una singola investigazione salvata"""
    try:
        investigation = crew_investigations_collection.find_one({'_id': investigation_id})
        if not investigation:
            return jsonify({'error': 'Investigazione non trovata'}), 404

        investigation['date'] = investigation['date'].isoformat() if investigation.get('date') else ''
        if investigation.get('last_updated'):
            investigation['last_updated'] = investigation['last_updated'].isoformat()

        return jsonify(investigation)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/api/investigation/<investigation_id>', methods=['DELETE'])
def api_delete_investigation(investigation_id):
    """Elimina un'investigazione salvata + persone collegate + ChromaDB"""
    try:
        result = crew_investigations_collection.delete_one({'_id': investigation_id})
        if result.deleted_count > 0:
            deleted_people = 0
            try:
                people_with_inv = people_collection.find({
                    'investigations.investigation_id': investigation_id
                })
                for person in people_with_inv:
                    remaining = [inv for inv in person.get('investigations', [])
                                 if inv.get('investigation_id') != investigation_id]
                    if not remaining:
                        people_collection.delete_one({'_id': person['_id']})
                        deleted_people += 1
                    else:
                        people_collection.update_one(
                            {'_id': person['_id']},
                            {'$pull': {'investigations': {'investigation_id': investigation_id}}}
                        )
            except Exception as e:
                print(f"[DELETE] Errore pulizia persone: {e}", flush=True)

            try:
                from app.agents.vectordb import delete_from_vectordb
                delete_from_vectordb(f"investigation://{investigation_id}")
                delete_from_vectordb(f"deep-dive://{investigation_id}")
            except Exception as e:
                print(f"[DELETE] Errore pulizia ChromaDB investigazione: {e}", flush=True)
            return jsonify({'success': True, 'message': f'Investigation deleted ({deleted_people} people removed)'})
        else:
            return jsonify({'error': 'Investigazione non trovata'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/api/investigations/delete-all', methods=['DELETE'])
def api_delete_all_investigations():
    """Elimina TUTTE le investigazioni + persone + analisi + ChromaDB"""
    try:
        counts = {}

        r = crew_investigations_collection.delete_many({})
        counts['investigations'] = r.deleted_count

        r = analyses_collection.delete_many({})
        counts['analyses'] = r.deleted_count

        r = deep_analyses_collection.delete_many({})
        counts['deep_analyses'] = r.deleted_count

        r = merged_investigations_collection.delete_many({})
        counts['merges'] = r.deleted_count

        r = syntheses_collection.delete_many({})
        counts['syntheses'] = r.deleted_count

        r = people_collection.delete_many({})
        counts['people'] = r.deleted_count

        r = searches_collection.delete_many({})
        counts['searches'] = r.deleted_count

        try:
            from app.agents.vectordb import get_or_create_collection, chroma_client
            collection = get_or_create_collection()
            chroma_client.delete_collection("epstein_docs")
            counts['chromadb'] = 'reset'
        except Exception as e:
            counts['chromadb_error'] = str(e)

        total = sum(v for v in counts.values() if isinstance(v, int))
        return jsonify({
            'success': True,
            'message': f'Deleted {total} items total',
            'details': counts
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/api/investigation/integrate', methods=['POST'])
def api_investigation_integrate():
    """Integra nuove scoperte (deep dive) nell'investigazione e ri-sintetizza"""
    data = request.json
    investigation_id = data.get('investigation_id', '')
    new_findings = data.get('new_findings', {})

    if not investigation_id:
        return jsonify({'error': 'investigation_id richiesto'})

    try:
        investigation = crew_investigations_collection.find_one({'_id': investigation_id})
        if not investigation:
            return jsonify({'error': 'Investigazione non trovata'})

        existing_analysis = investigation.get('analysis', {})
        existing_report = investigation.get('report', '')
        existing_follow_up = investigation.get('follow_up', {})

        deep_dives = investigation.get('deep_dives', [])
        deep_dives.append(new_findings)

        docs_found = investigation.get('documents_found', 0)
        new_doc_id = new_findings.get('doc_id', '')

        context = f"""# INVESTIGAZIONE ORIGINALE
Obiettivo: {investigation.get('objective', '')}

## Analisi Precedente
Persone chiave: {json.dumps(existing_analysis.get('key_people', []), ensure_ascii=False)}
Connessioni: {json.dumps(existing_analysis.get('connections', []), ensure_ascii=False)}
Prove significative: {json.dumps(existing_analysis.get('significant_evidence', []), ensure_ascii=False)}
Timeline: {json.dumps(existing_analysis.get('timeline', []), ensure_ascii=False)}

## Report Precedente (sommario)
{existing_report[:3000] if existing_report else 'N/A'}

## Follow-up suggeriti
{json.dumps(existing_follow_up, ensure_ascii=False)}

# NUOVA ANALISI APPROFONDITA: {new_doc_id}
{json.dumps(new_findings, indent=2, ensure_ascii=False)}

# TUTTE LE ANALISI APPROFONDITE PRECEDENTI
"""
        for dd in deep_dives[:-1]:
            context += f"\n## {dd.get('doc_id', 'N/A')}\n"
            context += f"Scoperte: {json.dumps(dd.get('key_findings', []), ensure_ascii=False)}\n"
            context += f"Red Flags: {json.dumps(dd.get('red_flags', []), ensure_ascii=False)}\n"
            if dd.get('financial_transactions'):
                context += f"Transazioni: {json.dumps(dd.get('financial_transactions', []), ensure_ascii=False)}\n"
            if dd.get('trafficking_references'):
                context += f"Trafficking: {json.dumps(dd.get('trafficking_references', []), ensure_ascii=False)}\n"
            if dd.get('conclusion'):
                context += f"Conclusione: {dd.get('conclusion', '')}\n"

        client = get_anthropic_client()

        prompt = f"""Sei un investigatore esperto. Devi RISCRIVERE l'analisi COMPLETA dell'investigazione integrando le nuove scoperte dal documento {new_doc_id} appena analizzato.

{context}

ISTRUZIONI CRITICHE:
1. Riscrivi il report COMPLETO integrando le nuove scoperte - NON una sezione aggiuntiva, ma il report INTERO AGGIORNATO
2. MANTIENI tutte le persone chiave precedenti e AGGIUNGI quelle nuove
3. MANTIENI tutte le connessioni precedenti e AGGIUNGI quelle nuove
4. MANTIENI tutte le prove precedenti e AGGIUNGI quelle nuove dal deep dive
5. Aggiorna la timeline se ci sono nuovi eventi
6. Il sommario del report deve riflettere TUTTE le scoperte (vecchie + nuove)
7. Aggiorna i prossimi passi basandoti sul quadro COMPLETO aggiornato

Rispondi SOLO in JSON:
{{
    "analysis": {{
        "key_people": [{{"name": "...", "role": "...", "relevance": "alta/media/bassa"}}],
        "connections": [{{"from": "A", "to": "B", "type": "relazione", "evidence": "doc"}}],
        "significant_evidence": [{{"document": "EFTA...", "content": "...", "importance": "critica/alta/media"}}],
        "timeline": [{{"date": "...", "event": "..."}}]
    }},
    "report": "Report COMPLETO AGGIORNATO in markdown con ## headers. Deve includere TUTTE le scoperte vecchie + nuove integrate.",
    "follow_up": {{
        "critical_questions": ["domande aggiornate"],
        "leads_to_follow": ["nuove piste"],
        "suggested_searches": ["termini di ricerca"]
    }}
}}"""

        response = call_claude_with_retry(
            client,
            model=get_model(),
            max_tokens=8000,
            messages=[{"role": "user", "content": prompt + get_language_instruction()}]
        )

        response_text = response.content[0].text

        try:
            json_match = re.search(r'\{[\s\S]*\}', response_text)
            if json_match:
                updated = json.loads(json_match.group())
            else:
                updated = {}
        except Exception:
            updated = {}

        update_data = {
            'deep_dives': deep_dives,
            'last_updated': datetime.now()
        }

        if updated.get('analysis'):
            update_data['analysis'] = updated['analysis']

        if updated.get('report'):
            update_data['report'] = updated['report']

        if updated.get('follow_up'):
            update_data['follow_up'] = updated['follow_up']

        if updated.get('analysis'):
            update_data['network_data'] = build_investigation_network(updated['analysis'])

        crew_investigations_collection.update_one(
            {'_id': investigation_id},
            {'$set': update_data}
        )

        try:
            from app.agents.vectordb import add_document_to_vectordb
            report_text = update_data.get('report', '')
            if report_text and len(report_text) > 50:
                add_document_to_vectordb(
                    url=f"investigation://{investigation_id}",
                    title=f"Investigazione (deep-dive {new_doc_id}): {investigation.get('objective', '')[:100]}",
                    text=report_text[:15000],
                    metadata={"type": "crew_investigation", "investigation_id": investigation_id, "deep_dive_doc": new_doc_id}
                )
                print(f"[INTEGRATE] Report aggiornato indicizzato in ChromaDB", flush=True)
        except Exception as idx_err:
            print(f"[INTEGRATE] Errore indicizzazione ChromaDB: {idx_err}", flush=True)

        try:
            analysis_to_upsert = update_data.get('analysis', existing_analysis)
            upsert_people_from_investigation(investigation_id, analysis_to_upsert)
        except Exception as pe:
            print(f"[INTEGRATE] Errore salvataggio persone: {pe}", flush=True)

        return jsonify({
            'success': True,
            'documents_found': docs_found,
            'analysis': update_data.get('analysis', existing_analysis),
            'follow_up': update_data.get('follow_up', existing_follow_up),
            'report': update_data.get('report', existing_report),
            'network_data': update_data.get('network_data', investigation.get('network_data', {})),
            'deep_dives': deep_dives,
            'investigation_id': investigation_id
        })

    except Exception as e:
        import traceback
        return jsonify({'error': str(e), 'traceback': traceback.format_exc()})


@bp.route('/api/investigation/<investigation_id>/continue', methods=['POST'])
def api_investigation_continue(investigation_id):
    """Continua un'investigazione esistente con un nuovo obiettivo"""
    data = request.json
    new_objective = data.get('objective', '')

    if not new_objective:
        return jsonify({"error": "Obiettivo richiesto"}), 400

    if not investigation_id:
        return jsonify({"error": "investigation_id richiesto"}), 400

    investigation = crew_investigations_collection.find_one({'_id': investigation_id})
    if not investigation:
        return jsonify({"error": "Investigazione non trovata"}), 404

    job_id = str(uuid.uuid4())
    continuation_jobs[job_id] = {
        'status': 'pending',
        'progress': 'In coda...',
        'objective': new_objective,
        'investigation_id': investigation_id,
        'result': None,
        'error': None
    }

    print(f"[CONTINUATION] Nuovo job {job_id[:8]} - Inv: {investigation_id[:8]} - Obiettivo: {new_objective[:50]}...", flush=True)

    thread = threading.Thread(target=run_continuation_job, args=(job_id, investigation_id, new_objective))
    thread.daemon = True
    thread.start()

    return jsonify({'job_id': job_id, 'status': 'started'})


@bp.route('/api/investigation/continue/status/<job_id>', methods=['GET'])
def api_investigation_continue_status(job_id):
    """Controlla lo stato di una continuazione investigativa"""
    if job_id not in continuation_jobs:
        return jsonify({'error': 'Job non trovato'}), 404

    job = continuation_jobs[job_id]

    response = {
        'job_id': job_id,
        'status': job['status'],
        'progress': job['progress']
    }

    if job['status'] == 'completed':
        response['result'] = job['result']
    elif job['status'] == 'error':
        response['error'] = job['error']

    return Response(
        json.dumps(response, ensure_ascii=False),
        mimetype='application/json; charset=utf-8'
    )


@bp.route('/api/meta-investigation', methods=['POST'])
def api_meta_investigation():
    """Avvia una meta-investigazione"""
    data = request.json or {}
    investigation_ids = data.get('investigation_ids', None)

    job_id = str(uuid.uuid4())
    meta_investigation_jobs[job_id] = {
        'status': 'pending',
        'progress': 'In coda...',
        'result': None,
        'error': None
    }

    thread = threading.Thread(target=run_meta_investigation_job, args=(job_id, investigation_ids))
    thread.daemon = True
    thread.start()

    return jsonify({'job_id': job_id, 'status': 'started'})


@bp.route('/api/meta-investigation/status/<job_id>', methods=['GET'])
def api_meta_investigation_status(job_id):
    """Controlla lo stato di una meta-investigazione"""
    if job_id not in meta_investigation_jobs:
        return jsonify({'error': 'Job non trovato'}), 404

    job = meta_investigation_jobs[job_id]

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
