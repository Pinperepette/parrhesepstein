"""
/api/search, /api/searches, /api/download-pdf, /api/search-emails,
/api/search-multi, /api/semantic-search, /api/searches/<id> DELETE — 7 route
"""
import threading
from datetime import datetime
from flask import Blueprint, jsonify, request
from bson import ObjectId
from app.services.justice_gov import search_justice_gov
from app.services.pdf import download_pdf_text
from app.services.emails import search_emails
from app.extensions import searches_collection


def _download_results_bg(results):
    """Scarica i PDF dei risultati in background."""
    for doc in results:
        if doc.get('url'):
            try:
                download_pdf_text(doc['url'])
            except Exception:
                pass

bp = Blueprint("search", __name__)


@bp.route('/api/search', methods=['POST'])
def api_search():
    data = request.json
    query = data.get('query', '')
    page = data.get('page', 0)

    if not query:
        return jsonify({"error": "Query richiesta"}), 400

    results = search_justice_gov(query, page)

    if results.get('total', 0) > 0:
        search_doc = {
            'date': datetime.now().isoformat(),
            'query': query,
            'total_results': results.get('total', 0),
            'results_sample': results.get('results', [])[:10],
            'type': 'search'
        }
        try:
            searches_collection.insert_one(search_doc)
            print(f"[SEARCH] Salvata ricerca: '{query}' ({results.get('total', 0)} risultati)", flush=True)
            results['saved'] = True
        except Exception as e:
            print(f"[SEARCH] Errore salvataggio: {e}", flush=True)
            results['saved'] = False

        # Scarica PDF in background
        threading.Thread(target=_download_results_bg, args=(results.get('results', []),), daemon=True).start()

    return jsonify(results)


@bp.route('/api/searches', methods=['GET'])
def api_get_searches():
    """Recupera tutte le ricerche salvate"""
    try:
        searches = list(searches_collection.find().sort('date', -1).limit(50))
        for s in searches:
            s['_id'] = str(s['_id'])
        return jsonify({'searches': searches})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/api/download-pdf', methods=['POST'])
def api_download_pdf():
    """Scarica e estrae testo da un PDF"""
    data = request.json
    url = data.get('url', '')

    if not url:
        return jsonify({"error": "URL richiesto"}), 400

    text = download_pdf_text(url)
    return jsonify({"text": text[:50000], "length": len(text)})


@bp.route('/api/search-emails', methods=['POST'])
def api_search_emails():
    """Cerca nel dataset email di Epstein"""
    data = request.json
    query = data.get('query', '')
    limit = data.get('limit', 50)

    if not query:
        return jsonify({"error": "Query richiesta"}), 400

    results = search_emails(query, limit)
    return jsonify(results)


@bp.route('/api/search-multi', methods=['POST'])
def api_search_multi():
    """Ricerca multipla: justice.gov + email locali"""
    data = request.json
    query = data.get('query', '')
    page = data.get('page', 0)

    if not query:
        return jsonify({"error": "Query richiesta"}), 400

    justice_results = search_justice_gov(query, page)
    email_results = search_emails(query, 50)

    total_combined = justice_results.get('total', 0) + email_results.get('total', 0)
    if total_combined > 0:
        search_doc = {
            'date': datetime.now().isoformat(),
            'query': query,
            'total_results': total_combined,
            'justice_total': justice_results.get('total', 0),
            'email_total': email_results.get('total', 0),
            'results_sample': justice_results.get('results', [])[:5] + email_results.get('results', [])[:5],
            'type': 'search_multi'
        }
        try:
            searches_collection.insert_one(search_doc)
            print(f"[SEARCH-MULTI] Salvata: '{query}' (justice:{justice_results.get('total', 0)}, email:{email_results.get('total', 0)})", flush=True)
        except Exception as e:
            print(f"[SEARCH-MULTI] Errore salvataggio: {e}", flush=True)

    # Scarica PDF in background
    justice_docs = justice_results.get('results', [])
    if justice_docs:
        threading.Thread(target=_download_results_bg, args=(justice_docs,), daemon=True).start()

    return jsonify({
        "query": query,
        "justice_gov": {
            "total": justice_results.get('total', 0),
            "results": justice_docs
        },
        "emails": {
            "total": email_results.get('total', 0),
            "results": email_results.get('results', [])
        }
    })


@bp.route('/api/semantic-search', methods=['POST'])
def api_semantic_search():
    """Ricerca semantica nei documenti indicizzati"""
    from app.agents.vectordb import semantic_search

    data = request.json
    query = data.get('query', '')
    n_results = data.get('n_results', 20)

    if not query:
        return jsonify({"error": "Query richiesta"}), 400

    try:
        results = semantic_search(query, n_results)
        return jsonify({"results": results, "count": len(results)})
    except Exception as e:
        return jsonify({"error": str(e), "results": []})


@bp.route('/api/searches/<search_id>', methods=['DELETE'])
def api_delete_search(search_id):
    """Elimina una ricerca salvata"""
    try:
        try:
            result = searches_collection.delete_one({'_id': ObjectId(search_id)})
        except Exception:
            result = searches_collection.delete_one({'_id': search_id})

        if result.deleted_count > 0:
            return jsonify({'success': True})
        return jsonify({'error': 'Ricerca non trovata'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500
