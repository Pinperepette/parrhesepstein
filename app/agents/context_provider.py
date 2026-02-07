"""
Context Provider - Accesso centralizzato a RAG (ChromaDB) e MongoDB.
Fornisce contesto storico a tutti gli agenti investigativi, cazzi e mazzi.
"""
from datetime import datetime
from app.extensions import db_epstein


def get_rag_context(query, n_results=5):
    """Cerca nel database vettoriale ChromaDB e ritorna contesto formattato."""
    try:
        from app.agents.vectordb import semantic_search
        results = semantic_search(query, n_results=n_results)
        if not results:
            return ""
        context = "## DOCUMENTI RILEVANTI DAL DATABASE VETTORIALE\n\n"
        for i, r in enumerate(results, 1):
            title = r.get('title', 'Unknown')
            url = r.get('url', '')
            relevance = r.get('relevance', 0)
            text = r.get('text', '')[:500]
            context += f"### [{i}] {title}\n"
            context += f"**Rilevanza:** {relevance:.2f}\n"
            if url:
                context += f"**URL:** {url}\n"
            context += f"{text}\n\n"
        return context
    except Exception as e:
        print(f"[CONTEXT_PROVIDER] Errore RAG: {e}")
        return ""


def get_mongodb_context(query, limit=10):
    """Cerca nello storico MongoDB (ricerche, analisi, investigazioni)."""
    try:
        context_parts = []

        try:
            searches = list(db_epstein["searches"].find(
                {"query": {"$regex": query, "$options": "i"}},
                {"query": 1, "total_results": 1, "date": 1, "results_sample": {"$slice": 3}},
            ).sort("date", -1).limit(limit))
            if searches:
                section = "### Ricerche precedenti correlate\n"
                for s in searches:
                    date = s.get('date', 'N/A')
                    if isinstance(date, datetime):
                        date = date.isoformat()
                    section += f"- **{s.get('query', '')}** ({s.get('total_results', 0)} risultati, {date})\n"
                context_parts.append(section)
        except Exception:
            pass

        try:
            analyses = list(db_epstein["analyses"].find(
                {"$or": [
                    {"question": {"$regex": query, "$options": "i"}},
                    {"result_text": {"$regex": query, "$options": "i"}},
                ]},
                {"question": 1, "date": 1, "result_text": {"$slice": 500}},
            ).sort("date", -1).limit(5))
            if analyses:
                section = "### Analisi AI precedenti\n"
                for a in analyses:
                    q = a.get('question', 'N/A')
                    text = str(a.get('result_text', ''))[:300]
                    section += f"- **Domanda:** {q}\n  {text}...\n"
                context_parts.append(section)
        except Exception:
            pass

        try:
            deep = list(db_epstein["deep_analyses"].find(
                {"$or": [
                    {"question": {"$regex": query, "$options": "i"}},
                    {"response": {"$regex": query, "$options": "i"}},
                ]},
                {"question": 1, "date": 1, "response": 1, "mode": 1},
            ).sort("date", -1).limit(5))
            if deep:
                section = "### Analisi Detective precedenti\n"
                for d in deep:
                    q = d.get('question', 'N/A')
                    resp = str(d.get('response', ''))[:300]
                    section += f"- **[{d.get('mode', 'N/A')}]** {q}\n  {resp}...\n"
                context_parts.append(section)
        except Exception:
            pass

        try:
            investigations = list(db_epstein["crew_investigations"].find(
                {"$or": [
                    {"objective": {"$regex": query, "$options": "i"}},
                    {"report": {"$regex": query, "$options": "i"}},
                ]},
                {"objective": 1, "date": 1, "documents_found": 1, "report": 1},
            ).sort("date", -1).limit(5))
            if investigations:
                section = "### Investigazioni Crew precedenti\n"
                for inv in investigations:
                    obj = inv.get('objective', 'N/A')
                    report = str(inv.get('report', ''))[:300]
                    section += f"- **{obj}** ({inv.get('documents_found', 0)} docs)\n  {report}...\n"
                context_parts.append(section)
        except Exception:
            pass

        if not context_parts:
            return ""
        return "## STORICO INVESTIGAZIONI PRECEDENTI\n\n" + "\n".join(context_parts)
    except Exception as e:
        print(f"[CONTEXT_PROVIDER] Errore MongoDB: {e}")
        return ""


def get_full_context(query, rag_results=5, mongo_limit=10):
    """Combina RAG + MongoDB in un unico blocco di contesto."""
    parts = []
    rag = get_rag_context(query, n_results=rag_results)
    if rag:
        parts.append(rag)
    mongo = get_mongodb_context(query, limit=mongo_limit)
    if mongo:
        parts.append(mongo)
    if not parts:
        return ""
    header = "# CONTESTO DA RICERCHE E ANALISI PRECEDENTI\n\n"
    return header + "\n---\n\n".join(parts) + "\n\n---\n"
