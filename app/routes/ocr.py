"""
/api/pdf-text, /api/ocr-status, /api/extract-images, /api/extract-images-batch — 4 route
"""
import requests
from flask import Blueprint, jsonify, request
from app.services.pdf import download_pdf_text, extract_images_from_pdf
from app.services.claude import get_claude_api_key
from app.extensions import OCR_AVAILABLE, PYMUPDF_AVAILABLE

bp = Blueprint("ocr", __name__)


@bp.route('/api/pdf-text', methods=['POST'])
def api_pdf_text():
    """Restituisce il testo raw di un PDF"""
    data = request.json
    url = data.get('url', '')
    use_ocr = data.get('use_ocr', False)
    use_claude_vision = data.get('use_claude_vision', False)

    if not url:
        return jsonify({"error": "URL richiesto"}), 400

    text = download_pdf_text(url, use_ocr=use_ocr, use_claude_vision=use_claude_vision)

    return jsonify({
        "url": url,
        "text": text,
        "length": len(text),
        "method": "claude_vision" if use_claude_vision else ("tesseract" if use_ocr else "pypdf2"),
        "ocr_available": OCR_AVAILABLE
    })


@bp.route('/api/ocr-status')
def api_ocr_status():
    """Verifica lo stato delle funzionalità OCR"""
    tesseract_ok = False
    if OCR_AVAILABLE:
        try:
            import pytesseract
            tesseract_ok = pytesseract.get_tesseract_version() is not None
        except Exception:
            pass

    return jsonify({
        "pdf2image": OCR_AVAILABLE,
        "tesseract": tesseract_ok,
        "claude_vision": get_claude_api_key() is not None
    })


@bp.route('/api/extract-images', methods=['POST'])
def api_extract_images():
    """Estrae le immagini incorporate da un PDF"""
    data = request.json
    url = data.get('url', '')

    if not url:
        return jsonify({"error": "URL richiesto"}), 400

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:146.0) Gecko/20100101 Firefox/146.0",
            "Cookie": "justiceGovAgeVerified=true",
            "Referer": "https://www.justice.gov/epstein",
        }
        response = requests.get(url, headers=headers, timeout=120, allow_redirects=True)
        response.raise_for_status()

        content = response.content
        if not content.startswith(b'%PDF'):
            return jsonify({"error": "Il file non è un PDF valido"}), 400

        result = extract_images_from_pdf(content)
        result['url'] = url
        result['pymupdf_available'] = PYMUPDF_AVAILABLE

        return jsonify(result)

    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"Errore download: {str(e)}"}), 500
    except Exception as e:
        return jsonify({"error": f"Errore: {str(e)}"}), 500


@bp.route('/api/extract-images-batch', methods=['POST'])
def api_extract_images_batch():
    """Estrae immagini da più PDF in parallelo"""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    data = request.json
    urls = data.get('urls', [])
    max_workers = min(data.get('max_workers', 5), 10)

    if not urls:
        return jsonify({"error": "Lista URL richiesta"}), 400

    def process_url(url):
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:146.0) Gecko/20100101 Firefox/146.0",
                "Cookie": "justiceGovAgeVerified=true",
                "Referer": "https://www.justice.gov/epstein",
            }
            response = requests.get(url, headers=headers, timeout=120, allow_redirects=True)
            response.raise_for_status()

            content = response.content
            if not content.startswith(b'%PDF'):
                return {"url": url, "error": "Non è un PDF valido", "images": []}

            result = extract_images_from_pdf(content)
            result['url'] = url
            return result
        except Exception as e:
            return {"url": url, "error": str(e), "images": []}

    results = []
    total_images = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(process_url, url): url for url in urls[:20]}

        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            total_images += len(result.get('images', []))

    return jsonify({
        "results": results,
        "total_pdfs": len(results),
        "total_images": total_images
    })
