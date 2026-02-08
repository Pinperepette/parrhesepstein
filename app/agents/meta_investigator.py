"""
Meta-Investigator - Analizza e confronta investigazioni salvate
Trova contraddizioni, punti in comune e lancia nuove ricerche per risolverle.
"""

import re
import json
import requests
from anthropic import Anthropic
from app.services.justice_gov import search_justice_gov
from app.services.pdf import download_pdf_text




def get_document_content(doc_id, snippets=None):
    """Ottiene il contenuto di un documento, con fallback sugli snippet"""
    # Prima cerca il documento per ottenere l'URL
    result = search_justice_gov(doc_id)

    if result.get("results"):
        doc = result["results"][0]
        url = doc.get("url", "")
        doc_snippets = doc.get("snippets", []) or snippets or []

        # Prova a scaricare il PDF
        if url:
            text = download_pdf_text(url)
            if text and len(text) > 100:
                return {"success": True, "source": "pdf", "text": text}

        # Fallback sugli snippet
        if doc_snippets:
            snippet_text = "\n\n".join([s.replace("<em>", "**").replace("</em>", "**") for s in doc_snippets])
            if len(snippet_text) > 50:
                return {"success": True, "source": "snippets", "text": snippet_text}

    return {"success": False, "source": None, "text": ""}


class MetaInvestigator:
    """Analizza investigazioni salvate e risolve contraddizioni"""

    def __init__(self, api_key, progress_callback=None, model="claude-sonnet-4-20250514", lang_instruction="", base_url=None):
        self.client = Anthropic(api_key=api_key, base_url=base_url) if base_url else Anthropic(api_key=api_key)
        self.progress_callback = progress_callback or (lambda x: print(f"[META] {x}"))
        self.model = model
        self.lang_instruction = lang_instruction

    def update_progress(self, msg):
        self.progress_callback(msg)
        print(f"[META] {msg}", flush=True)

    def analyze_investigations(self, investigations):
        """Fase 1: Analizza le investigazioni e trova contraddizioni"""
        self.update_progress("Analisi comparativa delle investigazioni...")

        # Recupera contesto storico da RAG + MongoDB
        self._historical_context = ""
        try:
            from app.agents.context_provider import get_full_context
            # Usa gli obiettivi delle investigazioni come query
            objectives = " ".join([inv.get("objective", "") for inv in investigations[:3]])
            self._historical_context = get_full_context(objectives[:200], rag_results=5, mongo_limit=5)
            if self._historical_context:
                self.update_progress(f"Contesto storico recuperato: {len(self._historical_context)} caratteri")
        except Exception as e:
            print(f"[META] Errore recupero contesto storico: {e}", flush=True)

        # Prepara il contesto
        inv_summaries = []
        for i, inv in enumerate(investigations):
            summary = {
                "id": i + 1,
                "date": str(inv.get("date", "N/A")),
                "objective": inv.get("objective", ""),
                "documents_found": inv.get("documents_found", 0),
                "key_people": [p.get("name") for p in inv.get("analysis", {}).get("key_people", [])],
                "connections": inv.get("analysis", {}).get("connections", []),
                "timeline": inv.get("analysis", {}).get("timeline", [])
            }
            inv_summaries.append(summary)

        # Contesto storico
        historical_ctx = getattr(self, '_historical_context', '') or ''
        historical_section = f"\n{historical_ctx}\n" if historical_ctx else ""

        prompt = f"""Sei un META-INVESTIGATORE che analizza investigazioni precedenti sugli Epstein Files.

HAI {len(investigations)} INVESTIGAZIONI DA CONFRONTARE:

{json.dumps(inv_summaries, indent=2, ensure_ascii=False)}
{historical_section}

Analizza queste investigazioni e identifica:

1. **CONTRADDIZIONI**: Dove le investigazioni si contraddicono? (es: una dice che X è coinvolto, l'altra no)
2. **PUNTI IN COMUNE**: Cosa emerge in modo coerente da tutte le investigazioni?
3. **LACUNE**: Cosa manca? Quali domande restano senza risposta?
4. **LIVELLO DI CONFIDENZA**: Per ogni persona/connessione, quanto è solida la prova?
5. **RICERCHE DA FARE**: Quali ricerche specifiche servono per risolvere le contraddizioni?

Rispondi in JSON:
{{
    "contradictions": [
        {{"topic": "...", "inv1_says": "...", "inv2_says": "...", "resolution_needed": "..."}}
    ],
    "common_findings": [
        {{"finding": "...", "supported_by": [1, 2, ...], "confidence": "alta/media/bassa"}}
    ],
    "gaps": ["..."],
    "people_confidence": [
        {{"name": "...", "confidence": "alta/media/bassa", "reason": "..."}}
    ],
    "searches_needed": ["query1", "query2", ...]
}}
"""

        response = self.client.messages.create(
            model=self.model,
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt + self.lang_instruction}]
        )

        try:
            text = response.content[0].text
            json_match = re.search(r'\{[\s\S]*\}', text)
            if json_match:
                return json.loads(json_match.group())
        except Exception as e:
            print(f"[META ANALYSIS ERROR] {e}")

        return {
            "contradictions": [],
            "common_findings": [],
            "gaps": [],
            "people_confidence": [],
            "searches_needed": []
        }

    def resolve_contradictions(self, analysis):
        """Fase 2: Cerca e ANALIZZA documenti per risolvere le contraddizioni"""
        self.update_progress("Ricerca documenti per risolvere contraddizioni...")

        resolution_docs = []
        searches_done = []
        document_analyses = []

        # Estrai gli ID dei documenti citati nelle contraddizioni
        doc_ids_to_check = set()
        for contradiction in analysis.get("contradictions", []):
            resolution = contradiction.get("resolution_needed", "")
            # Estrai ID documento (formato EFTA...)
            import re
            ids = re.findall(r'EFTA\d+', resolution)
            doc_ids_to_check.update(ids)

        self.update_progress(f"Trovati {len(doc_ids_to_check)} documenti chiave da verificare...")

        # Cerca e scarica i documenti specifici citati
        for doc_id in list(doc_ids_to_check)[:5]:
            self.update_progress(f"Scarico e analizzo {doc_id}...")

            # Usa la nuova funzione che ha fallback sugli snippet
            doc_content = get_document_content(doc_id)

            if doc_content.get("success"):
                text = doc_content.get("text", "")
                source = doc_content.get("source", "unknown")

                self.update_progress(f"Analisi {doc_id} (fonte: {source})...")

                # Analizza il contenuto con Claude
                doc_analysis = self.analyze_document_for_contradiction(
                    doc_id, text, analysis.get("contradictions", [])
                )
                document_analyses.append({
                    "doc_id": doc_id,
                    "source": source,
                    "text_preview": text[:500],
                    "analysis": doc_analysis
                })
            else:
                # Prova comunque a cercare e usare gli snippet dalla ricerca
                result = search_justice_gov(doc_id)
                if result.get("results"):
                    doc = result["results"][0]
                    snippets = doc.get("snippets", [])
                    if snippets:
                        snippet_text = "\n".join([s.replace("<em>", "**").replace("</em>", "**") for s in snippets])
                        doc_analysis = self.analyze_document_for_contradiction(
                            doc_id, snippet_text, analysis.get("contradictions", [])
                        )
                        document_analyses.append({
                            "doc_id": doc_id,
                            "source": "snippets",
                            "text_preview": snippet_text[:500],
                            "analysis": doc_analysis
                        })
                    else:
                        document_analyses.append({
                            "doc_id": doc_id,
                            "source": "none",
                            "text_preview": "Documento non disponibile",
                            "analysis": "Non è stato possibile recuperare il contenuto del documento"
                        })

            # Aggiungi ai risultati
            result = search_justice_gov(doc_id)
            if result.get("results"):
                resolution_docs.append(result["results"][0])
                searches_done.append({
                    "query": doc_id,
                    "total": result.get("total", 0),
                    "docs": result.get("results", [])[:3]
                })

        # Cerca anche per le query suggerite
        for query in analysis.get("searches_needed", [])[:3]:
            self.update_progress(f"Cerco: {query}...")
            result = search_justice_gov(query)
            searches_done.append({
                "query": query,
                "total": result.get("total", 0),
                "docs": result.get("results", [])[:5]
            })
            resolution_docs.extend(result.get("results", [])[:2])

        return {
            "searches_done": searches_done,
            "resolution_docs": resolution_docs,
            "document_analyses": document_analyses
        }

    def analyze_document_for_contradiction(self, doc_id, text, contradictions):
        """Analizza un documento specifico per risolvere le contraddizioni"""

        contradictions_text = "\n".join([
            f"- {c.get('topic', 'N/A')}: {c.get('resolution_needed', '')}"
            for c in contradictions
        ])

        prompt = f"""Analizza questo documento degli Epstein Files per risolvere le contraddizioni.

DOCUMENTO: {doc_id}

CONTENUTO:
{text[:8000]}

CONTRADDIZIONI DA RISOLVERE:
{contradictions_text}

ISTRUZIONI - DEVI ESSERE PRECISO E RIGOROSO:
- Cita il TESTO ESATTO dal documento, tra virgolette
- Se il documento dice "Salvini peaked too early", scrivi ESATTAMENTE quello, non "leaked too early"
- Se non trovi prove, scrivi "NESSUNA PROVA TROVATA" - non inventare

DISTINZIONE CRITICA TRA TIPI DI EVIDENZA:
1. **COMUNICAZIONE DIRETTA**: Email scritta DALLA persona investigata o indirizzata A lei con RISPOSTA
   → Questa è l'UNICA prova di coinvolgimento diretto
2. **MENZIONE DA TERZI**: Il nome appare in email tra ALTRE persone
   → NON è prova di coinvolgimento, solo che qualcuno ne parla
3. **ARTICOLO/NOTIZIA**: Testo giornalistico salvato nei file
   → NON è prova di nulla, è solo un articolo

Per ogni documento, DEVI specificare:
- CHI ha scritto il messaggio (mittente)
- A CHI era destinato (destinatario)
- La persona investigata ha MAI RISPOSTO direttamente?

Esempio: Se trovi "heading to meet with Salvini", devi dire:
"Il documento mostra che [MITTENTE] scrive a [DESTINATARIO] di voler incontrare Salvini.
NON c'è risposta di Salvini. NON c'è prova che l'incontro sia avvenuto.
Salvini è solo MENZIONATO, non è un partecipante attivo alla comunicazione."

Rispondi in modo PRECISO:
1. CITAZIONI ESATTE: Copia/incolla i passaggi rilevanti dal documento
2. TIPO DI EVIDENZA: È una prova diretta, una menzione, o niente?
3. VERDETTO: Quale versione delle contraddizioni è supportata? O nessuna?

NON PARAFRASARE - cita il testo esatto."""

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1500,
                messages=[{"role": "user", "content": prompt + self.lang_instruction}]
            )
            return response.content[0].text
        except Exception as e:
            return f"Errore analisi: {e}"

    def synthesize_verdict(self, investigations, analysis, resolution):
        """Fase 3: Sintetizza un verdetto finale basato sulle PROVE"""
        self.update_progress("Sintesi verdetto finale basato sulle prove...")

        # Prepara il contesto delle analisi dei documenti
        doc_analyses_text = ""
        for da in resolution.get("document_analyses", []):
            doc_analyses_text += f"\n\n### Documento {da.get('doc_id', 'N/A')}:\n{da.get('analysis', 'N/A')}"

        docs_context = ""
        for doc in resolution.get("resolution_docs", [])[:10]:
            snippets = " | ".join(s[:200] for s in doc.get("snippets", [])[:2])
            docs_context += f"\n- {doc.get('id', 'N/A')}: {snippets}"

        # Contesto storico
        historical_ctx = getattr(self, '_historical_context', '') or ''
        historical_section = f"\n{historical_ctx}\n" if historical_ctx else ""

        prompt = f"""Sei un META-INVESTIGATORE che deve emettere un VERDETTO FINALE basato su PROVE DOCUMENTALI.
{historical_section}
ANALISI PRECEDENTE:
{json.dumps(analysis, indent=2, ensure_ascii=False)}

ANALISI DETTAGLIATA DEI DOCUMENTI CHIAVE:
{doc_analyses_text}

ALTRI DOCUMENTI TROVATI:
{docs_context}

Basandoti sulle PROVE REALI nei documenti, scrivi un VERDETTO FINALE in italiano che:

1. **RISOLVE LE CONTRADDIZIONI**: Per ogni contraddizione, indica quale versione è più supportata dai documenti
2. **CLASSIFICA LE PERSONE**: Per ogni persona chiave, assegna un livello basato sulle PROVE REALI:
   - COMUNICAZIONE DIRETTA: Email scritte DA o A questa persona con risposta (UNICA prova forte)
   - MENZIONATO DA TERZI: Il nome appare in comunicazioni tra ALTRI (NON è prova di coinvolgimento)
   - SOLO IN ARTICOLI: Appare solo in notizie/articoli salvati (NON è prova)
   - NESSUNA EVIDENZA: Nome non trovato nei documenti

   ATTENZIONE: Se una persona è solo MENZIONATA da altri, NON puoi dire che sia "coinvolta" o "parte della rete".
   Dire "qualcuno vuole incontrare X" NON significa che X sia complice di nulla.
3. **MAPPA DELLE CONNESSIONI VERIFICATE**: Solo le connessioni con evidenza documentale
4. **DOMANDE ANCORA APERTE**: Cosa non siamo riusciti a risolvere

Formato del verdetto:

## VERDETTO FINALE

### Risoluzione Contraddizioni
[Per ogni contraddizione...]

### Classificazione Persone
| Persona | Livello | Evidenza |
|---------|---------|----------|
| ... | PROVATO/PROBABILE/POSSIBILE/NON PROVATO | ... |

### Connessioni Verificate
[Solo quelle con documenti a supporto]

### Domande Aperte
[Cosa resta da investigare]

### Cosa NON È Provato
[Elenca esplicitamente le conclusioni che NON si possono trarre dai documenti.
Se una persona è solo menzionata da altri, scrivi: "Non c'è prova che X abbia mai comunicato direttamente o sia coinvolto attivamente"]

### Conclusione
[Sintesi ONESTA in 3-5 frasi. Non esagerare le conclusioni oltre le prove.]
"""

        response = self.client.messages.create(
            model=self.model,
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt + self.lang_instruction}]
        )

        return response.content[0].text

    def investigate(self, investigations):
        """Esegue la meta-investigazione completa"""
        if len(investigations) < 2:
            return {
                "success": False,
                "error": "Servono almeno 2 investigazioni da confrontare"
            }

        self.update_progress(f"Avvio meta-investigazione su {len(investigations)} investigazioni...")

        # Fase 1: Analisi comparativa
        analysis = self.analyze_investigations(investigations)
        self.update_progress(f"Trovate {len(analysis.get('contradictions', []))} contraddizioni")

        # Fase 2: Ricerca per risolvere
        resolution = self.resolve_contradictions(analysis)
        self.update_progress(f"Analizzati {len(resolution.get('resolution_docs', []))} nuovi documenti")

        # Fase 3: Verdetto finale
        verdict = self.synthesize_verdict(investigations, analysis, resolution)

        return {
            "success": True,
            "investigations_analyzed": len(investigations),
            "analysis": analysis,
            "resolution": resolution,
            "verdict": verdict
        }


def run_meta_investigation(investigations, api_key, progress_callback=None,
                           model="claude-sonnet-4-20250514", lang_instruction="", base_url=None):
    """Funzione principale per eseguire una meta-investigazione"""
    investigator = MetaInvestigator(api_key, progress_callback, model=model, lang_instruction=lang_instruction, base_url=base_url)
    return investigator.investigate(investigations)
