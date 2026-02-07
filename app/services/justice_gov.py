"""
Ricerca nel database Epstein su justice.gov — unica copia.
"""
import re
import requests


def search_justice_gov(query, page=0, size=20):
    """Cerca nel database Epstein su justice.gov"""
    url = "https://www.justice.gov/multimedia-search"
    params = {"keys": query, "page": page}
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:146.0) Gecko/20100101 Firefox/146.0",
        "Accept": "*/*",
        "Accept-Language": "it-IT,it;q=0.8,en-US;q=0.5,en;q=0.3",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://www.justice.gov/epstein",
        "x-queueit-ajaxpageurl": "https%3A%2F%2Fwww.justice.gov%2Fepstein",
        "Alt-Used": "www.justice.gov",
        "Connection": "keep-alive",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
    }
    try:
        response = requests.get(url, params=params, headers=headers, timeout=30)
        response.raise_for_status()
        return parse_json_results(response.json(), query)
    except Exception as e:
        return {"error": str(e), "results": []}


def parse_json_results(data, query):
    """Estrae i risultati dal JSON"""
    results = []
    hits = data.get("hits", {})
    total = hits.get("total", {}).get("value", 0)

    for item in hits.get("hits", []):
        source = item.get("_source", {})
        highlight = item.get("highlight", {})

        result = {
            "id": source.get("documentId", ""),
            "title": source.get("ORIGIN_FILE_NAME", "Documento"),
            "url": source.get("ORIGIN_FILE_URI", ""),
            "file_size": source.get("fileSize", 0),
            "total_words": source.get("totalWords", 0),
            "total_chars": source.get("totalCharacters", 0),
            "content_type": source.get("contentType", ""),
            "processed_at": source.get("processedAt", ""),
            "start_page": source.get("startPage", 1),
            "end_page": source.get("endPage", 1),
            "dataset": extract_dataset(source.get("key", "")),
        }

        snippets = highlight.get("content", [])
        if snippets:
            clean_snippets = [s.replace("<em>", "**").replace("</em>", "**") for s in snippets]
            result["snippets"] = clean_snippets
            result["description"] = " ... ".join(clean_snippets)[:500]

        results.append(result)

    return {"query": query, "total": total, "count": len(results), "results": results}


def extract_dataset(key):
    """Estrae il nome del dataset dal path"""
    match = re.search(r'DataSet\s*(\d+)', key)
    return f"Dataset {match.group(1)}" if match else "Unknown"
