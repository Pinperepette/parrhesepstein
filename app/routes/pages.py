"""
Pagine HTML — 20 route, tutte render_template().
"""
from flask import Blueprint, render_template

bp = Blueprint("pages", __name__)


@bp.route('/')
def index():
    return render_template('index.html')



@bp.route('/map')
def map_page():
    return render_template('map.html')


@bp.route('/analysis')
def analysis_page():
    return render_template('analysis.html')


@bp.route('/gallery')
def gallery_page():
    return render_template('gallery.html')


@bp.route('/viewer')
def viewer_page():
    return render_template('viewer.html')


@bp.route('/network')
def network_page():
    return render_template('network.html')


@bp.route('/investigate')
def investigate_page():
    return render_template('investigate.html')



@bp.route('/influence')
def influence_page():
    return render_template('influence.html')


@bp.route('/sintesi')
def sintesi_page():
    return render_template('sintesi.html')


@bp.route('/investigation')
def investigation_page():
    return render_template('investigation.html')


@bp.route('/jmail')
def jmail_page():
    return render_template('jmail.html')


@bp.route('/flights')
def flights_page():
    return render_template('flights.html')


@bp.route('/merge')
def merge_page():
    return render_template('merge.html')


@bp.route('/relationships')
def relationships_page():
    return render_template('relationships.html')


@bp.route('/people')
def people_page():
    return render_template('people.html')


@bp.route('/archive')
def archive_page():
    return render_template('archive.html')


@bp.route('/settings')
def settings_page():
    return render_template('settings.html')
