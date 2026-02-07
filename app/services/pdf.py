"""
Download e estrazione testo da PDF: PyPDF2, Tesseract, Claude Vision.
"""
import os
import io
import re
import base64
import threading
import requests
import PyPDF2

from app.config import DOCUMENTS_DIR
from app.extensions import pdf_cache, OCR_AVAILABLE, PYMUPDF_AVAILABLE
from app.services.claude import get_anthropic_client, call_claude_with_retry
from app.services.settings import get_model, get_language_instruction


def download_pdf_text(url, use_ocr=False, use_claude_vision=False):
    """Scarica un PDF e ne estrae il testo"""
    cache_key = f"{url}_ocr{use_ocr}_vision{use_claude_vision}"
    if cache_key in pdf_cache:
        return pdf_cache[cache_key]

    # Check locale PRIMA del download
    doc_id_match = re.search(r'EFTA\d+', url)
    doc_id = doc_id_match.group() if doc_id_match else None
    if doc_id and not use_ocr and not use_claude_vision:
        txt_path = os.path.join(DOCUMENTS_DIR, f"{doc_id}.txt")
        if os.path.exists(txt_path):
            with open(txt_path, 'r', encoding='utf-8') as f:
                text = f.read()
            pdf_cache[cache_key] = text
            return text

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
            return "[Errore: il file non è un PDF valido - possibile redirect o protezione]"

        pdf_file = io.BytesIO(content)
        try:
            pdf_reader = PyPDF2.PdfReader(pdf_file)
            text = ""
            for page in pdf_reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"

            if not text.strip():
                if use_claude_vision:
                    text = extract_text_with_claude_vision(content)
                elif use_ocr and OCR_AVAILABLE:
                    text = extract_text_with_tesseract(content)
                else:
                    if OCR_AVAILABLE:
                        text = extract_text_with_tesseract(content)
                        if not text.strip() or text.startswith('['):
                            text = extract_text_with_claude_vision(content)
                    else:
                        text = extract_text_with_claude_vision(content)

            # Salva su disco
            if doc_id and text and not text.startswith('[Errore') and not text.startswith('[OCR'):
                try:
                    pdf_path = os.path.join(DOCUMENTS_DIR, f"{doc_id}.pdf")
                    if not os.path.exists(pdf_path):
                        with open(pdf_path, 'wb') as f:
                            f.write(content)
                    txt_path = os.path.join(DOCUMENTS_DIR, f"{doc_id}.txt")
                    with open(txt_path, 'w', encoding='utf-8') as f:
                        f.write(text)
                except Exception as save_err:
                    print(f"[SAVE DOC] Errore salvataggio {doc_id}: {save_err}")

            # Auto-indicizza in ChromaDB (in background)
            if doc_id and text and not text.startswith('[Errore') and not text.startswith('[OCR'):
                try:
                    from app.agents.vectordb import add_document_to_vectordb
                    title_for_index = doc_id

                    def _index_bg():
                        try:
                            add_document_to_vectordb(url, title_for_index, text, {'doc_id': doc_id})
                            print(f"[AUTO-INDEX] Indicizzato {doc_id}", flush=True)
                        except Exception as idx_err:
                            print(f"[AUTO-INDEX] Errore {doc_id}: {idx_err}", flush=True)
                    threading.Thread(target=_index_bg, daemon=True).start()
                except Exception:
                    pass

            pdf_cache[cache_key] = text
            return text
        except Exception as pdf_err:
            return f"[Errore parsing PDF: {str(pdf_err)}]"

    except requests.exceptions.RequestException as e:
        return f"[Errore download: {str(e)}]"
    except Exception as e:
        return f"[Errore generico: {str(e)}]"


def extract_text_with_tesseract(pdf_content):
    """Estrae testo da PDF usando OCR Tesseract"""
    if not OCR_AVAILABLE:
        return "[OCR non disponibile - installa pytesseract e pdf2image]"
    try:
        from pdf2image import convert_from_bytes
        import pytesseract
        images = convert_from_bytes(pdf_content, dpi=200)
        text = ""
        for i, img in enumerate(images):
            page_text = pytesseract.image_to_string(img, lang='eng')
            text += f"--- Pagina {i+1} ---\n{page_text}\n\n"
        return text if text.strip() else "[OCR completato ma nessun testo trovato]"
    except Exception as e:
        return f"[Errore OCR Tesseract: {str(e)}]"


def extract_text_with_claude_vision(pdf_content, max_pages=5):
    """Estrae testo da PDF usando Claude Vision"""
    try:
        if not OCR_AVAILABLE:
            return "[pdf2image non disponibile - necessario per Claude Vision]"

        from pdf2image import convert_from_bytes
        images = convert_from_bytes(pdf_content, dpi=150)
        images = images[:max_pages]

        image_contents = []
        for i, img in enumerate(images):
            img_buffer = io.BytesIO()
            img.save(img_buffer, format='PNG')
            img_base64 = base64.b64encode(img_buffer.getvalue()).decode('utf-8')
            image_contents.append({
                "type": "image",
                "source": {"type": "base64", "media_type": "image/png", "data": img_base64},
            })
            image_contents.append({"type": "text", "text": f"[Pagina {i+1}]"})

        image_contents.append({
            "type": "text",
            "text": "Trascrivi TUTTO il testo visibile in queste immagini di documenti scansionati. Mantieni la formattazione originale il più possibile. Includi intestazioni, date, firme, note a margine - tutto ciò che è leggibile."
                   + get_language_instruction(),
        })

        client = get_anthropic_client()
        response = call_claude_with_retry(
            client,
            model=get_model(),
            max_tokens=8192,
            messages=[{"role": "user", "content": image_contents}],
        )
        return response.content[0].text
    except Exception as e:
        return f"[Errore Claude Vision: {str(e)}]"


def extract_images_from_pdf(pdf_content):
    """Estrae tutte le immagini incorporate in un PDF usando PyMuPDF"""
    if not PYMUPDF_AVAILABLE:
        return {"error": "PyMuPDF non disponibile. Installa: pip install PyMuPDF", "images": []}

    import fitz
    images = []
    try:
        doc = fitz.open(stream=pdf_content, filetype="pdf")
        for page_num in range(len(doc)):
            page = doc[page_num]
            image_list = page.get_images(full=True)
            for img_index, img_info in enumerate(image_list):
                xref = img_info[0]
                try:
                    base_image = doc.extract_image(xref)
                    image_bytes = base_image["image"]
                    image_ext = base_image["ext"]
                    width = base_image.get("width", 0)
                    height = base_image.get("height", 0)
                    image_b64 = base64.b64encode(image_bytes).decode('utf-8')
                    mime_types = {
                        'png': 'image/png', 'jpeg': 'image/jpeg', 'jpg': 'image/jpeg',
                        'jxr': 'image/jxr', 'jp2': 'image/jp2', 'jpx': 'image/jpx',
                        'jpm': 'image/jpm', 'bmp': 'image/bmp', 'tiff': 'image/tiff',
                    }
                    mime_type = mime_types.get(image_ext.lower(), f'image/{image_ext}')
                    if width >= 50 and height >= 50:
                        images.append({
                            "page": page_num + 1, "index": img_index + 1,
                            "width": width, "height": height, "format": image_ext,
                            "size_bytes": len(image_bytes),
                            "data": f"data:{mime_type};base64,{image_b64}",
                        })
                except Exception:
                    continue
        doc.close()
    except Exception as e:
        return {"error": f"Errore estrazione immagini: {str(e)}", "images": []}

    return {"images": images, "total": len(images)}
