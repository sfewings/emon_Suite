"""
Event page (FR-27): the post for the current sail, edited from a phone or the
racing app's iPad, at /log on this service.

Reached through nginx at /race/log/, inside the racing app's Home Screen
scope, so it opens in the same full-screen window as GAR, Map and Race
(racing DESIGN 9.13). Everything it uses lives under /log as well: the page,
its API, the preview and the files the preview shows. The page addresses all
of them relatively, so it works the same at /race/log/, /events/log/ and on
this service's own port, with nothing outside log/ but its back link.
"""

import logging
from pathlib import Path

from flask import Blueprint, jsonify, request, send_from_directory

from .recording_service import RecordingError

logger = logging.getLogger(__name__)

PAGE_DIR = Path(__file__).parent / 'web_ui' / 'log'


def create_event_page(web) -> Blueprint:
    """
    The /log blueprint, for a WebInterface: it uses that interface's
    recording service and file directories.
    """
    page = Blueprint('event_page', __name__, url_prefix='/log')
    service = web.recordings

    def refused(e: RecordingError):
        return jsonify({'success': False, 'error': str(e)}), e.status

    def failed(what: str, e: Exception):
        logger.error(f"Event page {what} error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

    # === The page ===

    @page.route('/')
    def index():
        return send_from_directory(PAGE_DIR, 'index.html')

    @page.route('/assets/<path:filename>')
    def assets(filename):
        return send_from_directory(PAGE_DIR, filename)

    # === Its API ===

    @page.route('/api/state')
    def state():
        """The recording, its draft and everything else the page shows.
        ?id= for a particular recording; without it, FR-28 chooses."""
        try:
            recording_id = request.args.get('id', type=int)
            return jsonify({'success': True,
                            **service.page_state(recording_id, web._file_url)})
        except RecordingError as e:
            return refused(e)
        except Exception as e:
            return failed('state', e)

    @page.route('/api/draft/<int:recording_id>', methods=['PUT'])
    def save(recording_id):
        """Body: {"changes": {field: value}}. Per field, the later save stands."""
        try:
            data = request.get_json(silent=True) or {}
            if not isinstance(data.get('changes'), dict):
                return jsonify({'success': False, 'error': 'Body needs a "changes" object'}), 400
            draft = service.save_draft_fields(recording_id, data['changes'])
            return jsonify({'success': True, 'draft': draft})
        except RecordingError as e:
            return refused(e)
        except Exception as e:
            return failed('save', e)

    @page.route('/api/publish/<int:recording_id>', methods=['POST'])
    def publish(recording_id):
        """Start publishing; {"draft": true} sends it as a WordPress draft."""
        try:
            data = request.get_json(silent=True) or {}
            options = {'auto_publish': False} if data.get('draft') else {}
            return jsonify({'success': True,
                            'job': service.start_publish(recording_id, **options)}), 202
        except RecordingError as e:
            return refused(e)
        except Exception as e:
            return failed('publish', e)

    # === The preview, and the files it shows ===

    @page.route('/preview')
    def preview():
        # Same page as /preview, served here so its relative image URLs
        # resolve under log/ too
        return web.app.view_functions['preview_post']()

    @page.route('/plots/<int:recording_id>/<path:filename>')
    def plots(recording_id, filename):
        return send_from_directory(web.plots_dir / str(recording_id), filename)

    @page.route('/uploads/<int:recording_id>/<path:filename>')
    def uploads(recording_id, filename):
        return send_from_directory(web.uploads_dir / str(recording_id), filename)

    @page.route('/exports/<int:recording_id>/<path:filename>')
    def exports(recording_id, filename):
        return send_from_directory(web.plots_dir / str(recording_id), filename,
                                   as_attachment=True)

    return page
