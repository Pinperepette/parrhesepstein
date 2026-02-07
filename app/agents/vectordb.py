"""
ChromaDB: add, search, delete, stats — unica copia.
"""
import os
import re
import hashlib
from datetime import datetime
from collections import defaultdict

import chromadb
from chromadb.config import Settings
import networkx as nx

try:
    import wikipediaapi
    wiki = wikipediaapi.Wikipedia(user_agent='EpsteinFilesAnalyzer/1.0', language='en')
except ImportError:
    wiki = None

from app.config import CHROMA_PATH

# ChromaDB setup
chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)


def get_or_create_collection():
    """Ottiene o crea la collection ChromaDB"""
    return chroma_client.get_or_create_collection(
        name="epstein_docs",
        metadata={"description": "Documenti Epstein Files"},
    )


def generate_doc_id(url, chunk_idx=0):
    return hashlib.md5(f"{url}_{chunk_idx}".encode()).hexdigest()


def chunk_text(text, chunk_size=1000, overlap=200):
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start = end - overlap
    return chunks


def add_document_to_vectordb(url, title, text, metadata=None):
    """Aggiunge un documento al database vettoriale"""
    collection = get_or_create_collection()
    chunks = chunk_text(text)
    for i, chunk in enumerate(chunks):
        doc_id = generate_doc_id(url, i)
        existing = collection.get(ids=[doc_id])
        if existing and existing['ids']:
            continue
        meta = {
            "url": url,
            "title": title,
            "chunk_index": i,
            "total_chunks": len(chunks),
            "indexed_at": datetime.now().isoformat(),
        }
        if metadata:
            meta.update(metadata)
        collection.add(ids=[doc_id], documents=[chunk], metadatas=[meta])
    return len(chunks)


def get_collection_stats():
    try:
        collection = get_or_create_collection()
        count = collection.count()
        all_meta = collection.get(include=["metadatas"])
        unique_docs = set()
        for meta in all_meta.get('metadatas', []):
            if meta and meta.get('url'):
                unique_docs.add(meta['url'])
            elif meta and meta.get('doc_id'):
                unique_docs.add(meta['doc_id'])
        return {"total_chunks": count, "total_documents": len(unique_docs)}
    except Exception as e:
        return {"total_chunks": 0, "total_documents": 0, "error": str(e)}


def is_document_indexed(doc_id):
    try:
        collection = get_or_create_collection()
        results = collection.get(where={"doc_id": doc_id}, include=["metadatas"])
        chunks = len(results.get('ids', []))
        return {"indexed": chunks > 0, "chunks": chunks}
    except Exception:
        try:
            collection = get_or_create_collection()
            results = collection.get(include=["metadatas"])
            chunks = 0
            for meta in results.get('metadatas', []):
                if meta and (meta.get('doc_id') == doc_id or doc_id in meta.get('url', '')):
                    chunks += 1
            return {"indexed": chunks > 0, "chunks": chunks}
        except Exception:
            return {"indexed": False, "chunks": 0}


def delete_from_vectordb(url_pattern):
    try:
        collection = get_or_create_collection()
        all_data = collection.get(include=["metadatas"])
        ids_to_delete = []
        for i, meta in enumerate(all_data.get('metadatas', [])):
            if meta and url_pattern in meta.get('url', ''):
                ids_to_delete.append(all_data['ids'][i])
        if ids_to_delete:
            collection.delete(ids=ids_to_delete)
            print(f"[VECTORDB] Eliminati {len(ids_to_delete)} chunk per pattern '{url_pattern}'", flush=True)
            return {"deleted": len(ids_to_delete)}
        return {"deleted": 0}
    except Exception as e:
        print(f"[VECTORDB] Errore eliminazione: {e}", flush=True)
        return {"deleted": 0, "error": str(e)}


def semantic_search(query, n_results=20):
    """Ricerca semantica nei documenti"""
    collection = get_or_create_collection()
    results = collection.query(
        query_texts=[query], n_results=n_results,
        include=["documents", "metadatas", "distances"],
    )
    formatted = []
    seen_urls = set()
    for i, doc in enumerate(results['documents'][0]):
        meta = results['metadatas'][0][i]
        distance = results['distances'][0][i] if results['distances'] else 0
        if meta['url'] in seen_urls:
            continue
        seen_urls.add(meta['url'])
        formatted.append({
            "text": doc,
            "title": meta.get('title', 'Unknown'),
            "url": meta.get('url', ''),
            "relevance": 1 - distance,
            "metadata": meta,
        })
    return formatted


# ── Funzioni di supporto per InvestigatorAgent e NetworkAgent ──

def extract_entities_from_text(text):
    """Estrae entità (nomi, email, date, denaro) dal testo"""
    entities = {
        "people": set(), "organizations": set(), "locations": set(),
        "emails": set(), "dates": set(), "money": set(),
    }
    # Split into segments at sentence/line boundaries to avoid cross-sentence merges
    segments = re.split(r'[.!?\n\r]+', text)
    names = []
    for segment in segments:
        clean_seg = re.sub(r'\s+', ' ', segment).strip()
        if not clean_seg:
            continue
        # Find consecutive capitalized words within this segment
        cap_sequences = re.findall(r'(?:[A-Z][a-z]+[,;:\-]*(?:\s+|$)){2,}', clean_seg)
        for seq in cap_sequences:
            words = [w.rstrip(',;:-') for w in seq.strip().split()]
            words = [w for w in words if w]
            for i in range(len(words)):
                if i + 1 < len(words):
                    names.append(f"{words[i]} {words[i+1]}")
                if i + 2 < len(words):
                    names.append(f"{words[i]} {words[i+1]} {words[i+2]}")
    stop_names = {
        'The New', 'New York', 'United States', 'Dear Sir', 'Best Regards',
        'Kind Regards', 'Thank You', 'Please Note', 'For Example', 'Prime Minister',
        'Dear Jeffrey', 'Hey Jeffrey', 'The Daily', 'Daily Beast', 'New York Times',
        'Wall Street', 'White House', 'United Kingdom', 'Los Angeles', 'San Francisco',
        'The Guardian', 'Washington Post', 'Fox News', 'Dear Friend', 'Best Wishes',
        'Happy Birthday', 'Merry Christmas', 'Happy New', 'Good Morning', 'Good Evening',
        'Dear Mr', 'Dear Mrs', 'Dear Ms', 'The Honorable', 'His Excellency', 'Her Majesty',
        'Democratic Party', 'Republican Party', 'Labour Party', 'Conservative Party',
        'Supreme Court', 'District Court', 'High Court', 'Federal Court',
        'January February', 'March April', 'October November', 'November December',
        'Original Message', 'Sent Items', 'Read Receipt', 'Delivery Status',
        'Auto Reply', 'Out Office', 'High Importance', 'Low Importance',
    }
    # Words that should never be part of a person's name
    bad_words = {
        # Email header terms
        'sent', 'subject', 'from', 'to', 'date', 'reply', 'forward', 'forwarded',
        'attachment', 'attached', 'received', 'importance', 'message', 'original',
        'inbox', 'draft', 'drafts', 'deleted', 'archive', 'spam', 'junk',
        'cc', 'bcc', 'mailto', 'regarding', 're',
        # Document/legal terms often capitalized
        'exhibit', 'page', 'paragraph', 'section', 'document', 'filed',
        'redacted', 'sealed', 'confidential', 'privileged', 'produced',
        'bates', 'stamped', 'marked', 'noted', 'stated', 'continued',
        # Transport/misc terms
        'flight', 'airport', 'reposition', 'passengers', 'departed',
        'arrived', 'scheduled', 'cancelled', 'delayed',
        # Location/organization suffixes mistaken for names
        'beach', 'island', 'islands', 'city', 'county', 'state', 'park',
        'avenue', 'boulevard', 'drive', 'road', 'lane', 'place',
        'foundation', 'institute', 'university', 'college', 'school',
        'corporation', 'company', 'group', 'associates', 'partners',
        'management', 'capital', 'global', 'international', 'holdings',
        'tower', 'building', 'center', 'centre', 'plaza', 'hotel',
        'asset', 'assets', 'fund', 'funds', 'trust', 'services',
        'girl', 'boy', 'man', 'woman', 'child', 'children',
        # Common false positive verbs/words when capitalized
        'having', 'being', 'doing', 'going', 'coming', 'making',
        'taking', 'getting', 'putting', 'setting', 'running',
        'called', 'wrote', 'said', 'told', 'asked', 'sent',
        'monday', 'tuesday', 'wednesday', 'thursday', 'friday',
        'saturday', 'sunday',
        'january', 'february', 'march', 'april', 'may', 'june',
        'july', 'august', 'september', 'october', 'november', 'december',
    }
    bad_patterns = [
        r'^The\s+', r'^Dear\s+', r'^Hey\s+', r'^Mr\s+', r'^Mrs\s+', r'^Ms\s+', r'^Dr\s+',
        r'Party$', r'Court$', r'Street$', r'Times$', r'Post$', r'News$',
        r'Minister$', r'President$', r'Having\s+', r'With\s+', r'From\s+',
        r'About\s+', r'After\s+', r'Before\s+',
        r'\s+But\s+', r'\s+And\s+', r'\s+Or\s+',
        r'\s+Will\s+', r'\s+Would\s+', r'\s+Could\s+', r'\s+Should\s+',
    ]
    for name in names:
        if len(name) < 8 or len(name) > 35:
            continue
        if len(name.split()) > 3:
            continue
        if name in stop_names:
            continue
        # Check if any word in the name is a known bad word
        name_words = name.lower().split()
        if any(w in bad_words for w in name_words):
            continue
        skip = False
        for pattern in bad_patterns:
            if re.search(pattern, name, re.IGNORECASE):
                skip = True
                break
        if skip:
            continue
        entities["people"].add(name)

    # When a 3-word name exists, remove its 2-word subsets (they're partial matches)
    three_word_names = [n for n in entities["people"] if len(n.split()) == 3]
    partial_to_remove = set()
    for name3 in three_word_names:
        parts = name3.split()
        partial_to_remove.add(f"{parts[0]} {parts[1]}")
        partial_to_remove.add(f"{parts[1]} {parts[2]}")
    entities["people"] -= partial_to_remove

    entities["emails"] = set(re.findall(r'[\w\.-]+@[\w\.-]+\.\w+', text))

    date_patterns = [
        r'\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}\b',
        r'\b\d{1,2}/\d{1,2}/\d{2,4}\b',
        r'\b\d{4}-\d{2}-\d{2}\b',
    ]
    for pattern in date_patterns:
        entities["dates"].update(re.findall(pattern, text, re.IGNORECASE))

    money_pattern = r'[\$€£]\s*[\d,]+(?:\.\d{2})?(?:\s*(?:million|billion|thousand|k|m|b))?|\d+(?:,\d{3})*(?:\.\d{2})?\s*(?:dollars|euros|pounds|USD|EUR|GBP)'
    entities["money"] = set(re.findall(money_pattern, text, re.IGNORECASE))

    return {k: list(v) for k, v in entities.items()}


def get_wikipedia_info(name):
    if not wiki:
        return {"exists": False, "name": name}
    try:
        page = wiki.page(name)
        if not page.exists():
            for variant in [name, name.replace(" ", "_"), f"{name} (businessman)", f"{name} (financier)", f"{name} (politician)"]:
                page = wiki.page(variant)
                if page.exists():
                    break
        if page.exists():
            return {"title": page.title, "summary": page.summary[:1000] if page.summary else "", "url": page.fullurl, "exists": True}
    except Exception:
        pass
    return {"exists": False, "name": name}


def build_network_graph(documents):
    """Costruisce un grafo delle relazioni tra entità"""
    G = nx.Graph()
    all_entities = defaultdict(lambda: {"docs": [], "count": 0})
    doc_entities = []
    for doc in documents:
        text = doc.get('full_text', '') or doc.get('text', '') or ' '.join(doc.get('snippets', []))
        entities = extract_entities_from_text(text)
        doc_entities.append({"doc": doc, "entities": entities})
        for person in entities.get('people', []):
            all_entities[person]["count"] += 1
            all_entities[person]["docs"].append(doc.get('title', 'Unknown'))

    top_people = sorted(all_entities.items(), key=lambda x: x[1]["count"], reverse=True)[:50]
    for person, data in top_people:
        G.add_node(person, type="person", count=data["count"], docs=data["docs"][:5])

    for doc_data in doc_entities:
        people = doc_data["entities"].get("people", [])
        for i, p1 in enumerate(people):
            if p1 not in G:
                continue
            for p2 in people[i + 1:]:
                if p2 not in G:
                    continue
                if G.has_edge(p1, p2):
                    G[p1][p2]["weight"] += 1
                else:
                    G.add_edge(p1, p2, weight=1)
    return G


def graph_to_vis_format(G):
    nodes, edges = [], []
    degrees = dict(G.degree())
    max_degree = max(degrees.values()) if degrees else 1
    for node in G.nodes():
        data = G.nodes[node]
        size = 10 + (degrees[node] / max_degree) * 40
        nodes.append({
            "id": node, "label": node, "size": size,
            "title": f"{node}\nMenzioni: {data.get('count', 0)}\nDocumenti: {', '.join(data.get('docs', [])[:3])}",
            "color": {"background": "#00d4ff" if data.get('count', 0) > 5 else "#1a1a3a", "border": "#00d4ff"},
        })
    for u, v, data in G.edges(data=True):
        edges.append({"from": u, "to": v, "value": data.get("weight", 1), "title": f"Co-occorrenze: {data.get('weight', 1)}"})
    return {"nodes": nodes, "edges": edges}
