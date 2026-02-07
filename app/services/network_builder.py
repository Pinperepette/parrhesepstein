"""
Costruisce dati network (nodi + edge) da risultati investigazione.
"""


def build_investigation_network(analysis, banking=None):
    """Costruisce i dati del network dalle connessioni trovate"""
    nodes = []
    edges = []
    node_ids = set()

    for person in analysis.get('key_people', []):
        name = person.get('name', '')
        if name and name not in node_ids:
            node_ids.add(name)
            relevance = person.get('relevance', 'media')
            color = '#ff4757' if relevance == 'alta' else '#ffa502' if relevance == 'media' else '#2ed573'
            nodes.append({
                'id': name, 'label': name,
                'title': person.get('role', ''),
                'color': color,
                'size': 30 if relevance == 'alta' else 20,
            })

    for conn in analysis.get('connections', []):
        from_node = conn.get('from', '')
        to_node = conn.get('to', '')
        if from_node and from_node not in node_ids:
            node_ids.add(from_node)
            nodes.append({'id': from_node, 'label': from_node, 'color': '#888', 'size': 15})
        if to_node and to_node not in node_ids:
            node_ids.add(to_node)
            nodes.append({'id': to_node, 'label': to_node, 'color': '#888', 'size': 15})
        if from_node and to_node:
            edges.append({
                'from': from_node, 'to': to_node,
                'label': conn.get('type', ''),
                'title': conn.get('evidence', ''),
            })

    for location in analysis.get('locations', []):
        if location and location not in node_ids:
            node_ids.add(location)
            nodes.append({
                'id': location, 'label': location,
                'color': '#00d4ff', 'shape': 'diamond', 'size': 15,
            })

    if banking and isinstance(banking, dict):
        for bank in banking.get('banks', []):
            bank_name = bank.get('name', '')
            if bank_name and bank_name not in node_ids:
                node_ids.add(bank_name)
                nodes.append({
                    'id': bank_name, 'label': bank_name,
                    'title': bank.get('role', ''),
                    'color': '#2ed573', 'shape': 'diamond', 'size': 20,
                })
            for person_name in bank.get('key_people', []):
                if person_name and person_name not in node_ids:
                    node_ids.add(person_name)
                    nodes.append({'id': person_name, 'label': person_name, 'color': '#888', 'size': 15})
                if bank_name and person_name:
                    edges.append({
                        'from': person_name, 'to': bank_name,
                        'label': 'banca',
                        'title': bank.get('evidence', ''),
                        'color': {'color': '#2ed573'},
                    })

        for tx in banking.get('transactions', []):
            from_entity = tx.get('from_entity', '')
            to_entity = tx.get('to_entity', '')
            if from_entity and from_entity not in node_ids:
                node_ids.add(from_entity)
                nodes.append({'id': from_entity, 'label': from_entity, 'color': '#888', 'size': 15})
            if to_entity and to_entity not in node_ids:
                node_ids.add(to_entity)
                nodes.append({'id': to_entity, 'label': to_entity, 'color': '#888', 'size': 15})
            if from_entity and to_entity:
                is_suspicious = tx.get('suspicious', False)
                edges.append({
                    'from': from_entity, 'to': to_entity,
                    'label': tx.get('amount', ''),
                    'title': tx.get('reason', '') if is_suspicious else tx.get('type', ''),
                    'color': {'color': '#ff4757' if is_suspicious else '#2ed573'},
                })

    return {'nodes': nodes, 'edges': edges}
