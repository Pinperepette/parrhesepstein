"""
Registra tutti i Blueprint Flask.
"""


def register_blueprints(app):
    from app.routes.pages import bp as pages_bp
    from app.routes.status import bp as status_bp
    from app.routes.flights import bp as flights_bp
    from app.routes.settings_routes import bp as settings_bp
    from app.routes.people import bp as people_bp
    from app.routes.documents import bp as documents_bp
    from app.routes.search import bp as search_bp
    from app.routes.ocr import bp as ocr_bp
    from app.routes.indexing import bp as indexing_bp
    from app.routes.relationships import bp as relationships_bp
    from app.routes.analyze import bp as analyze_bp
    from app.routes.investigate import bp as investigate_bp
    from app.routes.network import bp as network_bp
    from app.routes.influence import bp as influence_bp
    from app.routes.synthesis import bp as synthesis_bp
    from app.routes.merge import bp as merge_bp
    from app.routes.investigation_crew import bp as crew_bp

    for blueprint in [
        pages_bp, status_bp, flights_bp, settings_bp, people_bp,
        documents_bp, search_bp, ocr_bp, indexing_bp, relationships_bp,
        analyze_bp, investigate_bp, network_bp,
        influence_bp, synthesis_bp, merge_bp, crew_bp,
    ]:
        app.register_blueprint(blueprint)
