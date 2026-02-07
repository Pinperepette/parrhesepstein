"""
Fact-checker per citazioni EFTA nei report investigativi.
Verifica che ogni codice EFTA citato esista realmente in ChromaDB o su justice.gov.
"""
import re
from app.agents.vectordb import is_document_indexed
from app.services.justice_gov import search_justice_gov


def verify_citations(report_text):
    """
    Estrae tutti i codici EFTA dal report e li verifica contro le fonti.

    Returns:
        dict: {
            "total_citations": int,
            "verified": int,
            "unverified": int,
            "details": [
                {"doc_id": "EFTA01234567", "status": "verified"|"unverified", "source": "chromadb"|"justice.gov"|null},
            ]
        }
    """
    if not report_text:
        return {"total_citations": 0, "verified": 0, "unverified": 0, "details": []}

    # Estrai tutti i codici EFTA unici
    efta_codes = list(set(re.findall(r'EFTA\d{8,}', report_text)))

    if not efta_codes:
        return {"total_citations": 0, "verified": 0, "unverified": 0, "details": []}

    details = []
    verified_count = 0

    for doc_id in sorted(efta_codes):
        source = None

        # Check 1: ChromaDB
        try:
            chroma_result = is_document_indexed(doc_id)
            if chroma_result.get("indexed"):
                source = "chromadb"
        except Exception:
            pass

        # Check 2: justice.gov (solo se non trovato in ChromaDB)
        if not source:
            try:
                gov_result = search_justice_gov(doc_id, size=1)
                if not gov_result.get("error") and gov_result.get("total", 0) > 0:
                    for r in gov_result.get("results", []):
                        if doc_id in r.get("id", "") or doc_id in r.get("url", ""):
                            source = "justice.gov"
                            break
            except Exception:
                pass

        status = "verified" if source else "unverified"
        if source:
            verified_count += 1

        details.append({
            "doc_id": doc_id,
            "status": status,
            "source": source,
        })

    return {
        "total_citations": len(efta_codes),
        "verified": verified_count,
        "unverified": len(efta_codes) - verified_count,
        "details": details,
    }
