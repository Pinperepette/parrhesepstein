"""
Orchestrator Agent - Coordina investigazioni multi-livello
Analizza risultati, identifica lead, approfondisce automaticamente
"""

import re
import json
from datetime import datetime


class InvestigationOrchestrator:
    """Orchestratore che coordina investigazioni approfondite"""

    def __init__(self, search_fn, download_fn, analyze_fn):
        """
        Args:
            search_fn: Funzione per cercare su justice.gov
            download_fn: Funzione per scaricare PDF
            analyze_fn: Funzione per analizzare con Claude
        """
        self.search = search_fn
        self.download = download_fn
        self.analyze = analyze_fn

        self.investigated_docs = set()
        self.findings = []
        self.leads_queue = []
        self.iteration = 0
        self.max_iterations = 5

    def extract_doc_ids(self, text):
        """Estrae tutti i document ID (EFTA...) dal testo"""
        return set(re.findall(r'EFTA\d+', str(text)))

    def extract_leads(self, analysis_result):
        """Estrae lead da approfondire dall'analisi"""
        leads = []

        # Cerca documenti menzionati
        if isinstance(analysis_result, dict):
            # Da critical_findings
            for finding in analysis_result.get('critical_findings', []):
                doc_ids = self.extract_doc_ids(finding)
                for doc_id in doc_ids:
                    if doc_id not in self.investigated_docs:
                        leads.append({
                            'type': 'document',
                            'id': doc_id,
                            'reason': finding[:200],
                            'priority': 'high' if any(kw in finding.lower() for kw in ['trafficking', 'transfer', 'payment', 'fbi']) else 'medium'
                        })

            # Da document_analysis
            for doc in analysis_result.get('document_analysis', []):
                if 'trafficking' in str(doc).lower() or 'transfer' in str(doc).lower():
                    # Questo documento merita approfondimento
                    doc_id = doc.get('doc_id', '')
                    if doc_id and doc_id not in self.investigated_docs:
                        leads.append({
                            'type': 'deep_analysis',
                            'id': doc_id,
                            'reason': doc.get('key_content', '')[:200],
                            'priority': 'high'
                        })

            # Da recommendations
            for rec in analysis_result.get('recommendations', []):
                doc_ids = self.extract_doc_ids(rec)
                for doc_id in doc_ids:
                    if doc_id not in self.investigated_docs:
                        leads.append({
                            'type': 'recommended',
                            'id': doc_id,
                            'reason': rec[:200],
                            'priority': 'medium'
                        })

        # Ordina per priorità
        priority_order = {'high': 0, 'medium': 1, 'low': 2}
        leads.sort(key=lambda x: priority_order.get(x.get('priority', 'low'), 2))

        return leads

    def should_continue(self, leads):
        """Decide se continuare l'investigazione"""
        if self.iteration >= self.max_iterations:
            return False, "Raggiunto limite massimo iterazioni"

        high_priority = [l for l in leads if l.get('priority') == 'high']
        if high_priority:
            return True, f"Trovati {len(high_priority)} lead ad alta priorità"

        if len(leads) > 0 and self.iteration < 3:
            return True, f"Trovati {len(leads)} lead da investigare"

        return False, "Nessun lead significativo trovato"

    def investigate_lead(self, lead):
        """Investiga un singolo lead"""
        doc_id = lead.get('id', '')
        if not doc_id or doc_id in self.investigated_docs:
            return None

        self.investigated_docs.add(doc_id)

        result = {
            'doc_id': doc_id,
            'lead_type': lead.get('type'),
            'reason': lead.get('reason'),
            'content': None,
            'analysis': None
        }

        # Cerca e scarica il documento
        try:
            search_result = self.search(doc_id)
            if search_result.get('results'):
                doc = search_result['results'][0]
                doc_url = doc.get('url', '')

                if doc_url:
                    text = self.download(doc_url)
                    if text and not text.startswith('[Errore'):
                        result['content'] = text[:5000]
                        result['title'] = doc.get('title', '')

                        # Aggiungi contesto RAG se disponibile
                        rag_section = ""
                        rag_ctx = getattr(self, '_rag_context', '')
                        if rag_ctx:
                            rag_section = f"\nCONTESTO DA ANALISI PRECEDENTI:\n{rag_ctx[:2000]}\n"

                        # Analizza il contenuto
                        analysis_prompt = f"""Analizza questo documento degli Epstein Files.

DOCUMENTO: {doc_id}
TITOLO: {doc.get('title', 'N/A')}
MOTIVO INVESTIGAZIONE: {lead.get('reason', 'N/A')}
{rag_section}
CONTENUTO:
{text[:4000]}

Rispondi in JSON:
{{
    "summary": "Cosa contiene questo documento (2-3 frasi)",
    "key_findings": ["scoperta 1", "scoperta 2"],
    "people_mentioned": ["persona 1", "persona 2"],
    "financial_data": ["trasferimento/importo se presente"],
    "red_flags": ["elemento sospetto 1"],
    "follow_up_needed": ["cosa investigare dopo"],
    "relevance_score": 1-10
}}"""

                        analysis = self.analyze(analysis_prompt)
                        result['analysis'] = analysis

        except Exception as e:
            result['error'] = str(e)

        return result

    def run_investigation(self, initial_result, callback=None):
        """
        Esegue investigazione iterativa

        Args:
            initial_result: Risultato iniziale del merge
            callback: Funzione chiamata ad ogni iterazione per aggiornamenti

        Returns:
            Risultato completo dell'investigazione
        """
        all_findings = []
        investigation_log = []

        # Recupera contesto storico da RAG + MongoDB
        try:
            from app.agents.context_provider import get_rag_context
            # Usa le critical_findings come query
            query_parts = []
            if isinstance(initial_result, dict):
                for f in initial_result.get('critical_findings', [])[:3]:
                    query_parts.append(str(f)[:100])
            query = " ".join(query_parts) if query_parts else "Epstein investigation"
            rag_context = get_rag_context(query, n_results=5)
            if rag_context:
                self._rag_context = rag_context
                print(f"[ORCHESTRATOR] Contesto RAG recuperato: {len(rag_context)} caratteri", flush=True)
        except Exception as e:
            print(f"[ORCHESTRATOR] Errore recupero contesto: {e}", flush=True)

        # Estrai lead iniziali
        leads = self.extract_leads(initial_result)
        self.leads_queue.extend(leads)

        investigation_log.append({
            'iteration': 0,
            'action': 'initial_analysis',
            'leads_found': len(leads),
            'high_priority': len([l for l in leads if l.get('priority') == 'high'])
        })

        while self.leads_queue:
            self.iteration += 1

            # Controlla se continuare
            should_continue, reason = self.should_continue(self.leads_queue)

            if not should_continue:
                investigation_log.append({
                    'iteration': self.iteration,
                    'action': 'stopped',
                    'reason': reason
                })
                break

            # Prendi il prossimo lead
            current_lead = self.leads_queue.pop(0)

            if callback:
                callback({
                    'iteration': self.iteration,
                    'investigating': current_lead.get('id'),
                    'reason': current_lead.get('reason'),
                    'remaining_leads': len(self.leads_queue)
                })

            # Investiga
            finding = self.investigate_lead(current_lead)

            if finding and finding.get('content'):
                all_findings.append(finding)

                # Estrai nuovi lead dall'analisi
                if finding.get('analysis'):
                    new_leads = self.extract_leads(finding['analysis'])
                    # Aggiungi solo lead non già investigati
                    for lead in new_leads:
                        if lead['id'] not in self.investigated_docs:
                            self.leads_queue.append(lead)

                investigation_log.append({
                    'iteration': self.iteration,
                    'action': 'investigated',
                    'doc_id': current_lead.get('id'),
                    'new_leads': len(new_leads) if finding.get('analysis') else 0
                })

        return {
            'iterations': self.iteration,
            'documents_investigated': list(self.investigated_docs),
            'findings': all_findings,
            'investigation_log': investigation_log,
            'remaining_leads': self.leads_queue[:10]  # Lead non investigati
        }


def create_orchestrated_merge(investigations, search_fn, download_fn, analyze_fn, initial_merge_result):
    """
    Crea un merge orchestrato che approfondisce automaticamente

    Returns:
        Risultato arricchito con approfondimenti
    """
    orchestrator = InvestigationOrchestrator(search_fn, download_fn, analyze_fn)

    # Esegui investigazione approfondita
    deep_results = orchestrator.run_investigation(initial_merge_result)

    # Combina risultati
    enriched_result = {
        **initial_merge_result,
        'deep_investigation': deep_results,
        'total_documents_analyzed': len(deep_results['documents_investigated']),
        'investigation_complete': len(deep_results['remaining_leads']) == 0
    }

    return enriched_result
