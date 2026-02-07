"""
/api/investigations/merge/*, /api/investigations/deep-dive/*,
/api/investigations/merges, /api/investigations/list — 8 route + 2 worker
"""
import re
import json
import uuid
import threading
from datetime import datetime
from flask import Blueprint, jsonify, request
from app.services.justice_gov import search_justice_gov
from app.services.pdf import download_pdf_text
from app.services.claude import get_anthropic_client, call_claude_with_retry
from app.services.settings import get_model, get_language_instruction
from app.extensions import (
    crew_investigations_collection, merged_investigations_collection,
    deep_analyses_collection,
)

bp = Blueprint("merge", __name__)

merge_jobs = {}
deep_dive_jobs = {}


def run_merge_background(merge_id, investigation_ids):
    """Esegue il merge in background"""
    try:
        investigations = []
        all_people = {}
        all_connections = []
        all_doc_ids = set()

        for inv_id in investigation_ids:
            inv = crew_investigations_collection.find_one({'_id': inv_id})
            if inv:
                investigations.append(inv)

                if inv.get('analysis') and inv['analysis'].get('key_people'):
                    for person in inv['analysis']['key_people']:
                        name = person.get('name', '')
                        if name:
                            if name not in all_people:
                                all_people[name] = {'name': name, 'role': person.get('role', ''), 'count': 0, 'investigations': []}
                            all_people[name]['count'] += 1
                            all_people[name]['investigations'].append(inv.get('objective', '')[:50])

                if inv.get('analysis'):
                    if inv['analysis'].get('connections'):
                        for conn in inv['analysis']['connections']:
                            all_connections.append(conn)
                            evidence = conn.get('evidence', '')
                            doc_match = re.search(r'EFTA\d+', evidence)
                            if doc_match:
                                all_doc_ids.add(doc_match.group())

                    if inv['analysis'].get('key_people'):
                        for person in inv['analysis']['key_people']:
                            doc = person.get('evidence_doc', '')
                            if doc and doc.startswith('EFTA'):
                                all_doc_ids.add(doc)

                if inv.get('report'):
                    doc_matches = re.findall(r'EFTA\d+', inv['report'])
                    all_doc_ids.update(doc_matches)

        common_people = [p for p in all_people.values() if p['count'] >= 2]
        common_people.sort(key=lambda x: x['count'], reverse=True)

        critical_docs_content = {}
        critical_doc_ids = list(all_doc_ids)[:10]

        for doc_id in critical_doc_ids:
            try:
                search_result = search_justice_gov(doc_id)
                if search_result.get('results'):
                    doc = search_result['results'][0]
                    doc_url = doc.get('url', '')

                    if doc_url:
                        text = download_pdf_text(doc_url, use_ocr=False, use_claude_vision=False)
                        if text and not text.startswith('[Errore'):
                            critical_docs_content[doc_id] = {
                                'title': doc.get('title', ''),
                                'text': text[:3000],
                                'snippets': doc.get('snippets', [])
                            }
            except Exception as e:
                print(f"Errore scaricamento {doc_id}: {e}")
                continue

        context = "# INVESTIGAZIONI DA UNIRE\n\n"
        for inv in investigations:
            context += f"## {inv.get('objective', 'N/A')}\n"
            context += f"Documenti trovati: {inv.get('documents_found', 0)}\n"
            if inv.get('report'):
                context += f"Report: {inv['report'][:2500]}\n"
            context += "\n---\n\n"

        if critical_docs_content:
            context += "\n# DOCUMENTI CRITICI SCARICATI E ANALIZZATI\n\n"
            for doc_id, doc_data in critical_docs_content.items():
                context += f"## {doc_id}: {doc_data['title']}\n"
                context += f"Contenuto:\n{doc_data['text'][:2000]}\n"
                context += "\n---\n\n"

        client = get_anthropic_client()

        prompt = f"""Sei un investigatore esperto. Analizza queste {len(investigations)} investigazioni sui documenti Epstein E i documenti critici che ho scaricato per te.

CONTESTO:
{context}

Rispondi in JSON con questa struttura:
{{
    "summary": "Sintesi di come le investigazioni si collegano",
    "critical_findings": ["scoperta critica 1", "scoperta 2"],
    "connections": [
        {{"from": "persona/entità 1", "to": "persona/entità 2", "relationship": "tipo relazione", "evidence": "EFTAXXXXXX"}}
    ],
    "patterns": ["pattern identificato 1", "pattern 2"],
    "document_analysis": [
        {{"doc_id": "EFTAXXXXX", "key_content": "cosa c'è di importante", "red_flags": ["elemento sospetto"]}}
    ],
    "recommendations": ["cosa investigare dopo 1", "cosa 2"]
}}"""

        response = call_claude_with_retry(
            client,
            model=get_model(),
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt + get_language_instruction()}]
        )

        response_text = response.content[0].text

        try:
            json_match = re.search(r'\{[\s\S]*\}', response_text)
            if json_match:
                result = json.loads(json_match.group())
            else:
                result = {'full_report': response_text}
        except json.JSONDecodeError:
            result = {'full_report': response_text}

        result['common_people'] = common_people[:10]
        result['documents_analyzed'] = list(critical_docs_content.keys())
        result['total_documents_found'] = len(all_doc_ids)

        leads_to_follow = []
        all_mentioned_docs = set()
        if result.get('full_report'):
            all_mentioned_docs.update(re.findall(r'EFTA\d+', result['full_report']))
        if result.get('critical_findings'):
            for f in result['critical_findings']:
                all_mentioned_docs.update(re.findall(r'EFTA\d+', str(f)))

        not_analyzed = all_mentioned_docs - set(critical_docs_content.keys())

        for doc_id in list(not_analyzed)[:5]:
            reason = "Menzionato nell'analisi"
            if result.get('full_report') and doc_id in result['full_report']:
                idx = result['full_report'].find(doc_id)
                start = max(0, idx - 100)
                end = min(len(result['full_report']), idx + 150)
                reason = result['full_report'][start:end].replace('\n', ' ')

            leads_to_follow.append({
                'doc_id': doc_id,
                'reason': reason,
                'priority': 'high' if any(kw in reason.lower() for kw in ['trafficking', 'transfer', 'fbi', 'payment']) else 'medium'
            })

        result['leads_to_follow'] = leads_to_follow
        result['can_go_deeper'] = len(leads_to_follow) > 0

        merged_investigations_collection.update_one(
            {'_id': merge_id},
            {'$set': {
                'status': 'completed',
                'result': result
            }}
        )

    except Exception as e:
        import traceback
        merged_investigations_collection.update_one(
            {'_id': merge_id},
            {'$set': {
                'status': 'error',
                'error': str(e),
                'traceback': traceback.format_exc()
            }}
        )


def run_deep_dive_background(job_id, doc_id, context, doc_url, doc_title):
    """Esegue deep-dive in background"""
    try:
        deep_dive_jobs[job_id]['progress'] = 'Download PDF in corso...'
        print(f"[DEEP-DIVE {job_id[:8]}] Download PDF: {doc_url}", flush=True)

        text = download_pdf_text(doc_url, use_ocr=False, use_claude_vision=False)
        if not text or text.startswith('[Errore'):
            deep_dive_jobs[job_id]['status'] = 'error'
            deep_dive_jobs[job_id]['error'] = f'Impossibile scaricare documento: {text}'
            return

        deep_dive_jobs[job_id]['progress'] = 'Analisi AI in corso...'
        print(f"[DEEP-DIVE {job_id[:8]}] Analisi Claude...", flush=True)

        client = get_anthropic_client()

        prompt = f"""Sei un investigatore esperto. Analizza questo documento degli Epstein Files in profondità.

DOCUMENTO: {doc_id}
TITOLO: {doc_title}
CONTESTO INVESTIGAZIONE: {context}

CONTENUTO COMPLETO:
{text[:8000]}

ISTRUZIONI:
1. Analizza OGNI dettaglio rilevante
2. Estrai TUTTI i nomi di persone
3. Estrai TUTTI gli importi finanziari
4. Cerca riferimenti a trafficking, minori, abusi
5. Identifica altri documenti collegati da investigare

Rispondi in JSON:
{{
    "document_summary": "Cosa contiene questo documento (dettagliato)",
    "key_findings": ["scoperta importante 1", "scoperta 2", "scoperta 3"],
    "people": [
        {{"name": "Nome Persona", "role": "ruolo/contesto", "suspicious": true}}
    ],
    "financial_transactions": [
        {{"amount": "$X", "from": "chi", "to": "chi", "date": "quando", "purpose": "scopo"}}
    ],
    "red_flags": ["elemento sospetto che richiede attenzione"],
    "related_documents": ["EFTA... da investigare"],
    "trafficking_references": ["citazione esatta se presente"],
    "conclusion": "Cosa significa questo documento per l'investigazione",
    "next_steps": ["cosa investigare dopo"]
}}"""

        response = call_claude_with_retry(
            client,
            model=get_model(),
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt + get_language_instruction()}]
        )

        response_text = response.content[0].text

        try:
            json_match = re.search(r'\{[\s\S]*\}', response_text)
            if json_match:
                analysis = json.loads(json_match.group())
            else:
                analysis = {'document_summary': response_text}
        except Exception:
            analysis = {'document_summary': response_text}

        analysis['doc_id'] = doc_id
        analysis['title'] = doc_title
        analysis['url'] = doc_url
        analysis['text_length'] = len(text)

        deep_dive_jobs[job_id]['status'] = 'completed'
        deep_dive_jobs[job_id]['result'] = analysis
        deep_dive_jobs[job_id]['progress'] = 'Completato!'
        print(f"[DEEP-DIVE {job_id[:8]}] Completato!", flush=True)

        try:
            from app.agents.vectordb import add_document_to_vectordb
            dd_text = json.dumps(analysis, ensure_ascii=False, default=str)[:15000]
            add_document_to_vectordb(
                url=f"deep-dive://{doc_id}/{job_id}",
                title=f"Deep Dive: {doc_id}",
                text=dd_text,
                metadata={"type": "deep_dive", "doc_id": doc_id, "job_id": job_id}
            )
            print(f"[DEEP-DIVE {job_id[:8]}] Indicizzato in ChromaDB", flush=True)
        except Exception as idx_err:
            print(f"[DEEP-DIVE {job_id[:8]}] Errore indicizzazione ChromaDB: {idx_err}", flush=True)

        try:
            deep_analyses_collection.insert_one({
                'job_id': job_id,
                'date': datetime.now(),
                'doc_id': doc_id,
                'doc_url': doc_url,
                'doc_title': doc_title,
                'context': context[:500] if context else '',
                'result': analysis,
                'type': 'deep_dive'
            })
            print(f"[DEEP-DIVE {job_id[:8]}] Salvato in MongoDB", flush=True)
        except Exception as save_err:
            print(f"[DEEP-DIVE {job_id[:8]}] Errore salvataggio MongoDB: {save_err}", flush=True)

    except Exception as e:
        import traceback
        deep_dive_jobs[job_id]['status'] = 'error'
        deep_dive_jobs[job_id]['error'] = str(e)
        deep_dive_jobs[job_id]['traceback'] = traceback.format_exc()
        print(f"[DEEP-DIVE {job_id[:8]}] Errore: {e}", flush=True)


@bp.route('/api/investigations/list')
def api_investigations_list():
    """Lista tutte le investigazioni salvate"""
    try:
        investigations = list(crew_investigations_collection.find())
        result = []
        for inv in investigations:
            people = []
            if inv.get('analysis') and inv['analysis'].get('key_people'):
                people = [p['name'] for p in inv['analysis']['key_people'][:5]]

            result.append({
                'id': str(inv.get('_id', '')),
                'objective': inv.get('objective', 'N/A'),
                'date': str(inv.get('date', '')),
                'documents_found': inv.get('documents_found', 0),
                'people': people,
                'has_network': bool(inv.get('network_data'))
            })

        return jsonify({'investigations': result})
    except Exception as e:
        return jsonify({'error': str(e), 'investigations': []})


@bp.route('/api/investigations/merge', methods=['POST'])
def api_investigations_merge():
    """Avvia merge in background e ritorna subito"""
    data = request.json
    investigation_ids = data.get('investigation_ids', [])

    if len(investigation_ids) < 2:
        return jsonify({'error': 'Seleziona almeno 2 investigazioni'})

    try:
        merge_id = str(uuid.uuid4())

        inv_names = []
        for inv_id in investigation_ids:
            inv = crew_investigations_collection.find_one({'_id': inv_id})
            if inv:
                inv_names.append(inv.get('objective', '')[:100])

        merge_doc = {
            '_id': merge_id,
            'date': datetime.now(),
            'investigation_ids': investigation_ids,
            'investigations_merged': inv_names,
            'status': 'processing',
            'result': None
        }
        merged_investigations_collection.insert_one(merge_doc)

        thread = threading.Thread(target=run_merge_background, args=(merge_id, investigation_ids))
        thread.daemon = True
        thread.start()

        return jsonify({'merge_id': merge_id, 'status': 'processing'})

    except Exception as e:
        import traceback
        return jsonify({'error': str(e), 'traceback': traceback.format_exc()})


@bp.route('/api/investigations/merge/status/<merge_id>')
def api_merge_status(merge_id):
    """Controlla lo stato di un merge in corso"""
    try:
        merge = merged_investigations_collection.find_one({'_id': merge_id})
        if not merge:
            return jsonify({'error': 'Merge non trovato'})

        status = merge.get('status', 'unknown')
        if status == 'completed':
            return jsonify({
                'status': 'completed',
                'result': merge.get('result', {})
            })
        elif status == 'error':
            return jsonify({
                'status': 'error',
                'error': merge.get('error', 'Errore sconosciuto')
            })
        else:
            return jsonify({'status': 'processing'})
    except Exception as e:
        return jsonify({'error': str(e)})


@bp.route('/api/investigations/deep-dive', methods=['POST'])
def api_deep_dive():
    """Approfondisce un documento specifico (asincrono)"""
    data = request.json
    doc_id = data.get('doc_id', '')
    context = data.get('context', '')

    if not doc_id:
        return jsonify({'error': 'doc_id richiesto'})

    doc_id_upper = doc_id.upper().strip()
    is_valid_doc_id = (
        doc_id_upper.startswith('EFTA') or
        doc_id_upper.startswith('GOV') or
        doc_id_upper.startswith('DOC') or
        doc_id_upper.startswith('USAO') or
        re.match(r'^[A-Z]{2,4}\d{5,}', doc_id_upper)
    )

    if not is_valid_doc_id:
        return jsonify({
            'error': f'"{doc_id}" non sembra un ID documento valido.',
            'suggestion': 'Usa il campo "Cerca altri documenti" per trovare documenti relativi a una persona o termine, poi clicca "Analizza" sul documento specifico.',
            'is_search_term': True
        })

    try:
        search_result = search_justice_gov(doc_id)
        if not search_result.get('results'):
            return jsonify({'error': f'Documento {doc_id} non trovato'})

        doc = search_result['results'][0]
        doc_url = doc.get('url', '')

        if not doc_url:
            return jsonify({'error': 'URL documento non disponibile'})

        job_id = str(uuid.uuid4())
        deep_dive_jobs[job_id] = {
            'status': 'running',
            'progress': 'Avvio analisi...',
            'doc_id': doc_id,
            'result': None,
            'error': None
        }

        thread = threading.Thread(
            target=run_deep_dive_background,
            args=(job_id, doc_id, context, doc_url, doc.get('title', ''))
        )
        thread.start()

        return jsonify({'job_id': job_id, 'status': 'started'})

    except Exception as e:
        import traceback
        return jsonify({'error': str(e), 'traceback': traceback.format_exc()})


@bp.route('/api/investigations/deep-dive/status/<job_id>')
def api_deep_dive_status(job_id):
    """Controlla stato del deep-dive"""
    if job_id not in deep_dive_jobs:
        return jsonify({'error': 'Job non trovato', 'status': 'not_found'})

    job = deep_dive_jobs[job_id]
    return jsonify({
        'status': job['status'],
        'progress': job['progress'],
        'doc_id': job.get('doc_id', ''),
        'result': job.get('result'),
        'error': job.get('error')
    })


@bp.route('/api/investigations/merge/integrate', methods=['POST'])
def api_merge_integrate():
    """Integra nuove scoperte nell'analisi e ri-sintetizza tutto"""
    data = request.json
    merge_id = data.get('merge_id', '')
    new_findings = data.get('new_findings', {})

    if not merge_id:
        return jsonify({'error': 'merge_id richiesto'})

    try:
        merge = merged_investigations_collection.find_one({'_id': merge_id})
        if not merge:
            return jsonify({'error': 'Merge non trovato'})

        existing_result = merge.get('result', {})

        deep_dives = existing_result.get('deep_dives', [])
        deep_dives.append(new_findings)
        existing_result['deep_dives'] = deep_dives

        context = f"""# ANALISI PRECEDENTE COMPLETA
Sommario: {existing_result.get('summary', '')}

Scoperte Critiche: {json.dumps(existing_result.get('critical_findings', []), ensure_ascii=False)}

Connessioni: {json.dumps(existing_result.get('connections', []), ensure_ascii=False)}

Pattern: {json.dumps(existing_result.get('patterns', []), ensure_ascii=False)}

Scoperta Chiave Precedente: {existing_result.get('key_insight', '')}

Raccomandazioni Precedenti: {json.dumps(existing_result.get('recommendations', []), ensure_ascii=False)}

Persone Comuni: {json.dumps(existing_result.get('common_people', []), ensure_ascii=False)}

Analisi Documenti Precedente: {json.dumps(existing_result.get('document_analysis', []), ensure_ascii=False)}

Lead Aperti: {json.dumps(existing_result.get('leads_to_follow', []), ensure_ascii=False)}

# NUOVA ANALISI APPROFONDITA: {new_findings.get('doc_id', 'N/A')}
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

        prompt = f"""Sei un investigatore esperto. Devi AGGIORNARE e INTEGRARE l'analisi con le nuove scoperte dal documento appena analizzato in profondità.

{context}

ISTRUZIONI CRITICHE:
1. Integra le NUOVE scoperte nell'analisi complessiva - NON perdere nulla delle scoperte precedenti
2. Aggiorna il sommario includendo le nuove informazioni acquisite
3. Aggiungi nuove scoperte critiche trovate nel deep dive
4. Aggiungi/aggiorna connessioni tra persone/entità - INCLUDI quelle vecchie + quelle nuove
5. Identifica nuovi pattern emergenti confrontando vecchie e nuove scoperte
6. Aggiorna le raccomandazioni basandoti su TUTTO il quadro
7. Aggiorna la lista persone comuni se il deep dive ha rivelato nuove persone
8. Aggiorna i lead: rimuovi quelli già investigati, aggiungi nuovi emersi dal deep dive
9. INCLUDI nell'analisi documenti TUTTI i documenti analizzati (precedenti + nuovo)

Rispondi SOLO in JSON con l'analisi COMPLETA AGGIORNATA (vecchio + nuovo integrati):
{{
    "summary": "Sommario AGGIORNATO che include TUTTE le scoperte (vecchie + nuove dal deep dive)",
    "critical_findings": ["TUTTE le scoperte critiche, vecchie + nuove integrate"],
    "connections": [{{"from": "A", "to": "B", "type": "relazione", "evidence": "doc"}}],
    "document_analysis": [{{"doc_id": "...", "key_content": "...", "relevance": "..."}}],
    "common_people": [{{"name": "Nome", "role": "ruolo", "count": 1}}],
    "patterns": ["pattern identificati includendo nuove scoperte"],
    "key_insight": "La scoperta più importante AGGIORNATA con nuove evidenze",
    "recommendations": ["prossimi passi investigativi AGGIORNATI"],
    "leads_to_follow": [{{"doc_id": "EFTA...", "reason": "motivo", "priority": "high"}}]
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
                updated_result = json.loads(json_match.group())
            else:
                updated_result = existing_result
        except Exception:
            updated_result = existing_result

        updated_result['deep_dives'] = deep_dives

        docs_analyzed = list(existing_result.get('documents_analyzed', []))
        new_doc_id = new_findings.get('doc_id', '')
        if new_doc_id and new_doc_id not in docs_analyzed:
            docs_analyzed.append(new_doc_id)
        updated_result['documents_analyzed'] = docs_analyzed

        if 'common_people' not in updated_result or not updated_result['common_people']:
            updated_result['common_people'] = existing_result.get('common_people', [])
        updated_result['total_documents_found'] = existing_result.get('total_documents_found', 0)
        updated_result['last_updated'] = datetime.now().isoformat()

        if 'leads_to_follow' not in updated_result:
            existing_leads = existing_result.get('leads_to_follow', [])
            updated_result['leads_to_follow'] = [
                l for l in existing_leads if l.get('doc_id') != new_doc_id
            ]

        merged_investigations_collection.update_one(
            {'_id': merge_id},
            {'$set': {'result': updated_result}}
        )

        return jsonify(updated_result)

    except Exception as e:
        import traceback
        return jsonify({'error': str(e), 'traceback': traceback.format_exc()})


@bp.route('/api/investigations/merges')
def api_merges_list():
    """Lista tutti i merge salvati"""
    try:
        merges = list(merged_investigations_collection.find().sort('date', -1))
        result = []
        for m in merges:
            result.append({
                'id': str(m.get('_id', '')),
                'date': str(m.get('date', '')),
                'investigations_merged': m.get('investigations_merged', []),
                'summary': m.get('result', {}).get('summary', '')[:200] if m.get('result') else ''
            })
        return jsonify({'merges': result})
    except Exception as e:
        return jsonify({'error': str(e), 'merges': []})


@bp.route('/api/investigations/merge/<merge_id>')
def api_merge_get(merge_id):
    """Recupera un merge specifico"""
    try:
        merge = merged_investigations_collection.find_one({'_id': merge_id})
        if merge:
            return jsonify({
                'id': str(merge.get('_id', '')),
                'date': str(merge.get('date', '')),
                'investigations_merged': merge.get('investigations_merged', []),
                'result': merge.get('result', {})
            })
        return jsonify({'error': 'Merge non trovato'})
    except Exception as e:
        return jsonify({'error': str(e)})


@bp.route('/api/investigations/merge/<merge_id>', methods=['DELETE'])
def api_merge_delete(merge_id):
    """Elimina un merge salvato + rimuove da ChromaDB"""
    try:
        result = merged_investigations_collection.delete_one({'_id': merge_id})
        if result.deleted_count > 0:
            try:
                from app.agents.vectordb import delete_from_vectordb
                delete_from_vectordb(f"merge://{merge_id}")
            except Exception as e:
                print(f"[DELETE] Errore pulizia ChromaDB merge: {e}", flush=True)
            return jsonify({'success': True, 'message': 'Merge eliminato'})
        return jsonify({'error': 'Merge non trovato'})
    except Exception as e:
        return jsonify({'error': str(e)})
