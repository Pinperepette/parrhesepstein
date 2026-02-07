"""
/api/relationships/emails, /api/relationships/documents — 2 route
"""
import re
import threading
from flask import Blueprint, jsonify, request
from app.services.justice_gov import search_justice_gov
from app.services.pdf import download_pdf_text
from app.agents.vectordb import extract_entities_from_text

bp = Blueprint("relationships", __name__)


@bp.route('/api/relationships/emails')
def api_relationships_emails():
    """Estrae comunicazioni email dai documenti cercati su justice.gov"""
    try:
        communications = []
        person = request.args.get('person', '').strip()

        if not person:
            return jsonify({'communications': [], 'total': 0, 'searched_person': None})

        all_results = []
        for page in range(10):
            results = search_justice_gov(person, page=page)
            new_results = results.get('results', [])
            if not new_results:
                break
            all_results.extend(new_results)

        email_pattern = re.compile(r'(?:From|Da|Sent by):\s*([^<\n]+?)(?:<[^>]+>)?[\s\n]+(?:To|A|Sent to):\s*([^<\n]+)', re.IGNORECASE)
        subject_pattern = re.compile(r'(?:Subject|Oggetto|Re):\s*(.+?)(?:\n|$)', re.IGNORECASE)

        seen_pairs = set()

        for doc in all_results:
            text = ' '.join(doc.get('snippets', []))
            title = doc.get('title', '')
            doc_id = doc.get('url', '').split('/')[-1].replace('.pdf', '') if doc.get('url') else 'N/A'

            for match in email_pattern.finditer(text):
                from_person = match.group(1).strip()[:50]
                to_person = match.group(2).strip()[:50]

                from_person = re.sub(r'[<>@\[\]]', '', from_person).strip()
                to_person = re.sub(r'[<>@\[\]]', '', to_person).strip()

                if from_person and to_person and len(from_person) > 2 and len(to_person) > 2:
                    pair_key = tuple(sorted([from_person.lower(), to_person.lower()]))
                    if pair_key not in seen_pairs:
                        seen_pairs.add(pair_key)

                        subject_match = subject_pattern.search(text)
                        subject = subject_match.group(1).strip()[:100] if subject_match else title[:100]

                        communications.append({
                            'from': from_person,
                            'to': to_person,
                            'subject': subject,
                            'doc_id': doc_id
                        })

        # Scarica PDF in background
        def _download_bg(docs):
            for doc in docs:
                if doc.get('url'):
                    try:
                        download_pdf_text(doc['url'])
                    except Exception:
                        pass
        threading.Thread(target=_download_bg, args=(all_results,), daemon=True).start()

        return jsonify({
            'communications': communications,
            'total': len(communications),
            'searched_person': person
        })

    except Exception as e:
        import traceback
        return jsonify({
            'error': str(e),
            'traceback': traceback.format_exc(),
            'communications': []
        })


@bp.route('/api/relationships/documents')
def api_relationships_documents():
    """Estrae co-occorrenze e introduzioni dai documenti cercati su justice.gov"""
    try:
        cooccurrences = []
        introductions = []
        person = request.args.get('person', '').strip()

        if not person:
            return jsonify({
                'cooccurrences': [], 'introductions': [],
                'total_cooccurrences': 0, 'total_introductions': 0,
                'searched_person': None, 'documents_searched': 0
            })

        all_results = []
        for page in range(10):
            results = search_justice_gov(person, page=page)
            new_results = results.get('results', [])
            if not new_results:
                break
            all_results.extend(new_results)

        intro_pattern = re.compile(r'(?:introduc|present|meet|connect)(?:ed|ing|s)?\s+(?:to\s+)?([A-Z][a-z]+\s+[A-Z][a-z]+)', re.IGNORECASE)

        for doc in all_results:
            text = ' '.join(doc.get('snippets', []))
            title = doc.get('title', '')
            doc_id = doc.get('url', '').split('/')[-1].replace('.pdf', '') if doc.get('url') else 'N/A'
            full_text = text + ' ' + title

            # Use the shared entity extractor (with false-positive filtering)
            entities = extract_entities_from_text(full_text)
            names_found = set(entities.get('people', []))

            # Also check if the searched person appears
            if person.lower() in full_text.lower():
                names_found.add(person)

            # Co-occurrenze: almeno 2 persone nello stesso documento
            if len(names_found) >= 2:
                cooccurrences.append({
                    'doc_id': doc_id,
                    'people': list(names_found)[:10],
                    'context': title[:100] if title else full_text[:100]
                })

            # Introduzioni: pattern "introduced X to Y"
            for match in intro_pattern.finditer(text):
                introduced = match.group(1)
                introductions.append({
                    'introducer': person,
                    'introduced': introduced,
                    'context': title[:100],
                    'doc_id': doc_id
                })

        # Scarica PDF in background
        def _download_bg(docs):
            for doc in docs:
                if doc.get('url'):
                    try:
                        download_pdf_text(doc['url'])
                    except Exception:
                        pass
        threading.Thread(target=_download_bg, args=(all_results,), daemon=True).start()

        return jsonify({
            'cooccurrences': cooccurrences,
            'introductions': introductions,
            'total_cooccurrences': len(cooccurrences),
            'total_introductions': len(introductions),
            'searched_person': person,
            'documents_searched': len(all_results)
        })

    except Exception as e:
        import traceback
        return jsonify({
            'error': str(e),
            'traceback': traceback.format_exc(),
            'cooccurrences': [],
            'introductions': []
        })
