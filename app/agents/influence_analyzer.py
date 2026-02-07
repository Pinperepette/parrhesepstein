"""
Analizzatore di Reti di Influenza su Organizzazioni Internazionali
Mappa come soggetti privati si inseriscono in organizzazioni come WHO, ICRC, World Bank
"""

import re
import json
import requests
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from app.services.justice_gov import search_justice_gov
from app.services.pdf import download_pdf_text

# Organizzazioni target predefinite
TARGET_ORGANIZATIONS = {
    "WHO": {
        "name": "World Health Organization",
        "aliases": ["WHO", "World Health Organization", "OMS", "W.H.O."],
        "key_figures": ["Margaret Chan", "Tedros", "Tedros Adhanom"],
        "type": "international_health"
    },
    "ICRC": {
        "name": "International Committee of the Red Cross",
        "aliases": ["ICRC", "Red Cross", "Croce Rossa", "International Committee of the Red Cross"],
        "key_figures": ["Peter Maurer"],
        "type": "humanitarian"
    },
    "World Bank": {
        "name": "World Bank",
        "aliases": ["World Bank", "Banca Mondiale", "IBRD"],
        "key_figures": ["Jim Yong Kim", "Jim Kim"],
        "type": "financial"
    },
    "Gates Foundation": {
        "name": "Bill & Melinda Gates Foundation",
        "aliases": ["Gates Foundation", "BMGF", "Bill & Melinda Gates", "Bill Gates Foundation"],
        "key_figures": ["Bill Gates", "Melinda Gates", "Boris Nikolic"],
        "type": "private_foundation"
    },
    "IPI": {
        "name": "International Peace Institute",
        "aliases": ["IPI", "International Peace Institute"],
        "key_figures": ["Terje Rød-Larsen", "Terje Rod-Larsen", "Terje", "Andrea Pfanzelter"],
        "type": "bridge_organization"
    },
    "UN": {
        "name": "United Nations",
        "aliases": ["United Nations", "UN", "ONU", "UN Office Geneva"],
        "key_figures": ["Kofi Annan", "Michael Møller", "Michael Moller"],
        "type": "international"
    },
    "GAVI": {
        "name": "GAVI Vaccine Alliance",
        "aliases": ["GAVI", "Global Alliance for Vaccines", "Vaccine Alliance"],
        "key_figures": [],
        "type": "health_alliance"
    }
}

# Persone chiave della rete Epstein (intermediari)
KEY_INTERMEDIARIES = [
    "Jeffrey Epstein",
    "Leon Black",
    "Bill Gates",
    "Boris Nikolic",
    "Terje Rød-Larsen",
    "Terje Rod-Larsen",
    "Larry Summers",
    "Andrea Pfanzelter"
]


class InfluenceNetworkAnalyzer:
    """Analizza le reti di influenza privata su organizzazioni internazionali"""

    def __init__(self, anthropic_client=None, model="claude-sonnet-4-20250514", lang_instruction=""):
        self.client = anthropic_client
        self.model = model
        self.lang_instruction = lang_instruction
        self.search_cache = {}

    def analyze_influence_network(self, target_orgs=None, depth="medium", progress_callback=None):
        """
        Analizza la rete di influenza su organizzazioni specifiche

        Args:
            target_orgs: Lista di chiavi da TARGET_ORGANIZATIONS (default: tutte)
            depth: "small", "medium", "full" - profondità dell'analisi
            progress_callback: Funzione per aggiornamenti di progresso

        Returns:
            Dict con analisi completa
        """
        if target_orgs is None:
            target_orgs = list(TARGET_ORGANIZATIONS.keys())

        depth_config = {
            "small": {"pages": 2, "max_docs": 30},
            "medium": {"pages": 5, "max_docs": 100},
            "full": {"pages": 10, "max_docs": 300}
        }
        config = depth_config.get(depth, depth_config["medium"])

        results = {
            "analysis_date": datetime.now().isoformat(),
            "target_organizations": {},
            "intermediaries": {},
            "connections": [],
            "financial_flows": [],
            "key_documents": [],
            "timeline": [],
            "influence_schema": None,
            "summary": None
        }

        # 1. Cerca documenti per ogni organizzazione target
        all_docs = []
        seen_urls = set()

        for org_key in target_orgs:
            org = TARGET_ORGANIZATIONS.get(org_key)
            if not org:
                continue

            if progress_callback:
                progress_callback(f"Ricerca documenti: {org['name']}...")

            org_results = {
                "name": org["name"],
                "type": org["type"],
                "total_mentions": 0,
                "documents": [],
                "key_figures_found": [],
                "connections_to_epstein": []
            }

            # Cerca per ogni alias
            for alias in org["aliases"]:
                search_term = f'"{alias}"' if " " in alias else alias

                for page in range(config["pages"]):
                    search_results = search_justice_gov(search_term, page)
                    org_results["total_mentions"] = max(org_results["total_mentions"],
                                                        search_results.get("total", 0))

                    for doc in search_results.get("results", []):
                        if doc["url"] not in seen_urls:
                            seen_urls.add(doc["url"])
                            doc["org_match"] = org_key
                            doc["search_term"] = alias
                            # Scarica e salva PDF
                            if doc.get("url"):
                                try:
                                    download_pdf_text(doc["url"])
                                except Exception:
                                    pass
                            org_results["documents"].append(doc)
                            all_docs.append(doc)

            # Cerca figure chiave
            for figure in org.get("key_figures", []):
                figure_results = search_justice_gov(f'"{figure}"', 0)
                if figure_results.get("total", 0) > 0:
                    org_results["key_figures_found"].append({
                        "name": figure,
                        "mentions": figure_results["total"]
                    })

            results["target_organizations"][org_key] = org_results

        # 2. Analizza gli intermediari
        if progress_callback:
            progress_callback("Analisi intermediari...")

        for intermediary in KEY_INTERMEDIARIES:
            search_results = search_justice_gov(f'"{intermediary}"', 0)
            total = search_results.get("total", 0)

            if total > 0:
                results["intermediaries"][intermediary] = {
                    "total_mentions": total,
                    "connected_orgs": []
                }

                # Verifica connessioni con le org target
                for org_key in target_orgs:
                    org = TARGET_ORGANIZATIONS.get(org_key)
                    for alias in org["aliases"][:2]:  # Prime 2 alias
                        combo_results = search_justice_gov(f'"{intermediary}" "{alias}"', 0)
                        if combo_results.get("total", 0) > 0:
                            results["intermediaries"][intermediary]["connected_orgs"].append({
                                "org": org_key,
                                "joint_mentions": combo_results["total"]
                            })
                            results["connections"].append({
                                "from": intermediary,
                                "to": org["name"],
                                "type": "intermediary_connection",
                                "documents": combo_results["total"]
                            })
                            break

        # 3. Cerca pattern finanziari
        if progress_callback:
            progress_callback("Analisi flussi finanziari...")

        financial_terms = [
            "grant agreement",
            "donation",
            "wire transfer",
            "million dollars",
            "funding"
        ]

        for term in financial_terms:
            for org_key in ["Gates Foundation", "IPI"]:
                combo = f'{term} {TARGET_ORGANIZATIONS[org_key]["aliases"][0]}'
                fin_results = search_justice_gov(combo, 0)

                if fin_results.get("total", 0) > 0:
                    for doc in fin_results.get("results", [])[:5]:
                        results["financial_flows"].append({
                            "type": term,
                            "organization": org_key,
                            "document": doc["title"],
                            "url": doc["url"],
                            "snippets": doc.get("snippets", [])[:2]
                        })

        # 4. Cerca documenti chiave specifici
        if progress_callback:
            progress_callback("Ricerca documenti chiave...")

        key_searches = [
            ("co-branding WHO ICRC", "Co-branding con organizzazioni internazionali"),
            ("pandemic preparedness IPI", "Preparazione pandemica"),
            ("polio eradication Gates IPI", "Programma eradicazione polio"),
            ("Geneva conference pandemics", "Conferenza Ginevra pandemie"),
            ("Margaret Chan Peter Maurer", "Vertici WHO e ICRC insieme")
        ]

        for search_term, description in key_searches:
            key_results = search_justice_gov(search_term, 0)
            if key_results.get("total", 0) > 0:
                for doc in key_results.get("results", [])[:3]:
                    results["key_documents"].append({
                        "category": description,
                        "title": doc["title"],
                        "url": doc["url"],
                        "snippets": doc.get("snippets", [])[:2],
                        "search_term": search_term
                    })

        # 5. Genera schema (sempre)
        if progress_callback:
            progress_callback("Generazione schema...")
        results["influence_schema"] = self._generate_influence_schema(results)

        # Debug: log statistiche
        print(f"[INFLUENCE] Statistiche finali:", flush=True)
        print(f"  - Organizzazioni: {len(results['target_organizations'])}", flush=True)
        print(f"  - Intermediari: {len(results['intermediaries'])}", flush=True)
        print(f"  - Connessioni: {len(results['connections'])}", flush=True)
        print(f"  - Documenti chiave: {len(results['key_documents'])}", flush=True)
        print(f"  - Schema livelli: {[len(l.get('entities', [])) for l in results['influence_schema']['levels']]}", flush=True)

        # 6. Genera analisi AI se disponibile
        if self.client:
            if progress_callback:
                progress_callback("Generazione analisi AI...")

            # Recupera contesto storico
            historical_context = ""
            try:
                from app.agents.context_provider import get_full_context
                org_names = " ".join([TARGET_ORGANIZATIONS[k]["name"] for k in target_orgs if k in TARGET_ORGANIZATIONS])
                historical_context = get_full_context(org_names[:200], rag_results=5, mongo_limit=5)
                if historical_context:
                    print(f"[INFLUENCE] Contesto storico recuperato: {len(historical_context)} caratteri", flush=True)
            except Exception as e:
                print(f"[INFLUENCE] Errore recupero contesto: {e}", flush=True)

            print(f"[INFLUENCE] Generazione report AI con Claude...", flush=True)
            results["summary"] = self._generate_summary(results, historical_context=historical_context)
            print(f"[INFLUENCE] Report AI generato: {len(results['summary'] or '')} caratteri", flush=True)
        else:
            print(f"[INFLUENCE] Client Claude non disponibile, skip report AI", flush=True)
            results["summary"] = None

        return results

    def _generate_influence_schema(self, data):
        """Genera uno schema dell'influenza basato sui dati"""

        schema = {
            "levels": [
                {
                    "name": "Finanziatori Privati",
                    "entities": [],
                    "description": "Soggetti privati che forniscono capitali"
                },
                {
                    "name": "Organizzazioni Ponte",
                    "entities": [],
                    "description": "Organizzazioni che fungono da intermediari"
                },
                {
                    "name": "Organizzazioni Target",
                    "entities": [],
                    "description": "Organizzazioni internazionali target dell'influenza"
                }
            ],
            "flows": []
        }

        # Popola TUTTI gli intermediari trovati come finanziatori/intermediari
        financier_names = {"Jeffrey Epstein", "Leon Black", "Bill Gates", "Larry Summers"}
        intermediary_names = {"Boris Nikolic", "Terje Rød-Larsen", "Terje Rod-Larsen", "Andrea Pfanzelter"}

        for name, int_data in data.get("intermediaries", {}).items():
            entity = {
                "name": name,
                "mentions": int_data.get("total_mentions", 0),
                "connected_orgs": [c["org"] for c in int_data.get("connected_orgs", [])]
            }

            # Classifica come finanziatore o intermediario ponte
            if name in financier_names:
                schema["levels"][0]["entities"].append(entity)
            elif name in intermediary_names:
                # Gli intermediari ponte vanno nel secondo livello
                schema["levels"][1]["entities"].append(entity)
            else:
                # Default: metti nei finanziatori
                schema["levels"][0]["entities"].append(entity)

        # Organizzazioni ponte (IPI, Gates Foundation)
        bridge_org_keys = ["IPI", "Gates Foundation"]
        for org_key in bridge_org_keys:
            if org_key in data.get("target_organizations", {}):
                org_data = data["target_organizations"][org_key]
                # Evita duplicati
                existing_names = [e["name"] for e in schema["levels"][1]["entities"]]
                if org_data["name"] not in existing_names:
                    schema["levels"][1]["entities"].append({
                        "name": org_data["name"],
                        "mentions": org_data["total_mentions"],
                        "documents": len(org_data["documents"])
                    })

        # Organizzazioni Target (WHO, ICRC, World Bank, UN, GAVI)
        target_org_keys = ["WHO", "ICRC", "World Bank", "UN", "GAVI"]
        for org_key in target_org_keys:
            if org_key in data.get("target_organizations", {}):
                org_data = data["target_organizations"][org_key]
                schema["levels"][2]["entities"].append({
                    "name": org_data["name"],
                    "mentions": org_data["total_mentions"],
                    "documents": len(org_data.get("documents", [])),
                    "key_figures": org_data.get("key_figures_found", [])
                })

        # Aggiungi flussi basati sulle connessioni trovate
        for conn in data.get("connections", []):
            schema["flows"].append({
                "from": conn["from"],
                "to": conn["to"],
                "strength": conn.get("documents", 1)
            })

        # Se non ci sono entità nel livello 0, aggiungi quelle di default con 0 menzioni
        # per garantire una visualizzazione minima
        if not schema["levels"][0]["entities"]:
            for name in ["Jeffrey Epstein", "Leon Black", "Bill Gates"]:
                if name in data.get("intermediaries", {}):
                    int_data = data["intermediaries"][name]
                    schema["levels"][0]["entities"].append({
                        "name": name,
                        "mentions": int_data.get("total_mentions", 0)
                    })

        return schema

    def _generate_summary(self, data, historical_context=""):
        """Genera un riassunto dell'analisi"""

        if not self.client:
            return None

        # Prepara il contesto
        context = "## DATI ANALISI RETE DI INFLUENZA\n\n"

        # Aggiungi contesto storico se disponibile
        if historical_context:
            context += f"{historical_context}\n\n"

        context += "### Organizzazioni Target:\n"
        for org_key, org_data in data.get("target_organizations", {}).items():
            context += f"- {org_data['name']}: {org_data['total_mentions']} menzioni, "
            context += f"{len(org_data['documents'])} documenti\n"
            if org_data.get("key_figures_found"):
                context += f"  Figure chiave trovate: {', '.join([f['name'] for f in org_data['key_figures_found']])}\n"

        context += "\n### Intermediari:\n"
        for name, int_data in data.get("intermediaries", {}).items():
            context += f"- {name}: {int_data['total_mentions']} menzioni\n"
            if int_data.get("connected_orgs"):
                orgs = [c["org"] for c in int_data["connected_orgs"]]
                context += f"  Connesso a: {', '.join(orgs)}\n"

        context += "\n### Documenti Chiave:\n"
        for doc in data.get("key_documents", [])[:10]:
            context += f"- [{doc['category']}] {doc['title']}\n"
            if doc.get("snippets"):
                snippet = doc["snippets"][0][:200].replace("<em>", "**").replace("</em>", "**")
                context += f"  \"{snippet}...\"\n"

        context += "\n### Flussi Finanziari Identificati:\n"
        for flow in data.get("financial_flows", [])[:10]:
            context += f"- {flow['type']} - {flow['organization']}: {flow['document']}\n"

        prompt = f"""{context}

---

Sei un analista investigativo. Basandoti sui dati sopra, genera un'analisi strutturata su come soggetti privati si stavano inserendo nelle organizzazioni sanitarie internazionali.

## 1. EXECUTIVE SUMMARY
Riassunto in 5 punti chiave di cosa emerge dai dati.

## 2. SCHEMA DI INFILTRAZIONE
Descrivi lo schema a 3 livelli:
- Finanziatori privati
- Organizzazioni ponte (IPI, Gates Foundation)
- Target (WHO, ICRC, etc.)

## 3. MECCANISMI IDENTIFICATI
Come funzionava concretamente l'inserimento? (conferenze, finanziamenti, co-branding, etc.)

## 4. ATTORI CHIAVE
Chi erano le persone che fungevano da ponte?

## 5. TIMELINE E PRECEDENTI
Quando è iniziato questo schema? Ci sono pattern temporali?

## 6. IMPLICAZIONI
Cosa significa questo per la governance sanitaria globale?

## 7. DOCUMENTI DA APPROFONDIRE
Quali documenti meritano analisi più approfondita?

Basa l'analisi SOLO sui dati forniti. Sii preciso e cita i documenti quando possibile."""

        try:
            message = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt + self.lang_instruction}]
            )
            return message.content[0].text
        except Exception as e:
            return f"Errore generazione analisi: {str(e)}"

    def get_document_details(self, url, download_func=None):
        """Ottiene i dettagli completi di un documento"""
        if download_func:
            return download_func(url)
        return None

    def export_to_markdown(self, analysis_data):
        """Esporta l'analisi in formato Markdown"""

        md = f"""# Analisi Rete di Influenza - Documenti Epstein

**Data Analisi:** {analysis_data.get('analysis_date', 'N/A')}

---

## Executive Summary

{analysis_data.get('summary', 'Analisi non disponibile')}

---

## Organizzazioni Analizzate

"""
        for org_key, org_data in analysis_data.get("target_organizations", {}).items():
            md += f"""### {org_data['name']}
- **Menzioni totali:** {org_data['total_mentions']}
- **Documenti trovati:** {len(org_data['documents'])}
- **Figure chiave identificate:** {', '.join([f['name'] for f in org_data.get('key_figures_found', [])]) or 'Nessuna'}

"""

        md += """---

## Intermediari Identificati

| Nome | Menzioni | Connessioni |
|------|----------|-------------|
"""
        for name, int_data in analysis_data.get("intermediaries", {}).items():
            orgs = ', '.join([c["org"] for c in int_data.get("connected_orgs", [])])
            md += f"| {name} | {int_data['total_mentions']} | {orgs} |\n"

        md += """
---

## Documenti Chiave

"""
        for doc in analysis_data.get("key_documents", []):
            md += f"""### {doc['category']}
- **Documento:** {doc['title']}
- **URL:** {doc['url']}
- **Ricerca:** `{doc['search_term']}`

"""
            if doc.get("snippets"):
                snippet = doc["snippets"][0].replace("<em>", "**").replace("</em>", "**")
                md += f"> {snippet[:500]}...\n\n"

        md += """---

## Schema di Influenza

"""
        if analysis_data.get("influence_schema"):
            schema = analysis_data["influence_schema"]
            for level in schema.get("levels", []):
                md += f"""### {level['name']}
*{level['description']}*

"""
                for entity in level.get("entities", []):
                    md += f"- **{entity['name']}**: {entity.get('mentions', 'N/A')} menzioni\n"
                md += "\n"

        md += """---

## Fonti

Tutti i documenti citati sono disponibili su: https://www.justice.gov/epstein
"""

        return md
