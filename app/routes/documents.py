"""
/api/documents/*, /api/vectordb/*, /api/archive/ask — 6 route
"""
import os
from flask import Blueprint, jsonify, request, send_from_directory
from app.config import DOCUMENTS_DIR
from app.services.documents import list_local_documents, get_document_text
from app.services.settings import get_model, get_language_instruction
from app.services.claude import get_anthropic_client, call_claude_with_retry

bp = Blueprint("documents", __name__)


@bp.route('/api/documents')
def api_documents_list():
    try:
        docs = list_local_documents()
        return jsonify({'documents': docs, 'total': len(docs)})
    except Exception as e:
        return jsonify({'error': str(e), 'documents': [], 'total': 0})


@bp.route('/api/documents/<doc_id>/text')
def api_document_text(doc_id):
    text = get_document_text(doc_id)
    if text is None:
        return jsonify({'error': 'Documento non trovato'}), 404
    return jsonify({'doc_id': doc_id, 'text': text, 'length': len(text)})


@bp.route('/api/documents/<doc_id>/pdf')
def api_document_pdf(doc_id):
    pdf_path = os.path.join(DOCUMENTS_DIR, f"{doc_id}.pdf")
    if not os.path.exists(pdf_path):
        return jsonify({'error': 'PDF non trovato'}), 404
    return send_from_directory(DOCUMENTS_DIR, f"{doc_id}.pdf", mimetype='application/pdf')


@bp.route('/api/vectordb/stats', methods=['GET'])
def api_vectordb_stats():
    from app.agents.vectordb import get_collection_stats
    from app.services.documents import count_local_txt
    stats = get_collection_stats()
    stats['local_documents'] = count_local_txt()
    return jsonify(stats)


@bp.route('/api/vectordb/check/<doc_id>', methods=['GET'])
def api_vectordb_check(doc_id):
    from app.agents.vectordb import is_document_indexed
    result = is_document_indexed(doc_id)
    return jsonify(result)


@bp.route('/api/archive/ask', methods=['POST'])
def api_archive_ask():
    from app.agents.vectordb import semantic_search

    data = request.json
    question = data.get('question', '')
    n_context = data.get('n_context', 10)

    if not question:
        return jsonify({'error': 'Domanda richiesta'}), 400

    try:
        rag_results = semantic_search(question, n_results=n_context)
        if not rag_results:
            return jsonify({'answer': 'Nessun documento trovato nel database vettoriale. Indicizza prima i documenti.', 'sources': []})

        context = "## DOCUMENTI DAL DATABASE VETTORIALE\n\n"
        sources = []
        for i, r in enumerate(rag_results, 1):
            doc_id = r.get('metadata', {}).get('doc_id', r.get('title', f'doc_{i}'))
            relevance = r.get('relevance', 0)
            context += f"### [{doc_id}] (relevance: {relevance:.2f})\n{r.get('text', '')}\n\n---\n\n"
            sources.append({'doc_id': doc_id, 'relevance': relevance, 'title': r.get('title', '')})

        prompt = f"""{context}

---

Rispondi a questa domanda basandoti ESCLUSIVAMENTE sui documenti forniti sopra.
Cita SEMPRE il codice EFTA del documento quando fai riferimento a informazioni specifiche.
Se non trovi informazioni sufficienti, dillo chiaramente.

DOMANDA: {question}"""

        client = get_anthropic_client()
        message = call_claude_with_retry(
            client, model=get_model(), max_tokens=4096,
            messages=[{"role": "user", "content": prompt + get_language_instruction()}],
        )
        return jsonify({'answer': message.content[0].text, 'sources': sources})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
