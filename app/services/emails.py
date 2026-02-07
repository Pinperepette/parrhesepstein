"""
Ricerca nel dataset email Epstein (parquet).
"""
from app.extensions import EMAILS_DF


def search_emails(query, limit=50):
    """Cerca nel dataset email di Epstein"""
    if EMAILS_DF is None:
        return {"total": 0, "results": [], "error": "Dataset email non caricato"}

    query_lower = query.lower()

    mask = (
        EMAILS_DF['subject'].fillna('').str.lower().str.contains(query_lower, regex=False) |
        EMAILS_DF['from_address'].fillna('').str.lower().str.contains(query_lower, regex=False) |
        EMAILS_DF['to_address'].fillna('').str.lower().str.contains(query_lower, regex=False) |
        EMAILS_DF['message_html'].fillna('').str.lower().str.contains(query_lower, regex=False) |
        EMAILS_DF['other_recipients'].fillna('').str.lower().str.contains(query_lower, regex=False)
    )

    matches = EMAILS_DF[mask].head(limit)

    results = []
    for _, row in matches.iterrows():
        msg = str(row.get('message_html', ''))
        snippet = ""
        if query_lower in msg.lower():
            idx = msg.lower().find(query_lower)
            start = max(0, idx - 100)
            end = min(len(msg), idx + len(query_lower) + 100)
            snippet = "..." + msg[start:end] + "..."

        results.append({
            "id": str(row.get('id', '')),
            "doc_id": str(row.get('document_id', '')),
            "source": str(row.get('source_filename', '')),
            "from": str(row.get('from_address', '')),
            "to": str(row.get('to_address', '')),
            "other_recipients": str(row.get('other_recipients', '')),
            "subject": str(row.get('subject', '')),
            "date": str(row.get('timestamp_raw', '')),
            "date_iso": str(row.get('timestamp_iso', '')),
            "message": msg[:2000],
            "snippet": snippet,
        })

    return {"total": int(mask.sum()), "results": results, "source": "huggingface_emails"}
