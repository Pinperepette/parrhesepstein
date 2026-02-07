"""
/api/status e /api/dashboard/stats
"""
from flask import Blueprint, jsonify
from datetime import datetime
from app.services.claude import get_claude_api_key
from app.services.documents import count_local_txt
from app.extensions import (
    crew_investigations_collection, people_collection,
    searches_collection,
)

bp = Blueprint("status", __name__)


@bp.route('/api/status')
def api_status():
    api_key = get_claude_api_key()
    return jsonify({"ai_configured": api_key is not None, "mongodb_connected": True})


@bp.route('/api/dashboard/stats', methods=['GET'])
def api_dashboard_stats():
    try:
        investigations_count = crew_investigations_collection.count_documents({})
        people_count = people_collection.count_documents({})
        searches_count = searches_collection.count_documents({})
        local_docs = count_local_txt()

        from app.agents.vectordb import get_collection_stats
        vectordb_stats = get_collection_stats()

        connections_count = 0
        try:
            pipeline = [
                {'$project': {'conn_count': {'$size': {'$ifNull': ['$all_connections', []]}}}},
                {'$group': {'_id': None, 'total': {'$sum': '$conn_count'}}},
            ]
            result = list(people_collection.aggregate(pipeline))
            connections_count = result[0]['total'] if result else 0
        except Exception:
            pass

        recent_investigations = []
        try:
            recent = list(crew_investigations_collection.find(
                {}, {'objective': 1, 'date': 1, 'documents_found': 1}
            ).sort('date', -1).limit(5))
            for inv in recent:
                inv['_id'] = str(inv['_id'])
                if isinstance(inv.get('date'), datetime):
                    inv['date'] = inv['date'].isoformat()
                recent_investigations.append(inv)
        except Exception:
            pass

        recent_people = []
        try:
            recent_p = list(people_collection.find(
                {}, {'name': 1, 'relevance': 1, 'roles': 1, 'last_updated': 1}
            ).sort('last_updated', -1).limit(5))
            for p in recent_p:
                p['_id'] = str(p['_id'])
                if isinstance(p.get('last_updated'), datetime):
                    p['last_updated'] = p['last_updated'].isoformat()
                recent_people.append(p)
        except Exception:
            pass

        return jsonify({
            'investigations_count': investigations_count,
            'people_count': people_count,
            'documents_indexed': vectordb_stats.get('total_documents', 0),
            'documents_local': local_docs,
            'chunks_indexed': vectordb_stats.get('total_chunks', 0),
            'connections_count': connections_count,
            'searches_count': searches_count,
            'recent_investigations': recent_investigations,
            'recent_people': recent_people,
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500
