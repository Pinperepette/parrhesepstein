"""
Logica di merge per investigazioni: build_continuation_context,
merge_investigation_results, resynthesize_report.
"""
import json
from datetime import datetime
from app.services.claude import get_anthropic_client, call_claude_with_retry
from app.services.settings import get_model, get_language_instruction
from app.services.network_builder import build_investigation_network


def build_continuation_context(existing):
    """Estrae contesto compatto da un'investigazione esistente per la continuazione"""
    analysis = existing.get('analysis', {})
    follow_up = existing.get('follow_up', {})
    strategy = existing.get('strategy', {})

    previous_terms = strategy.get('primary_terms', []) + strategy.get('secondary_terms', [])
    previous_terms += strategy.get('people_to_investigate', [])

    people_found = [p.get('name', '') for p in analysis.get('key_people', []) if p.get('name')]

    connections_found = [
        f"{c.get('from', '')} -> {c.get('to', '')} ({c.get('type', '')})"
        for c in analysis.get('connections', [])
    ]

    open_questions = follow_up.get('critical_questions', [])
    suggested_searches = follow_up.get('suggested_searches', [])
    leads = follow_up.get('leads_to_follow', [])

    continuation_history = existing.get('continuation_history', [])

    return {
        'original_objective': existing.get('objective', ''),
        'previous_search_terms': previous_terms,
        'people_already_found': people_found,
        'connections_already_found': connections_found,
        'open_questions': open_questions,
        'suggested_searches': suggested_searches,
        'leads_to_follow': leads,
        'continuation_history': continuation_history,
    }


def merge_investigation_results(existing, new_result, new_objective):
    """Merge deterministico dei risultati nuovi con quelli esistenti"""
    existing_analysis = existing.get('analysis', {})
    new_analysis = new_result.get('analysis', {})

    # key_people
    relevance_order = {'alta': 3, 'media': 2, 'bassa': 1}
    people_map = {}
    for p in existing_analysis.get('key_people', []):
        name = p.get('name', '')
        if name:
            people_map[name.lower()] = p
    for p in new_analysis.get('key_people', []):
        name = p.get('name', '')
        if name:
            key = name.lower()
            if key in people_map:
                old_rel = relevance_order.get(people_map[key].get('relevance', 'bassa'), 1)
                new_rel = relevance_order.get(p.get('relevance', 'bassa'), 1)
                if new_rel > old_rel:
                    people_map[key]['relevance'] = p.get('relevance', 'bassa')
                if p.get('role') and p.get('role') != people_map[key].get('role'):
                    people_map[key]['role'] = people_map[key].get('role', '') + '; ' + p.get('role', '')
            else:
                people_map[key] = p
    merged_people = list(people_map.values())

    # connections
    conn_set = set()
    merged_connections = []
    for c in existing_analysis.get('connections', []) + new_analysis.get('connections', []):
        key = f"{c.get('from', '')}|{c.get('to', '')}".lower()
        if key not in conn_set:
            conn_set.add(key)
            merged_connections.append(c)

    # significant_evidence
    evidence_set = set()
    merged_evidence = []
    for e in existing_analysis.get('significant_evidence', []) + new_analysis.get('significant_evidence', []):
        doc = e.get('document', '')
        if doc not in evidence_set:
            evidence_set.add(doc)
            merged_evidence.append(e)

    # timeline
    timeline_set = set()
    merged_timeline = []
    for t in existing_analysis.get('timeline', []) + new_analysis.get('timeline', []):
        key = f"{t.get('date', '')}|{t.get('event', '')}".lower()
        if key not in timeline_set:
            timeline_set.add(key)
            merged_timeline.append(t)
    merged_timeline.sort(key=lambda t: t.get('date', ''))

    locations = list(set(existing_analysis.get('locations', []) + new_analysis.get('locations', [])))
    patterns = list(set(existing_analysis.get('patterns', []) + new_analysis.get('patterns', [])))

    # strategy
    existing_strategy = existing.get('strategy', {})
    new_strategy = new_result.get('strategy', {})
    merged_strategy = {
        'primary_terms': list(set(existing_strategy.get('primary_terms', []) + new_strategy.get('primary_terms', []))),
        'secondary_terms': list(set(existing_strategy.get('secondary_terms', []) + new_strategy.get('secondary_terms', []))),
        'people_to_investigate': list(set(existing_strategy.get('people_to_investigate', []) + new_strategy.get('people_to_investigate', []))),
        'patterns_to_find': list(set(existing_strategy.get('patterns_to_find', []) + new_strategy.get('patterns_to_find', []))),
        'key_questions': list(set(existing_strategy.get('key_questions', []) + new_strategy.get('key_questions', []))),
    }

    # follow_up
    existing_follow = existing.get('follow_up', {})
    new_follow = new_result.get('follow_up', {})
    merged_follow = {
        'critical_questions': list(set(existing_follow.get('critical_questions', []) + new_follow.get('critical_questions', [])))[:15],
        'suggested_searches': list(set(existing_follow.get('suggested_searches', []) + new_follow.get('suggested_searches', [])))[:15],
        'leads_to_follow': list(set(existing_follow.get('leads_to_follow', []) + new_follow.get('leads_to_follow', [])))[:10],
        'inconsistencies': list(set(existing_follow.get('inconsistencies', []) + new_follow.get('inconsistencies', []))),
    }

    merged_search_stats = existing.get('search_stats', []) + new_result.get('search_stats', [])
    merged_docs_found = existing.get('documents_found', 0) + new_result.get('documents_found', 0)

    continuation_history = existing.get('continuation_history', [])
    continuation_history.append({
        'date': datetime.now().isoformat(),
        'objective': new_objective,
        'documents_found': new_result.get('documents_found', 0),
    })

    merged_analysis = {
        'key_people': merged_people,
        'connections': merged_connections,
        'significant_evidence': merged_evidence,
        'timeline': merged_timeline,
        'locations': locations,
        'patterns': patterns,
    }

    # banking
    existing_banking = existing.get('banking', {})
    new_banking = new_result.get('banking', {})
    if existing_banking or new_banking:
        bank_map = {}
        for b in (existing_banking.get('banks', []) if isinstance(existing_banking, dict) else []):
            name = b.get('name', '')
            if name:
                bank_map[name.lower()] = b
        for b in (new_banking.get('banks', []) if isinstance(new_banking, dict) else []):
            name = b.get('name', '')
            if name and name.lower() not in bank_map:
                bank_map[name.lower()] = b

        tx_set = set()
        merged_transactions = []
        for tx in (existing_banking.get('transactions', []) if isinstance(existing_banking, dict) else []) + \
                  (new_banking.get('transactions', []) if isinstance(new_banking, dict) else []):
            tx_key = f"{tx.get('from_entity', '')}|{tx.get('to_entity', '')}|{tx.get('amount', '')}".lower()
            if tx_key not in tx_set:
                tx_set.add(tx_key)
                merged_transactions.append(tx)

        merged_banking = {
            'banks': list(bank_map.values()),
            'transactions': merged_transactions,
            'money_flows': (existing_banking.get('money_flows', []) if isinstance(existing_banking, dict) else []) +
                           (new_banking.get('money_flows', []) if isinstance(new_banking, dict) else []),
            'offshore': (existing_banking.get('offshore', []) if isinstance(existing_banking, dict) else []) +
                        (new_banking.get('offshore', []) if isinstance(new_banking, dict) else []),
            'red_flags': (existing_banking.get('red_flags', []) if isinstance(existing_banking, dict) else []) +
                         (new_banking.get('red_flags', []) if isinstance(new_banking, dict) else []),
        }
    else:
        merged_banking = {}

    # identities
    existing_identities = existing.get('identities', {})
    new_identities = new_result.get('identities', {})
    if existing_identities or new_identities:
        id_map = {}
        for ident in (existing_identities.get('identities', []) if isinstance(existing_identities, dict) else []):
            canonical = ident.get('canonical_name', '')
            if canonical:
                id_map[canonical.lower()] = ident
        for ident in (new_identities.get('identities', []) if isinstance(new_identities, dict) else []):
            canonical = ident.get('canonical_name', '')
            if canonical:
                key = canonical.lower()
                if key in id_map:
                    existing_aliases = set(id_map[key].get('aliases', []))
                    new_aliases = set(ident.get('aliases', []))
                    id_map[key]['aliases'] = list(existing_aliases | new_aliases)
                    id_map[key].setdefault('evidence', []).extend(ident.get('evidence', []))
                else:
                    id_map[key] = ident
        merged_identities = {
            'identities': list(id_map.values()),
            'nickname_patterns': list(set(
                (existing_identities.get('nickname_patterns', []) if isinstance(existing_identities, dict) else []) +
                (new_identities.get('nickname_patterns', []) if isinstance(new_identities, dict) else [])
            )),
            'unresolved_references': (existing_identities.get('unresolved_references', []) if isinstance(existing_identities, dict) else []) +
                                     (new_identities.get('unresolved_references', []) if isinstance(new_identities, dict) else []),
        }
    else:
        merged_identities = {}

    # cipher
    existing_cipher = existing.get('cipher', {})
    new_cipher = new_result.get('cipher', {})
    if existing_cipher or new_cipher:
        euph_map = {}
        for e in (existing_cipher.get('euphemisms', []) if isinstance(existing_cipher, dict) else []):
            term = e.get('term', '')
            if term:
                euph_map[term.lower()] = e
        for e in (new_cipher.get('euphemisms', []) if isinstance(new_cipher, dict) else []):
            term = e.get('term', '')
            if term and term.lower() not in euph_map:
                euph_map[term.lower()] = e
        merged_cipher = {
            'coded_passages': (existing_cipher.get('coded_passages', []) if isinstance(existing_cipher, dict) else []) +
                              (new_cipher.get('coded_passages', []) if isinstance(new_cipher, dict) else []),
            'euphemisms': list(euph_map.values()),
            'number_patterns': (existing_cipher.get('number_patterns', []) if isinstance(existing_cipher, dict) else []) +
                               (new_cipher.get('number_patterns', []) if isinstance(new_cipher, dict) else []),
            'suspicious_language': (existing_cipher.get('suspicious_language', []) if isinstance(existing_cipher, dict) else []) +
                                   (new_cipher.get('suspicious_language', []) if isinstance(new_cipher, dict) else []),
        }
    else:
        merged_cipher = {}

    return {
        'analysis': merged_analysis,
        'strategy': merged_strategy,
        'follow_up': merged_follow,
        'search_stats': merged_search_stats,
        'documents_found': merged_docs_found,
        'continuation_history': continuation_history,
        'banking': merged_banking,
        'identities': merged_identities,
        'cipher': merged_cipher,
        'network_data': build_investigation_network(merged_analysis, merged_banking),
    }


def resynthesize_report(existing, new_result, merged_analysis, merged_follow, new_objective):
    """Ri-sintetizza il report completo con tutte le scoperte vecchie + nuove"""
    client = get_anthropic_client()

    existing_report = existing.get('report', '')
    new_report = new_result.get('report', '')

    prompt = f"""Sei un investigatore esperto. Devi RISCRIVERE il report COMPLETO dell'investigazione integrando le nuove scoperte dalla continuazione.

# REPORT INVESTIGAZIONE PRECEDENTE
Obiettivo originale: {existing.get('objective', '')}

{existing_report or 'N/A'}

# NUOVA FASE INVESTIGATIVA
Nuovo obiettivo: {new_objective}

{new_report or 'N/A'}

# DATI UNIFICATI
Persone chiave: {json.dumps(merged_analysis.get('key_people', []), ensure_ascii=False)}
Connessioni: {json.dumps(merged_analysis.get('connections', []), ensure_ascii=False)}
Prove: {json.dumps(merged_analysis.get('significant_evidence', []), ensure_ascii=False)}
Timeline: {json.dumps(merged_analysis.get('timeline', []), ensure_ascii=False)}
Follow-up: {json.dumps(merged_follow, ensure_ascii=False)}

ISTRUZIONI CRITICHE:
1. Riscrivi il report COMPLETO integrando TUTTE le scoperte - NON una sezione aggiuntiva ma l'INTERO report aggiornato
2. MANTIENI tutte le persone, connessioni e prove precedenti e AGGIUNGI quelle nuove
3. Cita SEMPRE i codici EFTA esatti dei documenti
4. Scrivi in italiano, in modo chiaro e giornalistico
5. Usa ## per le sezioni: SOMMARIO ESECUTIVO, PERSONE CHIAVE, CONNESSIONI, PROVE SIGNIFICATIVE, PATTERN, TIMELINE, DOMANDE APERTE, PROSSIMI PASSI, VALUTAZIONE
6. DISAMBIGUAZIONE: "WHO" nei documenti è quasi sempre il pronome inglese "who" (chi), NON l'Organizzazione Mondiale della Sanità. "OMS" può essere "Order Management System" o un nome aziendale (es. "Lhasa OMS Inc."), NON necessariamente l'OMS sanitaria. Non confondere parole comuni inglesi con nomi di organizzazioni.
7. NON dedicare sezioni a "cosa NON è stato trovato" — concentrati solo sulle PROVE POSITIVE e le connessioni reali emerse dai documenti

Scrivi SOLO il report in markdown, nient'altro."""

    response = call_claude_with_retry(
        client,
        model=get_model(),
        max_tokens=16000,
        messages=[{"role": "user", "content": prompt + get_language_instruction()}],
    )

    return response.content[0].text
