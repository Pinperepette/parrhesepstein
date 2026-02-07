"""
Estrazione entità e keyword dal testo.
"""
import re
from collections import Counter


def extract_entities(text):
    """Estrae entità dal testo (date, email, telefoni, termini top)"""
    date_pattern = (
        r'\b(?:January|February|March|April|May|June|July|August|September|October|November|December)'
        r'\s+\d{1,2},?\s+\d{4}\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b'
    )
    dates = re.findall(date_pattern, text, re.IGNORECASE)

    email_pattern = r'[\w\.-]+@[\w\.-]+\.\w+'
    emails = re.findall(email_pattern, text)

    phone_pattern = r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b'
    phones = re.findall(phone_pattern, text)

    stop_words = {
        'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of',
        'with', 'by', 'from', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
        'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could', 'should',
        'may', 'might', 'must', 'shall', 'can', 'this', 'that', 'these', 'those',
        'i', 'you', 'he', 'she', 'it', 'we', 'they', 'what', 'which', 'who', 'whom',
        'whose', 'where', 'when', 'why', 'how', 'all', 'each', 'every', 'both', 'few',
        'more', 'most', 'other', 'some', 'such', 'no', 'nor', 'not', 'only', 'own',
        'same', 'so', 'than', 'too', 'very', 'just', 'as', 'if', 'then', 'because',
        'while', 'although', 'though', 'after', 'before', 'since', 'until', 'unless',
        'about', 'into', 'through', 'during', 'above', 'below', 'between', 'under',
        'again', 'further', 'once', 'here', 'there', 'any', 'also',
    }
    words = re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', text)
    word_freq = Counter(w for w in words if w.lower() not in stop_words and len(w) > 2)

    return {
        "dates": list(set(dates))[:20],
        "emails": list(set(emails))[:20],
        "phones": list(set(phones))[:10],
        "top_terms": word_freq.most_common(30),
    }


def extract_search_keywords(question):
    """Estrae parole chiave dalla domanda per la ricerca"""
    stop_words = {
        'chi', 'cosa', 'come', 'quando', 'dove', 'perché', 'quale', 'quali',
        'era', 'erano', 'sono', 'stato', 'stati', 'aveva', 'avevano',
        'con', 'per', 'tra', 'fra', 'nel', 'nella', 'nei', 'nelle', 'sul', 'sulla',
        'il', 'lo', 'la', 'i', 'gli', 'le', 'un', 'uno', 'una',
        'di', 'da', 'in', 'su', 'a', 'e', 'o', 'ma', 'se', 'che',
        'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
        'what', 'who', 'where', 'when', 'why', 'how', 'which',
        'is', 'are', 'was', 'were', 'have', 'had', 'has',
        'connections', 'connessioni', 'relazioni', 'relations',
        'documenti', 'documents', 'trova', 'find', 'cerca', 'search',
        'epstein', 'jeffrey',
    }

    words = re.findall(r'\b[A-Za-z]{3,}\b', question)
    keywords = [w for w in words if w.lower() not in stop_words]

    name_pattern = r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b'
    names = re.findall(name_pattern, question)

    result = names + [k for k in keywords if k not in ' '.join(names)]

    if not result:
        result = sorted(words, key=len, reverse=True)[:3]

    return result[:5]


def generate_search_variants(question, keywords):
    """Genera varianti di ricerca più aggressive"""
    variants = []

    name_pattern = r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b'
    names = re.findall(name_pattern, question)
    for name in names:
        variants.append(name)
        parts = name.split()
        if len(parts) >= 2:
            variants.append(parts[-1])

    for kw in keywords:
        if kw not in variants:
            variants.append(kw)

    if len(keywords) >= 2:
        variants.append(f"{keywords[0]} {keywords[1]}")

    doc_terms = ['email', 'schedule', 'calendar', 'flight', 'meeting', 'dinner', 'memo']
    for term in doc_terms:
        if term.lower() in question.lower():
            for name in names[:1]:
                variants.append(f"{name} {term}")

    relation_words = ['relazione', 'connessione', 'incontro', 'meeting', 'connection', 'relationship']
    if any(w in question.lower() for w in relation_words):
        for name in names[:1]:
            variants.append(f"Jeffrey {name}")

    seen = set()
    unique = []
    for v in variants:
        if v.lower() not in seen:
            seen.add(v.lower())
            unique.append(v)

    return unique
