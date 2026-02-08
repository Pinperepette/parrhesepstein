"""
Investigation Crew - Sistema Multi-Agente per Investigazioni
Un team di agenti AI che collaborano per investigare i documenti Epstein.
"""

import re
import json
import requests
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from anthropic import Anthropic
from app.services.justice_gov import search_justice_gov
from app.services.pdf import download_pdf_text


def fix_llm_json(text):
    """Corregge JSON malformato tipico delle risposte LLM."""
    # Rimuovi commenti // e /* */
    text = re.sub(r'//[^\n]*', '', text)
    text = re.sub(r'/\*[\s\S]*?\*/', '', text)
    # Rimuovi trailing commas prima di } o ]
    text = re.sub(r',\s*([}\]])', r'\1', text)
    # Sostituisci single quotes con double quotes (solo attorno a valori/chiavi)
    # Ma non toccare apostrofi dentro stringhe già quotate con ""
    text = re.sub(r"(?<![\"\\])'([^']*)'(?![\"\\])", r'"\1"', text)
    # Rimuovi caratteri di controllo dentro le stringhe (newline, tab)
    text = re.sub(r'[\x00-\x1f]+', ' ', text)
    return text


def parse_llm_json(text, fallback=None):
    """Estrae e parsa JSON dalla risposta LLM con fallback robusto."""
    # Prova prima il testo grezzo
    json_match = re.search(r'\{[\s\S]*\}', text)
    if not json_match:
        return fallback

    raw = json_match.group()

    # Tentativo 1: parse diretto
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Tentativo 2: fix e riprova
    try:
        fixed = fix_llm_json(raw)
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass

    # Tentativo 3: estrai blocchi JSON più piccoli annidati
    # A volte il regex cattura troppo testo
    depth = 0
    start = None
    for i, c in enumerate(text):
        if c == '{':
            if depth == 0:
                start = i
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0 and start is not None:
                candidate = text[start:i+1]
                try:
                    return json.loads(fix_llm_json(candidate))
                except json.JSONDecodeError:
                    start = None

    print(f"[JSON FIX] Impossibile parsare JSON, uso fallback")
    return fallback



class InvestigationCrew:
    """Team di agenti investigativi"""

    def __init__(self, api_key, progress_callback=None, model="claude-sonnet-4-20250514", lang_instruction="", base_url=None):
        self.client = Anthropic(api_key=api_key, base_url=base_url) if base_url else Anthropic(api_key=api_key)
        self.progress_callback = progress_callback or (lambda x: print(f"[CREW] {x}"))
        self.model = model
        self.lang_instruction = lang_instruction
        self.memory = {
            "objective": "",
            "findings": [],
            "connections": [],
            "people": set(),
            "documents": [],
            "open_questions": [],
            "timeline": []
        }

    def update_progress(self, msg):
        """Aggiorna il progresso"""
        self.progress_callback(msg)
        print(f"[CREW] {msg}", flush=True)

    def director_agent(self, objective):
        """Agente Direttore: pianifica la strategia investigativa"""
        self.update_progress("Direttore: Analisi obiettivo e pianificazione strategia...")

        prompt = f"""Sei il DIRETTORE di un team investigativo che analizza gli Epstein Files.

OBIETTIVO DELL'INVESTIGAZIONE:
{objective}

Il tuo compito è creare una STRATEGIA DI RICERCA. Devi identificare:

1. TERMINI DI RICERCA PRIMARI (max 5): Le keyword più importanti da cercare nel database
2. TERMINI DI RICERCA SECONDARI (max 5): Termini correlati o alternativi
3. PERSONE DA INVESTIGARE: Nomi di persone che potrebbero essere coinvolte
4. PATTERN DA CERCARE: Tipi di connessioni o comportamenti da identificare
5. DOMANDE CHIAVE: Le domande principali a cui rispondere

Rispondi in formato JSON:
{{
    "primary_terms": ["termine1", "termine2", ...],
    "secondary_terms": ["termine1", "termine2", ...],
    "people_to_investigate": ["nome1", "nome2", ...],
    "patterns_to_find": ["pattern1", "pattern2", ...],
    "key_questions": ["domanda1", "domanda2", ...]
}}

Rispondi SOLO con il JSON, nient'altro."""

        response = self.client.messages.create(
            model=self.model,
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt + self.lang_instruction}]
        )

        fallback = {
            "primary_terms": [objective.split()[0]],
            "secondary_terms": [],
            "people_to_investigate": [],
            "patterns_to_find": [],
            "key_questions": [objective]
        }
        text = response.content[0].text
        strategy = parse_llm_json(text, fallback)
        if strategy is not fallback:
            self.memory["objective"] = objective
        else:
            print("[DIRECTOR] Usato fallback per JSON malformato")
        return strategy

    def researcher_agent(self, search_terms, max_results_per_term=50):
        """Agente Ricercatore: cerca documenti nel database"""
        self.update_progress(f"Ricercatore: Ricerca di {len(search_terms)} termini...")

        all_results = []
        seen_ids = set()
        search_stats = []

        for term in search_terms:
            self.update_progress(f"Ricercatore: Cerco '{term}'...")

            for page in range(3):  # 3 pagine per termine
                result = search_justice_gov(term, page)
                total = result.get("total", 0)

                if page == 0:
                    search_stats.append(f"'{term}': {total} documenti")

                for doc in result.get("results", []):
                    doc_id = doc.get("id", "")
                    if doc_id and doc_id not in seen_ids:
                        seen_ids.add(doc_id)
                        all_results.append(doc)

                if len(all_results) >= max_results_per_term * len(search_terms):
                    break

            time.sleep(0.5)  # Rate limiting

        # Ricerca anche nel RAG locale
        try:
            from app.agents.vectordb import semantic_search
            rag_count = 0
            for term in search_terms[:5]:
                rag_results = semantic_search(term, n_results=10)
                for r in rag_results:
                    doc_id = r.get('metadata', {}).get('doc_id', '')
                    if doc_id and doc_id not in seen_ids:
                        seen_ids.add(doc_id)
                        rag_count += 1
                        all_results.append({
                            'id': doc_id,
                            'title': r.get('title', doc_id),
                            'url': r.get('url', ''),
                            'snippets': [r.get('text', '')[:300]],
                            'source': 'local_rag',
                            'relevance_score': r.get('relevance', 0)
                        })
            if rag_count > 0:
                self.update_progress(f"Ricercatore: +{rag_count} documenti dal RAG locale")
        except Exception as e:
            print(f"[RAG] Errore ricerca vettoriale: {e}")

        self.update_progress(f"Ricercatore: Trovati {len(all_results)} documenti unici")

        # Scarica e salva i PDF di tutti i documenti trovati
        docs_to_download = [d for d in all_results if d.get('url') and d.get('source') != 'local_rag']
        if docs_to_download:
            self.update_progress(f"Ricercatore: Download {len(docs_to_download)} documenti...")
            downloaded = 0
            for doc in docs_to_download:
                try:
                    text = download_pdf_text(doc['url'])
                    if text and not text.startswith('[Errore') and not text.startswith('[OCR'):
                        doc['full_text'] = text[:3000]
                        downloaded += 1
                except Exception:
                    pass
            self.update_progress(f"Ricercatore: {downloaded}/{len(docs_to_download)} documenti scaricati e salvati")

        return all_results, search_stats

    def _build_analyst_prompt(self, docs_context, objective, known_people=None):
        """Costruisce il prompt per l'analista"""
        known_people_context = ""
        if known_people:
            known_people_context = "\n## PERSONE GIA' NOTE NEL DATABASE:\n"
            for kp in known_people[:20]:
                name = kp.get('name', '')
                roles = ', '.join(kp.get('roles', [])[:3])
                conns = ', '.join(kp.get('all_connections', [])[:5])
                rel = kp.get('relevance', 'media')
                known_people_context += f"- **{name}** (rilevanza: {rel})"
                if roles:
                    known_people_context += f" - Ruoli: {roles}"
                if conns:
                    known_people_context += f" - Connessioni: {conns}"
                known_people_context += "\n"
            known_people_context += "\nSe trovi riferimenti a queste persone, collega le nuove scoperte alle informazioni esistenti.\n"

        historical_ctx = getattr(self, '_historical_context', '') or ''
        historical_section = f"\n{historical_ctx}\n" if historical_ctx else ""

        return f"""Sei l'ANALISTA di un team investigativo sugli Epstein Files.

OBIETTIVO: {objective}
{known_people_context}{historical_section}
DOCUMENTI TROVATI:
{docs_context}

ISTRUZIONI IMPORTANTI - DEVI ESSERE RIGOROSO:
- Cita SEMPRE il codice documento EFTA esatto (es: EFTA01234567) quando fai riferimento a un documento
- NON usare riferimenti generici come "Documento 1" o "Documento 11"
- Se trovi una prova importante, DEVI citare il codice EFTA del documento che la contiene
- Cita il TESTO ESATTO quando possibile, tra virgolette

DISTINZIONE CRITICA - NON CONFONDERE:
- **COMUNICAZIONE DIRETTA**: Email scritta DA o indirizzata A quella persona (PROVA FORTE)
- **MENZIONE DA TERZI**: Il nome appare in email tra ALTRE persone che ne parlano (PROVA DEBOLE)
- **ARTICOLO/NOTIZIA**: Un articolo di giornale salvato che menziona la persona (NON È PROVA)

Se una persona è solo MENZIONATA da altri, NON puoi concludere che sia "coinvolta" o "parte della rete".
Devi specificare: CHI ha scritto → A CHI → e se la persona target ha MAI risposto direttamente.

Analizza questi documenti e identifica:

1. PERSONE CHIAVE: Chi sono le persone menzionate e qual è il loro ruolo?
2. CONNESSIONI: Quali collegamenti esistono tra persone, luoghi, eventi?
3. PATTERN: Quali comportamenti o schemi ricorrenti emergono?
4. PROVE SIGNIFICATIVE: Quali sono le informazioni più incriminanti o importanti?
5. TIMELINE: Quali date o periodi temporali emergono?
6. LUOGHI: Quali località sono menzionate?

Rispondi in formato JSON:
{{
    "key_people": [
        {{"name": "Nome", "role": "Ruolo/contesto", "relevance": "alta/media/bassa", "evidence_doc": "EFTA..."}}
    ],
    "connections": [
        {{"from": "Persona1", "to": "Persona2", "type": "tipo di connessione", "evidence": "EFTA...", "quote": "citazione esatta"}}
    ],
    "patterns": ["pattern1", "pattern2"],
    "significant_evidence": [
        {{"document": "EFTA...", "content": "citazione esatta dal documento", "importance": "perché è importante"}}
    ],
    "timeline": [
        {{"date": "data esatta", "event": "evento", "source": "EFTA..."}}
    ],
    "locations": ["luogo1", "luogo2"]
}}

Rispondi SOLO con il JSON, nient'altro."""

    def _prepare_doc_context(self, doc):
        """Prepara il contesto di un singolo documento"""
        doc_id = doc.get("id", "")
        title = doc.get("title", "N/A")
        if not doc_id.startswith("EFTA") and "EFTA" in title:
            efta_match = re.search(r'EFTA\d+', title)
            if efta_match:
                doc_id = efta_match.group()
        full_text = doc.get("full_text", "")
        if full_text:
            return f"\n[{doc_id}] {title}\n    FULL: {full_text[:3000]}\n"
        else:
            snippets = doc.get("snippets", [])
            snippet_text = " | ".join(s[:200].replace("<em>", "**").replace("</em>", "**") for s in snippets[:2])
            return f"\n[{doc_id}] {title}\n    {snippet_text}\n"

    def _analyze_batch(self, batch, batch_num, objective, known_people):
        """Analizza un batch di documenti (eseguito in parallelo)"""
        docs_context = ""
        for doc in batch:
            docs_context += self._prepare_doc_context(doc)

        prompt = self._build_analyst_prompt(docs_context, objective, known_people)

        try:
            print(f"[ANALYST WORKER {batch_num}] Analisi {len(batch)} documenti...", flush=True)
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4000,
                messages=[{"role": "user", "content": prompt + self.lang_instruction}]
            )
            result = parse_llm_json(response.content[0].text, None)
            if result:
                print(f"[ANALYST WORKER {batch_num}] Completato!", flush=True)
                return result
        except Exception as e:
            print(f"[ANALYST WORKER {batch_num}] Errore: {e}", flush=True)

        return {"key_people": [], "connections": [], "patterns": [], "significant_evidence": [], "timeline": [], "locations": []}

    def _merge_analyst_results(self, results):
        """Unisce i risultati di più batch di analisi"""
        merged = {
            "key_people": [],
            "connections": [],
            "patterns": [],
            "significant_evidence": [],
            "timeline": [],
            "locations": []
        }
        seen_people = {}
        seen_connections = set()
        seen_evidence = set()
        seen_timeline = set()

        for result in results:
            # People: deduplica per nome, tieni relevanza più alta
            for p in result.get("key_people", []):
                name = p.get("name", "").lower()
                if name and name not in seen_people:
                    seen_people[name] = p
                elif name and name in seen_people:
                    relevance_order = {'alta': 3, 'media': 2, 'bassa': 1}
                    old_rel = relevance_order.get(seen_people[name].get('relevance', 'bassa'), 1)
                    new_rel = relevance_order.get(p.get('relevance', 'bassa'), 1)
                    if new_rel > old_rel:
                        seen_people[name] = p

            # Connections: deduplica per from|to
            for c in result.get("connections", []):
                key = f"{c.get('from', '')}|{c.get('to', '')}".lower()
                if key not in seen_connections:
                    seen_connections.add(key)
                    merged["connections"].append(c)

            # Evidence: deduplica per documento
            for e in result.get("significant_evidence", []):
                doc = e.get("document", "")
                if doc not in seen_evidence:
                    seen_evidence.add(doc)
                    merged["significant_evidence"].append(e)

            # Timeline: deduplica per data+evento
            for t in result.get("timeline", []):
                key = f"{t.get('date', '')}|{t.get('event', '')}".lower()
                if key not in seen_timeline:
                    seen_timeline.add(key)
                    merged["timeline"].append(t)

            merged["patterns"].extend(result.get("patterns", []))
            merged["locations"].extend(result.get("locations", []))

        merged["key_people"] = list(seen_people.values())
        merged["patterns"] = list(set(merged["patterns"]))
        merged["locations"] = list(set(merged["locations"]))
        merged["timeline"].sort(key=lambda t: t.get("date", ""))

        return merged

    def analyst_agent(self, documents, objective, known_people=None):
        """Agente Analista: analizza i documenti e trova connessioni.
        Se ci sono più di 20 documenti, usa analisi parallela a batch."""
        self.update_progress(f"Analista: Analisi di {len(documents)} documenti...")

        batch_size = 20

        if len(documents) <= batch_size:
            # Pochi documenti: singola chiamata
            return self._analyze_batch(documents, 1, objective, known_people)

        # Molti documenti: batch paralleli
        batches = [documents[i:i + batch_size] for i in range(0, len(documents), batch_size)]
        self.update_progress(f"Analista: {len(batches)} batch paralleli da ~{batch_size} documenti...")

        results = []
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {
                executor.submit(self._analyze_batch, batch, i + 1, objective, known_people): i
                for i, batch in enumerate(batches)
            }
            for future in as_completed(futures):
                batch_idx = futures[future]
                try:
                    result = future.result(timeout=300)
                    results.append(result)
                    self.update_progress(f"Analista: Batch {batch_idx + 1}/{len(batches)} completato")
                except Exception as e:
                    print(f"[ANALYST] Batch {batch_idx + 1} errore: {e}", flush=True)

        if not results:
            return {"key_people": [], "connections": [], "patterns": [], "significant_evidence": [], "timeline": [], "locations": []}

        self.update_progress(f"Analista: Unione risultati da {len(results)} batch...")
        return self._merge_analyst_results(results)

    def banker_agent(self, documents, objective, analyst_findings):
        """Agente Banchiere: analizza transazioni finanziarie, banche, flussi di denaro"""
        self.update_progress("Banchiere: Analisi dati finanziari...")

        docs_context = ""
        for i, doc in enumerate(documents[:30]):
            doc_id = doc.get("id", "")
            title = doc.get("title", "N/A")
            if not doc_id.startswith("EFTA") and "EFTA" in title:
                efta_match = re.search(r'EFTA\d+', title)
                if efta_match:
                    doc_id = efta_match.group()
            snippets = doc.get("snippets", [])
            snippet_text = " | ".join(s[:200].replace("<em>", "**").replace("</em>", "**") for s in snippets[:2])
            docs_context += f"\n[{doc_id}] {title}\n    {snippet_text}\n"

        analyst_context = json.dumps(analyst_findings, indent=2, ensure_ascii=False)[:3000]

        # Contesto storico
        historical_ctx = getattr(self, '_historical_context', '') or ''
        historical_section = f"\n{historical_ctx}\n" if historical_ctx else ""

        prompt = f"""Sei il BANCHIERE FORENSE di un team investigativo sugli Epstein Files.

OBIETTIVO: {objective}

ANALISI PRECEDENTE DELL'ANALISTA:
{analyst_context}
{historical_section}
DOCUMENTI:
{docs_context}

Il tuo compito e' analizzare TUTTI i dati finanziari presenti nei documenti:
- Banche coinvolte, conti correnti, societa' offshore
- Transazioni, pagamenti, bonifici, assegni
- Flussi di denaro sospetti, riciclaggio, evasione
- Pattern finanziari ricorrenti
- Red flags finanziarie

ISTRUZIONI:
- Cita SEMPRE il codice EFTA del documento come prova
- Specifica importi esatti quando disponibili
- Indica se una transazione e' sospetta e perche'
- Identifica le banche e il loro ruolo nella rete

Rispondi in formato JSON:
{{
    "banks": [{{"name":"...", "role":"...", "evidence":"EFTA...", "accounts":["..."], "key_people":["..."]}}],
    "transactions": [{{"from_entity":"...", "to_entity":"...", "amount":"$...", "date":"...", "type":"wire/check/transfer", "bank":"...", "evidence":"EFTA...", "suspicious":true, "reason":"..."}}],
    "money_flows": [{{"source":"...", "destination":"...", "total_amount":"...", "period":"...", "pattern":"..."}}],
    "offshore": [{{"entity":"...", "jurisdiction":"...", "evidence":"EFTA...", "connected_to":["..."]}}],
    "red_flags": [{{"description":"...", "evidence":"EFTA...", "severity":"critica/alta/media"}}]
}}

Rispondi SOLO con il JSON."""

        response = self.client.messages.create(
            model=self.model,
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt + self.lang_instruction}]
        )

        fallback = {
            "banks": [],
            "transactions": [],
            "money_flows": [],
            "offshore": [],
            "red_flags": []
        }
        text = response.content[0].text
        result = parse_llm_json(text, fallback)
        if result is fallback:
            print("[BANKER] Usato fallback per JSON malformato")
        return result

    def identity_resolver_agent(self, documents, objective, analyst_findings):
        """Agente Risolutore Identita': risolve alias, soprannomi, iniziali"""
        self.update_progress("Risolutore Identita': Analisi alias e identita'...")

        docs_context = ""
        for i, doc in enumerate(documents[:30]):
            doc_id = doc.get("id", "")
            title = doc.get("title", "N/A")
            if not doc_id.startswith("EFTA") and "EFTA" in title:
                efta_match = re.search(r'EFTA\d+', title)
                if efta_match:
                    doc_id = efta_match.group()
            snippets = doc.get("snippets", [])
            snippet_text = " | ".join(s[:200].replace("<em>", "**").replace("</em>", "**") for s in snippets[:2])
            docs_context += f"\n[{doc_id}] {title}\n    {snippet_text}\n"

        analyst_context = json.dumps(analyst_findings, indent=2, ensure_ascii=False)[:3000]

        # Contesto storico
        historical_ctx = getattr(self, '_historical_context', '') or ''
        historical_section = f"\n{historical_ctx}\n" if historical_ctx else ""

        prompt = f"""Sei il RISOLUTORE DI IDENTITA' di un team investigativo sugli Epstein Files.

OBIETTIVO: {objective}

ANALISI PRECEDENTE:
{analyst_context}
{historical_section}
DOCUMENTI:
{docs_context}

Il tuo compito e' risolvere TUTTE le identita' ambigue nei documenti:
- Iniziali (JE = Jeffrey Epstein, GM = Ghislaine Maxwell, etc.)
- Soprannomi e nomi abbreviati
- Riferimenti indiretti a persone ("the boss", "our friend", etc.)
- Alias e pseudonimi
- Nomi scritti in modo diverso (varianti ortografiche)

REGOLE NOTE:
- JE, Jeff = Jeffrey Epstein
- GM, G = Ghislaine Maxwell
- Les, LW = Les Wexner
- AP = Andrew (Prince Andrew)
- BD, Bill = Bill Clinton o Bill Gates (distingui dal contesto)

Per ogni identita' risolta, cita il documento EFTA e il contesto che ti ha permesso di identificarla.

Rispondi in formato JSON:
{{
    "identities": [{{"canonical_name":"...", "aliases":["JE","Jeff"], "evidence":[{{"alias":"JE", "context":"...", "doc":"EFTA..."}}]}}],
    "nickname_patterns": ["pattern1"],
    "unresolved_references": [{{"reference":"...", "context":"...", "doc":"EFTA...", "possible_identities":["..."]}}]
}}

Rispondi SOLO con il JSON."""

        response = self.client.messages.create(
            model=self.model,
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt + self.lang_instruction}]
        )

        fallback = {
            "identities": [],
            "nickname_patterns": [],
            "unresolved_references": []
        }
        text = response.content[0].text
        result = parse_llm_json(text, fallback)
        if result is fallback:
            print("[IDENTITY_RESOLVER] Usato fallback per JSON malformato")
        return result

    def cipher_agent(self, documents, objective, identity_resolutions):
        """Agente Decodificatore: decodifica linguaggio in codice, eufemismi, passaggi criptici"""
        self.update_progress("Decodificatore: Analisi linguaggio cifrato...")

        docs_context = ""
        for i, doc in enumerate(documents[:30]):
            doc_id = doc.get("id", "")
            title = doc.get("title", "N/A")
            if not doc_id.startswith("EFTA") and "EFTA" in title:
                efta_match = re.search(r'EFTA\d+', title)
                if efta_match:
                    doc_id = efta_match.group()
            snippets = doc.get("snippets", [])
            snippet_text = " | ".join(s[:200].replace("<em>", "**").replace("</em>", "**") for s in snippets[:2])
            docs_context += f"\n[{doc_id}] {title}\n    {snippet_text}\n"

        identity_context = json.dumps(identity_resolutions, indent=2, ensure_ascii=False)[:2000]

        # Contesto storico
        historical_ctx = getattr(self, '_historical_context', '') or ''
        historical_section = f"\n{historical_ctx}\n" if historical_ctx else ""

        prompt = f"""Sei il DECODIFICATORE di un team investigativo sugli Epstein Files.

OBIETTIVO: {objective}

IDENTITA' RISOLTE DAL RISOLUTORE:
{identity_context}
{historical_section}
DOCUMENTI:
{docs_context}

Il tuo compito e' decodificare il linguaggio in codice nei documenti:
- Eufemismi noti: "massage" = possibile abuso sessuale, "modeling" = possibile traffico
- Pattern numerici sospetti (orari, somme, codici)
- Linguaggio vago intenzionale ("the usual", "the thing", "she's ready")
- Passaggi criptici che nascondono significati
- Comunicazioni che evitano di essere esplicite

USA le identita' risolte come contesto per decodificare meglio i messaggi.

ATTENZIONE: Non speculare senza basi. Indica il livello di confidenza per ogni interpretazione.

Rispondi in formato JSON:
{{
    "coded_passages": [{{"text":"...", "interpretation":"...", "confidence":"alta/media/bassa", "doc":"EFTA...", "reasoning":"..."}}],
    "euphemisms": [{{"term":"massage", "likely_meaning":"...", "occurrences":5, "evidence":["EFTA..."]}}],
    "number_patterns": [{{"pattern":"...", "possible_meaning":"...", "occurrences":[]}}],
    "suspicious_language": [{{"text":"...", "why_suspicious":"...", "doc":"EFTA..."}}]
}}

Rispondi SOLO con il JSON."""

        response = self.client.messages.create(
            model=self.model,
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt + self.lang_instruction}]
        )

        fallback = {
            "coded_passages": [],
            "euphemisms": [],
            "number_patterns": [],
            "suspicious_language": []
        }
        text = response.content[0].text
        result = parse_llm_json(text, fallback)
        if result is fallback:
            print("[CIPHER] Usato fallback per JSON malformato")
        return result

    def interrogator_agent(self, findings, objective):
        """Agente Interrogatore: genera domande di follow-up"""
        self.update_progress("Interrogatore: Generazione domande di approfondimento...")

        # Contesto storico
        historical_ctx = getattr(self, '_historical_context', '') or ''
        historical_section = f"\n{historical_ctx}\n" if historical_ctx else ""

        prompt = f"""Sei l'INTERROGATORE di un team investigativo sugli Epstein Files.

OBIETTIVO ORIGINALE: {objective}
{historical_section}
SCOPERTE FINORA:
{json.dumps(findings, indent=2, ensure_ascii=False)}

Basandoti su queste scoperte, genera:

1. DOMANDE CRITICHE: Domande che potrebbero rivelare informazioni cruciali
2. PISTE DA SEGUIRE: Nuove direzioni di ricerca suggerite dalle scoperte
3. INCONGRUENZE: Elementi che non tornano o meritano approfondimento
4. TERMINI DI RICERCA SUGGERITI: Nuovi termini da cercare nel database

Rispondi in formato JSON:
{{
    "critical_questions": ["domanda1", "domanda2", ...],
    "leads_to_follow": ["pista1", "pista2", ...],
    "inconsistencies": ["incongruenza1", ...],
    "suggested_searches": ["termine1", "termine2", ...]
}}"""

        response = self.client.messages.create(
            model=self.model,
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt + self.lang_instruction}]
        )

        fallback = {
            "critical_questions": [],
            "leads_to_follow": [],
            "inconsistencies": [],
            "suggested_searches": []
        }
        text = response.content[0].text
        result = parse_llm_json(text, fallback)
        if result is fallback:
            print("[INTERROGATOR] Usato fallback per JSON malformato")
        return result

    def synthesizer_agent(self, strategy, all_findings, follow_up, objective, search_stats):
        """Agente Sintetizzatore: crea il report finale"""
        self.update_progress("Sintetizzatore: Creazione report finale...")

        # Estrai i dati dai findings
        if isinstance(all_findings, dict) and 'banking' in all_findings:
            analysis = {k: v for k, v in all_findings.items() if k not in ('banking', 'identities', 'cipher')}
            banking_data = all_findings.get('banking', {})
            identity_data = all_findings.get('identities', {})
            cipher_data = all_findings.get('cipher', {})
        else:
            analysis = all_findings
            banking_data = {}
            identity_data = {}
            cipher_data = {}

        banking_section = ""
        if banking_data and any(banking_data.get(k) for k in ['banks', 'transactions', 'red_flags', 'offshore']):
            banking_section = f"""

DATI FINANZIARI (dal Banchiere Forense):
{json.dumps(banking_data, indent=2, ensure_ascii=False)[:3000]}"""

        identity_section = ""
        if identity_data and any(identity_data.get(k) for k in ['identities', 'unresolved_references']):
            identity_section = f"""

IDENTITA' RISOLTE (dal Risolutore):
{json.dumps(identity_data, indent=2, ensure_ascii=False)[:2000]}"""

        cipher_section = ""
        if cipher_data and any(cipher_data.get(k) for k in ['coded_passages', 'euphemisms', 'suspicious_language']):
            cipher_section = f"""

LINGUAGGIO CODIFICATO (dal Decodificatore):
{json.dumps(cipher_data, indent=2, ensure_ascii=False)[:2000]}"""

        # Contesto storico
        historical_ctx = getattr(self, '_historical_context', '') or ''
        historical_section = f"\n{historical_ctx}\n" if historical_ctx else ""

        prompt = f"""Sei il SINTETIZZATORE di un team investigativo sugli Epstein Files.

OBIETTIVO DELL'INVESTIGAZIONE:
{objective}
{historical_section}
STRATEGIA USATA:
{json.dumps(strategy, indent=2, ensure_ascii=False)}

ANALISI DEI DOCUMENTI:
{json.dumps(analysis, indent=2, ensure_ascii=False)}
{banking_section}
{identity_section}
{cipher_section}

DOMANDE DI FOLLOW-UP:
{json.dumps(follow_up, indent=2, ensure_ascii=False)}

STATISTICHE RICERCA:
{chr(10).join(search_stats)}

ISTRUZIONI IMPORTANTI PER LA PRECISIONE:
- Cita SEMPRE il codice documento EFTA esatto (es: EFTA01234567) quando menzioni una prova
- NON usare mai riferimenti generici come "Documento 1", "un documento", "alcuni documenti"
- Quando citi un fatto, DEVI indicare il documento EFTA che lo prova
- Se non hai il codice EFTA, scrivi "documento non identificato" e NON inventare
- Cita il TESTO ESATTO tra virgolette quando possibile

ATTENZIONE - DISAMBIGUAZIONE PAROLE COMUNI:
- "WHO" nei documenti è quasi sempre il PRONOME inglese "who" (chi), NON l'Organizzazione Mondiale della Sanità (World Health Organization)
- "OMS" può significare cose diverse: "Order Management System" (sistema trading), "Lhasa OMS Inc." (azienda), oppure in italiano "Organizzazione Mondiale della Sanità"
- NON confondere parole comuni inglesi (who, will, may, black, house, etc.) con nomi propri o organizzazioni
- Se un termine ha un alto numero di occorrenze (>1000), probabilmente è una parola comune, NON un'entità specifica
- NON fare affermazioni su organizzazioni (OMS/WHO, ONU, NATO, etc.) basandosi solo sul conteggio delle parole — verifica il CONTESTO reale nei documenti
- NON dedicare sezioni del report a "cosa NON è stato trovato" — concentrati solo sulle PROVE POSITIVE trovate

ATTENZIONE - NON FARE CONCLUSIONI INFONDATE:
- Essere MENZIONATO in un documento NON significa essere COINVOLTO
- Se qualcuno scrive "vado a incontrare X", non significa che X faccia parte di una rete criminale
- Distingui SEMPRE tra:
  * PROVA DIRETTA: Email/comunicazione scritta DALLA persona investigata
  * MENZIONE: La persona è nominata da altri (NON è prova di coinvolgimento)
  * ARTICOLO: Notizie/articoli salvati (NON sono prove)

- Per ogni persona, specifica:
  * Ha MAI comunicato direttamente? (email da/a)
  * O è solo MENZIONATA da terzi?
  * C'è RISPOSTA della persona o di un suo collaboratore?

- NON usare parole come "coinvolgimento", "coordinamento", "parte della rete" se la persona è solo MENZIONATA
- USA invece: "menzionato in", "citato da terzi", "oggetto di discussione tra altri"

Crea un REPORT INVESTIGATIVO COMPLETO in italiano che includa:

## SOMMARIO ESECUTIVO
Un riassunto delle scoperte principali in 3-5 punti. Ogni punto deve citare il documento EFTA di riferimento.

## PERSONE CHIAVE IDENTIFICATE
Chi sono e perché sono rilevanti. Per ogni persona indica il documento EFTA che la menziona.

## CONNESSIONI SCOPERTE
I collegamenti trovati tra persone, luoghi, eventi. OGNI connessione deve avere il codice EFTA del documento che la prova.

## PROVE SIGNIFICATIVE
I documenti e le informazioni più importanti. Formato: "EFTA...: [citazione esatta]"

## PATTERN E COMPORTAMENTI
Gli schemi ricorrenti identificati, con riferimenti ai documenti.

## ANALISI FINANZIARIA
Banche coinvolte, transazioni sospette, flussi di denaro, societa' offshore. Se non ci sono dati finanziari, scrivi "Nessun dato finanziario rilevante trovato."

## IDENTITA' E ALIAS
Identita' risolte, alias confermati, riferimenti ancora ambigui. Se non ci sono alias da risolvere, scrivi "Nessun alias significativo da risolvere."

## LINGUAGGIO CODIFICATO
Eufemismi decodificati, passaggi criptici interpretati, linguaggio sospetto. Se non presente, scrivi "Nessun linguaggio codificato significativo rilevato."

## TIMELINE
Cronologia degli eventi con codice EFTA per ogni evento. Formato: "DATA - Evento (EFTA...)"

## DOMANDE APERTE
Cosa resta da investigare.

## PROSSIMI PASSI
Cosa fare per approfondire l'investigazione.

## VALUTAZIONE
Quanto sono solide le prove trovate (alta/media/bassa affidabilità). Basata su quanti documenti EFTA supportano ogni affermazione.

Scrivi in modo chiaro, diretto, giornalistico. OGNI affermazione deve avere il codice EFTA del documento che la supporta."""

        response = self.client.messages.create(
            model=self.model,
            max_tokens=6000,
            messages=[{"role": "user", "content": prompt + self.lang_instruction}]
        )

        return response.content[0].text

    def director_agent_with_context(self, objective, existing_context):
        """Agente Direttore context-aware: pianifica evitando duplicati"""
        self.update_progress("Direttore: Analisi obiettivo con contesto precedente...")

        previous_terms = existing_context.get('previous_search_terms', [])
        people_found = existing_context.get('people_already_found', [])
        open_questions = existing_context.get('open_questions', [])
        suggested = existing_context.get('suggested_searches', [])
        leads = existing_context.get('leads_to_follow', [])

        prompt = f"""Sei il DIRETTORE di un team investigativo che analizza gli Epstein Files.

NUOVO OBIETTIVO DA INVESTIGARE:
{objective}

CONTESTO DELL'INVESTIGAZIONE PRECEDENTE:
- Obiettivo originale: {existing_context.get('original_objective', 'N/A')}
- Termini GIÀ cercati (NON ripeterli): {json.dumps(previous_terms, ensure_ascii=False)}
- Persone GIÀ trovate (concentrati su NUOVE): {json.dumps(people_found, ensure_ascii=False)}
- Domande ancora aperte: {json.dumps(open_questions, ensure_ascii=False)}
- Ricerche suggerite dal team: {json.dumps(suggested, ensure_ascii=False)}
- Piste da seguire: {json.dumps(leads, ensure_ascii=False)}

ISTRUZIONI:
1. NON ripetere termini già cercati
2. Concentrati su NUOVE persone e connessioni
3. Usa le domande aperte e le piste suggerite come input
4. Proponi termini di ricerca DIVERSI da quelli precedenti

Rispondi in formato JSON:
{{
    "primary_terms": ["termine1", "termine2", ...],
    "secondary_terms": ["termine1", "termine2", ...],
    "people_to_investigate": ["nome1", "nome2", ...],
    "patterns_to_find": ["pattern1", "pattern2", ...],
    "key_questions": ["domanda1", "domanda2", ...]
}}

Rispondi SOLO con il JSON, nient'altro."""

        response = self.client.messages.create(
            model=self.model,
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt + self.lang_instruction}]
        )

        fallback = {
            "primary_terms": [objective.split()[0]],
            "secondary_terms": [],
            "people_to_investigate": [],
            "patterns_to_find": [],
            "key_questions": [objective]
        }
        text = response.content[0].text
        strategy = parse_llm_json(text, fallback)
        if strategy is not fallback:
            self.memory["objective"] = objective
        else:
            print("[DIRECTOR-CTX] Usato fallback per JSON malformato")
        return strategy

    def interrogator_agent_with_context(self, findings, objective, existing_context):
        """Agente Interrogatore context-aware: evita domande già poste"""
        self.update_progress("Interrogatore: Generazione nuove domande di approfondimento...")

        previous_questions = existing_context.get('open_questions', [])

        prompt = f"""Sei l'INTERROGATORE di un team investigativo sugli Epstein Files.

OBIETTIVO CORRENTE: {objective}

SCOPERTE DA QUESTA FASE:
{json.dumps(findings, indent=2, ensure_ascii=False)}

DOMANDE GIÀ POSTE IN PRECEDENZA (NON ripeterle):
{json.dumps(previous_questions, ensure_ascii=False)}

Basandoti sulle NUOVE scoperte, genera NUOVE domande e piste che NON siano già state poste.

Rispondi in formato JSON:
{{
    "critical_questions": ["domanda1", "domanda2", ...],
    "leads_to_follow": ["pista1", "pista2", ...],
    "inconsistencies": ["incongruenza1", ...],
    "suggested_searches": ["termine1", "termine2", ...]
}}"""

        response = self.client.messages.create(
            model=self.model,
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt + self.lang_instruction}]
        )

        fallback = {
            "critical_questions": [],
            "leads_to_follow": [],
            "inconsistencies": [],
            "suggested_searches": []
        }
        text = response.content[0].text
        result = parse_llm_json(text, fallback)
        if result is fallback:
            print("[INTERROGATOR-CTX] Usato fallback per JSON malformato")
        return result

    def investigate_with_context(self, objective, existing_context, known_people=None):
        """Esegue l'investigazione con contesto da investigazione precedente"""
        self.update_progress(f"Continuazione investigazione: {objective[:50]}...")

        # 1. Direttore context-aware
        strategy = self.director_agent_with_context(objective, existing_context)
        self.update_progress(f"Strategia: {len(strategy.get('primary_terms', []))} termini primari")

        # 2. Ricercatore cerca documenti
        all_terms = strategy.get("primary_terms", []) + strategy.get("secondary_terms", [])
        all_terms += strategy.get("people_to_investigate", [])[:3]

        documents, search_stats = self.researcher_agent(all_terms[:10])

        if not documents:
            return {
                "success": False,
                "error": "Nessun documento trovato",
                "strategy": strategy
            }

        # 3. Analista analizza i documenti (con contesto persone note)
        analysis = self.analyst_agent(documents, objective, known_people=known_people)

        # 4. Banchiere + Risolutore Identita' IN PARALLELO
        self.update_progress("Analisi parallela: Banchiere + Risolutore Identita'...")
        banking_data = {}
        identity_data = {}
        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                banker_future = executor.submit(self.banker_agent, documents, objective, analysis)
                identity_future = executor.submit(self.identity_resolver_agent, documents, objective, analysis)
                try:
                    banking_data = banker_future.result()
                except Exception as e:
                    print(f"[BANKER-CTX] Errore: {e}")
                    banking_data = {"banks": [], "transactions": [], "money_flows": [], "offshore": [], "red_flags": []}
                try:
                    identity_data = identity_future.result()
                except Exception as e:
                    print(f"[IDENTITY-CTX] Errore: {e}")
                    identity_data = {"identities": [], "nickname_patterns": [], "unresolved_references": []}
        except Exception as e:
            print(f"[PARALLEL-CTX] Errore esecuzione parallela: {e}")

        # 5. Decodificatore (usa identita' risolte)
        cipher_data = {}
        try:
            cipher_data = self.cipher_agent(documents, objective, identity_data)
        except Exception as e:
            print(f"[CIPHER-CTX] Errore: {e}")
            cipher_data = {"coded_passages": [], "euphemisms": [], "number_patterns": [], "suspicious_language": []}

        # 6. Interrogatore context-aware (riceve tutto)
        all_findings = dict(analysis)
        all_findings['banking'] = banking_data
        all_findings['identities'] = identity_data
        all_findings['cipher'] = cipher_data
        follow_up = self.interrogator_agent_with_context(all_findings, objective, existing_context)

        # 7. Sintetizzatore crea il report
        report = self.synthesizer_agent(strategy, all_findings, follow_up, objective, search_stats)

        return {
            "success": True,
            "objective": objective,
            "strategy": strategy,
            "documents_found": len(documents),
            "search_stats": search_stats,
            "analysis": analysis,
            "follow_up": follow_up,
            "report": report,
            "banking": banking_data,
            "identities": identity_data,
            "cipher": cipher_data
        }

    def investigate(self, objective, known_people=None):
        """Esegue l'investigazione completa"""
        self.update_progress(f"Avvio investigazione: {objective[:50]}...")

        # Recupera contesto storico da RAG + MongoDB
        self._historical_context = ""
        try:
            from app.agents.context_provider import get_full_context
            self._historical_context = get_full_context(objective, rag_results=5, mongo_limit=5)
            if self._historical_context:
                self.update_progress(f"Contesto storico recuperato: {len(self._historical_context)} caratteri")
        except Exception as e:
            print(f"[CREW] Errore recupero contesto storico: {e}", flush=True)

        # 1. Direttore pianifica la strategia
        strategy = self.director_agent(objective)
        self.update_progress(f"Strategia: {len(strategy.get('primary_terms', []))} termini primari")

        # 2. Ricercatore cerca documenti
        all_terms = strategy.get("primary_terms", []) + strategy.get("secondary_terms", [])
        all_terms += strategy.get("people_to_investigate", [])[:3]  # Aggiungi persone

        documents, search_stats = self.researcher_agent(all_terms[:10])  # Max 10 termini

        if not documents:
            return {
                "success": False,
                "error": "Nessun documento trovato",
                "strategy": strategy
            }

        # 3. Analista analizza i documenti (con contesto persone note)
        analysis = self.analyst_agent(documents, objective, known_people=known_people)

        # 4. Banchiere + Risolutore Identita' IN PARALLELO
        self.update_progress("Analisi parallela: Banchiere + Risolutore Identita'...")
        banking_data = {}
        identity_data = {}
        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                banker_future = executor.submit(self.banker_agent, documents, objective, analysis)
                identity_future = executor.submit(self.identity_resolver_agent, documents, objective, analysis)
                try:
                    banking_data = banker_future.result()
                except Exception as e:
                    print(f"[BANKER] Errore: {e}")
                    banking_data = {"banks": [], "transactions": [], "money_flows": [], "offshore": [], "red_flags": []}
                try:
                    identity_data = identity_future.result()
                except Exception as e:
                    print(f"[IDENTITY_RESOLVER] Errore: {e}")
                    identity_data = {"identities": [], "nickname_patterns": [], "unresolved_references": []}
        except Exception as e:
            print(f"[PARALLEL] Errore esecuzione parallela: {e}")

        # 5. Decodificatore (usa identita' risolte)
        cipher_data = {}
        try:
            cipher_data = self.cipher_agent(documents, objective, identity_data)
        except Exception as e:
            print(f"[CIPHER] Errore: {e}")
            cipher_data = {"coded_passages": [], "euphemisms": [], "number_patterns": [], "suspicious_language": []}

        # 6. Interrogatore (riceve tutto)
        all_findings = dict(analysis)
        all_findings['banking'] = banking_data
        all_findings['identities'] = identity_data
        all_findings['cipher'] = cipher_data
        follow_up = self.interrogator_agent(all_findings, objective)

        # 7. Sintetizzatore crea il report
        report = self.synthesizer_agent(strategy, all_findings, follow_up, objective, search_stats)

        return {
            "success": True,
            "objective": objective,
            "strategy": strategy,
            "documents_found": len(documents),
            "search_stats": search_stats,
            "analysis": analysis,
            "follow_up": follow_up,
            "report": report,
            "banking": banking_data,
            "identities": identity_data,
            "cipher": cipher_data
        }


def run_investigation(objective, api_key, progress_callback=None, known_people=None,
                      model="claude-sonnet-4-20250514", lang_instruction="", base_url=None):
    """Funzione principale per eseguire un'investigazione"""
    crew = InvestigationCrew(api_key, progress_callback, model=model, lang_instruction=lang_instruction, base_url=base_url)
    return crew.investigate(objective, known_people=known_people)


def run_investigation_with_context(objective, existing_context, api_key, progress_callback=None, known_people=None,
                                   model="claude-sonnet-4-20250514", lang_instruction="", base_url=None):
    """Esegue un'investigazione con contesto da investigazione precedente"""
    crew = InvestigationCrew(api_key, progress_callback, model=model, lang_instruction=lang_instruction, base_url=base_url)
    return crew.investigate_with_context(objective, existing_context, known_people=known_people)


# Test
if __name__ == "__main__":
    import os
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        result = run_investigation("Connessioni tra Epstein e l'Ucraina", api_key)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("Set ANTHROPIC_API_KEY environment variable")
