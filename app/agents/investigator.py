"""
InvestigatorAgent — genera dossier su una persona.
"""
import re
from datetime import datetime
from app.agents.vectordb import extract_entities_from_text, get_wikipedia_info


class InvestigatorAgent:
    """Agente che investiga su una persona specifica"""

    def __init__(self, anthropic_client, model="claude-sonnet-4-20250514", lang_instruction=""):
        self.client = anthropic_client
        self.model = model
        self.lang_instruction = lang_instruction

    def investigate(self, name, documents, search_func=None, existing_info=None):
        dossier = {
            "name": name,
            "generated_at": datetime.now().isoformat(),
            "wikipedia": None,
            "documents_found": len(documents),
            "mentions": [],
            "connections": [],
            "timeline": [],
            "financial": [],
            "red_flags": [],
            "ai_analysis": None,
        }

        wiki_info = get_wikipedia_info(name)
        if wiki_info.get("exists"):
            dossier["wikipedia"] = wiki_info

        all_text = ""
        for doc in documents:
            text = doc.get('full_text', '') or doc.get('text', '') or ' '.join(doc.get('snippets', []))
            all_text += text + "\n"
            if name.lower() in text.lower():
                pattern = re.compile(rf'.{{0,150}}{re.escape(name)}.{{0,150}}', re.IGNORECASE)
                matches = pattern.findall(text)
                for match in matches[:5]:
                    dossier["mentions"].append({
                        "document": doc.get('title', 'Unknown'),
                        "url": doc.get('url', ''),
                        "context": match.strip(),
                    })

        entities = extract_entities_from_text(all_text)
        dossier["connections"] = entities.get("people", [])[:20]
        dossier["financial"] = entities.get("money", [])
        dossier["timeline"] = sorted(entities.get("dates", []))

        if self.client and documents:
            dossier["ai_analysis"] = self._generate_ai_analysis(name, documents, wiki_info, existing_info=existing_info)

        return dossier

    def _generate_ai_analysis(self, name, documents, wiki_info=None, existing_info=None):
        context = f"## DOSSIER: {name}\n\n"
        if existing_info:
            context += "### Informazioni già note nel database:\n"
            if existing_info.get('roles'):
                context += f"- Ruoli: {', '.join(existing_info['roles'][:5])}\n"
            if existing_info.get('all_connections'):
                context += f"- Connessioni note: {', '.join(existing_info['all_connections'][:10])}\n"
            if existing_info.get('dossier') and existing_info['dossier'].get('ai_analysis'):
                prev = existing_info['dossier']['ai_analysis']
                context += f"\n### Analisi precedente (da arricchire):\n{prev[:2000]}\n"
            context += "\nARRICCHISCI le informazioni sopra con le nuove scoperte dai documenti.\n\n"

        if wiki_info and wiki_info.get("exists"):
            context += f"### Background (Wikipedia):\n{wiki_info.get('summary', '')}\n\n"

        context += "### Documenti Epstein dove appare:\n\n"
        for i, doc in enumerate(documents[:10], 1):
            context += f"**Documento {i}:** {doc.get('title', 'Unknown')}\n"
            text = doc.get('full_text', '') or doc.get('text', '') or ' '.join(doc.get('snippets', []))
            context += f"{text[:3000]}\n\n---\n\n"

        prompt = f"""{context}

Analizza la relazione tra {name} e Jeffrey Epstein basandoti ESCLUSIVAMENTE sui documenti sopra.

Fornisci:

## 1. NATURA DELLA RELAZIONE
Come conosceva Epstein? Che tipo di rapporto avevano?

## 2. TIMELINE
Quando sono avvenuti i contatti documentati?

## 3. ELEMENTI RILEVANTI
Cosa emerge di significativo dai documenti?

## 4. CONNESSIONI
Altre persone menzionate in relazione a {name}?

## 5. RED FLAGS
Elementi sospetti o che meritano approfondimento?

## 6. CONCLUSIONI
Valutazione sintetica basata sui fatti documentati.

IMPORTANTE: Basa l'analisi SOLO sui documenti forniti. Se non ci sono prove di qualcosa, dillo chiaramente."""

        try:
            message = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt + self.lang_instruction}],
            )
            return message.content[0].text
        except Exception as e:
            return f"Errore nell'analisi: {str(e)}"
