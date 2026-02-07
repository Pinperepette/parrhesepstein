"""
NetworkAgent — mappa connessioni tra persone.
"""
import networkx as nx
from app.agents.vectordb import build_network_graph, graph_to_vis_format


class NetworkAgent:
    """Agente che mappa le connessioni tra persone"""

    def __init__(self, anthropic_client=None):
        self.client = anthropic_client

    def map_network(self, documents):
        G = build_network_graph(documents)
        vis_data = graph_to_vis_format(G)

        stats = {
            "total_nodes": G.number_of_nodes(),
            "total_edges": G.number_of_edges(),
            "most_connected": [],
            "clusters": [],
        }

        degrees = sorted(G.degree(), key=lambda x: x[1], reverse=True)[:10]
        stats["most_connected"] = [{"name": n, "connections": d} for n, d in degrees]

        if G.number_of_nodes() > 0:
            components = list(nx.connected_components(G))
            stats["clusters"] = [list(c)[:10] for c in sorted(components, key=len, reverse=True)[:5]]

        return {"graph": vis_data, "stats": stats}
