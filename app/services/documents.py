"""
Operazioni su documenti locali (DOCUMENTS_DIR).
"""
import os
from app.config import DOCUMENTS_DIR


def list_local_documents():
    """Lista documenti salvati localmente"""
    docs = []
    if not os.path.exists(DOCUMENTS_DIR):
        return docs

    seen_ids = set()
    for fname in os.listdir(DOCUMENTS_DIR):
        if fname.endswith('.pdf') or fname.endswith('.txt'):
            doc_id = fname.rsplit('.', 1)[0]
            if doc_id in seen_ids:
                continue
            seen_ids.add(doc_id)

            pdf_path = os.path.join(DOCUMENTS_DIR, f"{doc_id}.pdf")
            txt_path = os.path.join(DOCUMENTS_DIR, f"{doc_id}.txt")

            docs.append({
                'doc_id': doc_id,
                'has_pdf': os.path.exists(pdf_path),
                'has_text': os.path.exists(txt_path),
                'pdf_size': os.path.getsize(pdf_path) if os.path.exists(pdf_path) else 0,
                'text_size': os.path.getsize(txt_path) if os.path.exists(txt_path) else 0,
            })

    docs.sort(key=lambda d: d['doc_id'])
    return docs


def get_document_text(doc_id):
    """Restituisce il testo estratto di un documento"""
    txt_path = os.path.join(DOCUMENTS_DIR, f"{doc_id}.txt")
    if not os.path.exists(txt_path):
        return None
    with open(txt_path, 'r', encoding='utf-8') as f:
        return f.read()


def get_document_pdf_path(doc_id):
    """Restituisce il path del PDF se esiste"""
    pdf_path = os.path.join(DOCUMENTS_DIR, f"{doc_id}.pdf")
    if os.path.exists(pdf_path):
        return pdf_path
    return None


def count_local_txt():
    """Conta i file .txt nella directory documenti"""
    if not os.path.exists(DOCUMENTS_DIR):
        return 0
    return len([f for f in os.listdir(DOCUMENTS_DIR) if f.endswith('.txt')])
