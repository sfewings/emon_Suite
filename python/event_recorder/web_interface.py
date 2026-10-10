"""
Flask REST API for event recorder web interface.

Provides endpoints for managing recordings, configurations, and service status.
Follows pattern from emon_settings_web.py.
"""

import json
import os
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional
from flask import Flask, redirect, render_template, request, jsonify, send_from_directory, send_file
from werkzeug.exceptions import BadRequest
from werkzeug.utils import secure_filename

from .models import Database, ImageType, PostState, RecordingStatus
from .event_page import create_event_page
from .recording_service import RecordingError, RecordingService
from .wordpress_publisher import WordPressPublisher

logger = logging.getLogger(__name__)


def _preview_page(recording_id: int, title: str, content: str, layout: Optional[str]) -> str:
    """
    The rendered post in a page of its own. Plain styling close to a
    WordPress single post, not the red-shadow theme itself, which FR-24
    leaves for the event page. The more-break, a comment the reader never
    sees, is drawn as a line, because what sits above it is all the
    enchantee.org home page shows.
    """
    import html as html_lib
    shown = content.replace(
        '<!--more-->',
        '<div class="more-break">home page shows only what is above this line</div>')
    choices = []
    for value, label in ((None, 'Draft'), ('track_log', 'Track Log'), ('ship_log', "Ship's Log")):
        href = f"preview?id={recording_id}" + (f"&layout={value}" if value else '')
        cls = ' class="here"' if value == layout else ''
        choices.append(f'<a{cls} href="{href}">{label}</a>')
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Preview: {html_lib.escape(title)}</title>
<style>
body {{ margin: 0; background: #f4f1ec; color: #222;
       font: 17px/1.6 Georgia, "Times New Roman", serif; }}
.bar {{ background: #7a1a1a; color: #fff; padding: 10px 16px;
       font: 15px/1.4 -apple-system, "Segoe UI", sans-serif; }}
.bar a {{ color: #fff; margin-right: 14px; }}
.bar a.here {{ font-weight: bold; text-decoration: none; }}
article {{ max-width: 760px; margin: 0 auto; padding: 16px; background: #fff; }}
h1 {{ font-size: 1.7em; line-height: 1.25; }}
figure {{ margin: 1em 0; }}
img {{ max-width: 100%; height: auto; }}
figcaption {{ font-size: 0.85em; color: #555; text-align: center; }}
.more-break {{ border-top: 2px dashed #7a1a1a; color: #7a1a1a; margin: 2em 0;
              font: 13px sans-serif; text-transform: uppercase; }}
</style></head>
<body>
<div class="bar">Preview &middot; {' '.join(choices)}</div>
<article><h1>{html_lib.escape(title)}</h1>
{shown}
</article>
</body></html>"""


class WebInterface:
    """Web interface for event recorder service."""

    def __init__(self, database: Database, service_manager=None,
                 wordpress_publisher: Optional[WordPressPublisher] = None,
                 plots_dir: str = "/data/plots",
                 uploads_dir: str = "/data/uploads",
                 host: str = "0.0.0.0", port: int = 5000,
                 charts_config: Optional[Dict] = None,
                 plot_defaults: Optional[Dict] = None,
                 recording_service: Optional[RecordingService] = None):
        """
        Initialize web interface.

        Args:
            database: Database instance
            service_manager: Reference to EventRecorderService (optional)
            wordpress_publisher: WordPress publisher instance (optional)
            plots_dir: Plots directory
            uploads_dir: User uploads directory
            host: Listen host
            port: Listen port
            charts_config: The `charts` service config section, passed to the
                data processor for the offline route-map basemap
            plot_defaults: The `plots` service config section, passed to the
                data processor so a reprocess from here draws the same as one
                the service starts itself. Not to be confused with the
                per-request plot_config, which lists the plots to draw.
            recording_service: What every route that changes a recording
                calls (TR-10). main.py passes the service's own; without one,
                as in the tests, a service that records nothing is built here
                from the arguments above.
        """
        self.database = database
        self.service_manager = service_manager
        self.wordpress_publisher = wordpress_publisher
        self.plots_dir = Path(plots_dir)
        self.uploads_dir = Path(uploads_dir)
        self.charts_config = charts_config
        self.plot_defaults = plot_defaults
        self.host = host
        self.port = port

        self.recordings = recording_service or RecordingService(
            database,
            plots_dir=plots_dir,
            uploads_dir=uploads_dir,
            charts_config=charts_config,
            plot_defaults=plot_defaults,
            wordpress_publisher=wordpress_publisher,
        )

        # Ensure directories exist
        self.plots_dir.mkdir(parents=True, exist_ok=True)
        self.uploads_dir.mkdir(parents=True, exist_ok=True)

        # Create Flask app
        template_dir = Path(__file__).parent / 'web_ui'
        static_dir = Path(__file__).parent / 'web_ui'

        self.app = Flask(__name__,
                        template_folder=str(template_dir),
                        static_folder=str(static_dir))

        self.app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max upload

        # Register routes
        self._register_routes()

        # The event page, at /log (FR-27)
        self.app.register_blueprint(create_event_page(self))

        logger.info(f"WebInterface initialized (port={port})")

    def _image_with_url(self, img: dict) -> dict:
        """Add web-accessible URL to image record."""
        img = dict(img)
        image_path = Path(img['image_path'])
        recording_id = img.get('recording_id', '')
        filename = image_path.name

        if img.get('image_type') == ImageType.USER_UPLOAD:
            img['url'] = f"uploads/{recording_id}/{filename}"
        else:
            img['url'] = f"plots/{recording_id}/{filename}"

        return img

    def _file_url(self, path: str) -> str:
        """
        Where the Pi serves a recording's file, relative to the root: the
        crew's photos, a plot, or an export download.
        """
        path = Path(path)
        recording_id = path.parent.name
        if self.uploads_dir in path.parents:
            return f"uploads/{recording_id}/{path.name}"
        if path.suffix.lower() in ('.csv', '.gpx', '.kml'):
            return f"exports/{recording_id}/{path.name}"
        return f"plots/{recording_id}/{path.name}"

    def _export_with_url(self, exp: dict) -> dict:
        """Add web-accessible download URL to export record."""
        exp = dict(exp)
        file_path = Path(exp['file_path'])
        recording_id = exp.get('recording_id', '')
        exp['url'] = f"exports/{recording_id}/{file_path.name}"
        return exp

    def _refuse_if_published(self, recording_id: int):
        """
        Refuse a change to a recording that has already been published.

        Name, description and photos can be changed at every stage up to
        publishing, so a recording behaves the same whether it is still being
        recorded or has been processed. Once published they are what the post
        shows, and a change here would not reach it; Reset to Processed first.

        Returns:
            A Flask error response, or None when the change may go ahead
        """
        recording = self.database.get_recording(recording_id)
        if not recording:
            return jsonify({'success': False, 'error': 'Recording not found'}), 404
        # Once WordPress has the post, as a draft or live, it is WordPress's
        # to change (Q5); the recording no longer takes edits that would not
        # reach it
        if recording['post_state'] in PostState.OWNED_BY_WORDPRESS:
            return jsonify({
                'success': False,
                'error': 'Recording is already published; change the post in WordPress'
            }), 409
        return None

    def _register_routes(self):
        """Register Flask routes."""

        # === Main page ===
        @self.app.route('/')
        def index():
            """Serve main web interface."""
            return render_template('index.html')

        @self.app.route('/upload')
        def upload_page():
            """
            The old photo page, retired for the Log page, which has photos,
            notes and everything else about the post. A bookmark to it lands
            there, for the same recording. Relative, so it resolves under the
            /events/ prefix as well as on this port.
            """
            recording_id = request.args.get('recording_id', type=int)
            target = f"log/?id={recording_id}&from=events" if recording_id else "log/"
            return redirect(target, code=302)

        # === Static files ===
        @self.app.route('/static/<path:filename>')
        def serve_static(filename):
            """Serve static files (JS, CSS)."""
            return send_from_directory(self.app.static_folder, filename)

        # === Health Check ===
        @self.app.route('/health', methods=['GET'])
        def health():
            """Lightweight health check for Docker HEALTHCHECK and load balancers."""
            try:
                # Verify database is reachable with a minimal query
                self.database.get_database_stats()
                return jsonify({'status': 'ok'}), 200
            except Exception as e:
                logger.error(f"Health check failed: {e}")
                return jsonify({'status': 'error', 'error': str(e)}), 503

        # === Service Status ===
        @self.app.route('/api/status', methods=['GET'])
        def get_status():
            """Get service status."""
            try:
                status = {
                    'service': 'running',
                    'timestamp': datetime.utcnow().isoformat(),
                }

                # Add service manager status if available
                # Counted from what is being recorded, so recordings started
                # here count as well as the triggered ones main.py tracks
                status['active_recordings'] = len(self.recordings.active_recording_ids())
                if self.service_manager:
                    status['buffer_status'] = self.service_manager.data_recorder.get_buffer_status()
                    status['monitor_status'] = self.service_manager.trigger_monitor.get_monitor_status()

                # Database stats
                db_stats = self.database.get_database_stats()
                status['database'] = db_stats

                # WordPress publisher status
                if self.wordpress_publisher:
                    status['wordpress'] = {
                        'configured': True,
                        'site_url': self.wordpress_publisher.site_url
                    }
                else:
                    status['wordpress'] = {
                        'configured': False,
                        'site_url': None
                    }

                return jsonify({'success': True, 'status': status})

            except Exception as e:
                logger.error(f"Status error: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        # === Recordings Management ===
        @self.app.route('/api/recordings', methods=['GET'])
        def list_recordings():
            """List all recordings with optional filters."""
            try:
                # Get query parameters
                status_filter = request.args.get('status')
                limit = int(request.args.get('limit', 100))
                offset = int(request.args.get('offset', 0))

                # The filter is a stage (TR-12), which is derived rather than
                # stored, so it is applied here. 'active' is the one stage that
                # is also a status, and the dashboard asks for it every second,
                # so that one is still a query.
                if status_filter == RecordingStatus.ACTIVE:
                    recordings = self.database.get_recordings_by_status(status_filter)
                else:
                    recordings = self.database.get_all_recordings(limit, offset)
                    if status_filter:
                        recordings = [r for r in recordings if r['stage'] == status_filter]

                # Add message counts
                for recording in recordings:
                    recording['message_count'] = self.database.get_recording_data_count(
                        recording['id']
                    )

                return jsonify({
                    'success': True,
                    'recordings': recordings,
                    'count': len(recordings)
                })

            except Exception as e:
                logger.error(f"List recordings error: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/recordings/<int:recording_id>', methods=['GET'])
        def get_recording(recording_id):
            """Get recording details."""
            try:
                recording = self.database.get_recording(recording_id)
                if not recording:
                    return jsonify({'success': False, 'error': 'Recording not found'}), 404

                # Add additional details
                recording['message_count'] = self.database.get_recording_data_count(recording_id)
                recording['topics'] = self.database.get_recording_topics(recording_id)
                recording['images'] = [
                    self._image_with_url(img)
                    for img in self.database.get_recording_images(recording_id)
                ]
                recording['exports'] = [
                    self._export_with_url(exp)
                    for exp in self.database.get_recording_exports(recording_id)
                ]

                return jsonify({'success': True, 'recording': recording})

            except Exception as e:
                logger.error(f"Get recording error: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/recordings/<int:recording_id>/data', methods=['GET'])
        def get_recording_data(recording_id):
            """Get recording data with pagination."""
            try:
                # Get query parameters
                topic_filter = request.args.get('topic')
                limit = int(request.args.get('limit', 1000))

                data = self.database.get_recording_data(
                    recording_id,
                    topic_filter=topic_filter,
                    limit=limit
                )

                return jsonify({
                    'success': True,
                    'data': data,
                    'count': len(data)
                })

            except Exception as e:
                logger.error(f"Get recording data error: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/recordings', methods=['POST'])
        def create_recording():
            """Manually create/start a recording."""
            try:
                data = request.get_json()
                # Local time: the name is read by the crew and becomes the blog
                # post title. Stored timestamps stay UTC.
                name = data.get('name', f"Manual Recording - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                description = data.get('description', '')
                topics = data.get('topics', ['gps/#', 'battery/#'])

                recording_id = self.recordings.start(name, description, topics)

                return jsonify({
                    'success': True,
                    'recording_id': recording_id,
                    'message': f'Recording {recording_id} started'
                })

            except Exception as e:
                logger.error(f"Create recording error: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/recordings/<int:recording_id>', methods=['PUT'])
        def update_recording(recording_id):
            """Update recording metadata (name, description)."""
            try:
                data = request.get_json()

                # Only allow updating certain fields
                update_fields = {}
                if 'name' in data:
                    update_fields['name'] = data['name']
                if 'description' in data:
                    update_fields['description'] = data['description']

                if not update_fields:
                    return jsonify({'success': False, 'error': 'No fields to update'}), 400

                refused = self._refuse_if_published(recording_id)
                if refused:
                    return refused

                self.database.update_recording(recording_id, **update_fields)

                return jsonify({
                    'success': True,
                    'message': f'Recording {recording_id} updated'
                })

            except Exception as e:
                logger.error(f"Update recording error: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/recordings/<int:recording_id>', methods=['DELETE'])
        def delete_recording(recording_id):
            """Delete a recording."""
            try:
                self.recordings.delete(recording_id)
                return jsonify({
                    'success': True,
                    'message': f'Recording {recording_id} deleted'
                })

            except RecordingError as e:
                return jsonify({'success': False, 'error': str(e)}), e.status
            except Exception as e:
                logger.error(f"Delete recording error: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/recordings/<int:recording_id>/stop', methods=['POST'])
        def stop_recording(recording_id):
            """Manually stop a recording."""
            try:
                auto_processing = self.recordings.stop(recording_id)
                return jsonify({
                    'success': True,
                    'message': f'Recording {recording_id} stopped',
                    'auto_processing': auto_processing
                })

            except RecordingError as e:
                return jsonify({'success': False, 'error': str(e)}), e.status
            except Exception as e:
                logger.error(f"Stop recording error: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/exports/<int:recording_id>/<path:filename>')
        def serve_export(recording_id, filename):
            """Serve export file (CSV, KML, GPX) as a download."""
            try:
                export_dir = self.plots_dir / str(recording_id)
                file_path = export_dir / filename
                if not file_path.exists():
                    return jsonify({'success': False, 'error': 'Export not found'}), 404

                mime_map = {
                    '.csv': 'text/csv',
                    '.kml': 'application/vnd.google-earth.kml+xml',
                    '.gpx': 'application/gpx+xml',
                }
                mimetype = mime_map.get(file_path.suffix.lower(), 'application/octet-stream')
                return send_file(str(file_path), mimetype=mimetype,
                                 as_attachment=True, download_name=file_path.name)
            except Exception as e:
                logger.error(f"Serve export error: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/recordings/<int:recording_id>/process', methods=['POST'])
        def process_recording(recording_id):
            """Process recording (generate plots and export files)."""
            try:
                data = request.get_json(silent=True) or {}
                results = self.recordings.process(recording_id,
                                                  data.get('plot_config', []),
                                                  data.get('export_config', None))

                if results['status'] == 'success':
                    return jsonify({
                        'success': True,
                        'results': results,
                        'message': f'Recording {recording_id} processed'
                    })
                else:
                    return jsonify({
                        'success': False,
                        'error': results.get('error', 'Processing failed')
                    }), 500

            except Exception as e:
                logger.error(f"Process recording error: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/recordings/<int:recording_id>/reset', methods=['POST'])
        def reset_recording_status(recording_id):
            """Reset recording status from failed or published back to processed."""
            try:
                self.recordings.reset_to_processed(recording_id)
                return jsonify({'success': True, 'message': f'Recording reset to processed'})

            except RecordingError as e:
                return jsonify({'success': False, 'error': str(e)}), e.status
            except Exception as e:
                logger.error(f"Reset recording status error: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/recordings/<int:recording_id>/publish', methods=['POST'])
        def publish_recording(recording_id):
            """Start publishing to WordPress. Returns 202 and the job, which
            GET on the same URL reports on until it is done or failed."""
            try:
                data = request.get_json(silent=True) or {}
                job = self.recordings.start_publish(
                    recording_id,
                    category=data.get('category', 'Track Logs'),
                    template=data.get('template', None),
                    auto_publish=data.get('auto_publish', None)
                )
                return jsonify({'success': True, 'job': job}), 202

            except RecordingError as e:
                return jsonify({'success': False, 'error': str(e)}), e.status
            except Exception as e:
                logger.error(f"Publish recording error: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/recordings/<int:recording_id>/draft', methods=['GET'])
        def get_draft(recording_id):
            """The recording's post draft, stored or as a new one would start (FR-24)."""
            try:
                return jsonify({'success': True, 'draft': self.recordings.get_draft(recording_id)})
            except RecordingError as e:
                return jsonify({'success': False, 'error': str(e)}), e.status
            except Exception as e:
                logger.error(f"Get draft error: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/recordings/<int:recording_id>/draft', methods=['PUT'])
        def save_draft(recording_id):
            """Change draft fields. Body: {"revision": n, "changes": {...}}. 409 if
            another save has happened since revision n, with the current draft."""
            try:
                data = request.get_json(silent=True) or {}
                if 'revision' not in data or not isinstance(data.get('changes'), dict):
                    return jsonify({'success': False,
                                    'error': 'Body needs "revision" and a "changes" object'}), 400
                draft = self.recordings.save_draft(recording_id, data['changes'],
                                                   int(data['revision']))
                return jsonify({'success': True, 'draft': draft})
            except RecordingError as e:
                body = {'success': False, 'error': str(e)}
                if e.status == 409:
                    body['draft'] = self.recordings.get_draft(recording_id)
                return jsonify(body), e.status
            except Exception as e:
                logger.error(f"Save draft error: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/preview')
        def preview_post():
            """
            The post as it would be published, as a page (FR-24). At the root,
            not under /recordings/<id>/, so the relative image URLs in it
            resolve here and behind the /events/ prefix alike.
            ?id=<recording>  &layout=track_log|ship_log to compare layouts
            """
            try:
                recording_id = int(request.args.get('id', 0))
                layout = request.args.get('layout') or None
                content = self.recordings.preview(recording_id, self._file_url, layout)
                draft = self.recordings.get_draft(recording_id)
                return _preview_page(recording_id, draft['title'], content, layout)
            except RecordingError as e:
                return jsonify({'success': False, 'error': str(e)}), e.status
            except ValueError:
                return jsonify({'success': False, 'error': 'id must be a recording id'}), 400

        @self.app.route('/api/recordings/<int:recording_id>/publish', methods=['GET'])
        def publish_progress(recording_id):
            """The recording's latest publish job: running, done or failed."""
            try:
                job = self.recordings.publish_job(recording_id)
                if not job:
                    return jsonify({'success': False,
                                    'error': 'No publish started for this recording '
                                             'since the service started'}), 404
                return jsonify({'success': True, 'job': job})

            except RecordingError as e:
                return jsonify({'success': False, 'error': str(e)}), e.status
            except Exception as e:
                logger.error(f"Publish recording error: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/wordpress/test', methods=['GET'])
        def test_wordpress():
            """Test WordPress connection."""
            try:
                if not self.wordpress_publisher:
                    return jsonify({
                        'success': False,
                        'error': 'WordPress publisher not configured'
                    }), 400

                success, message = self.wordpress_publisher.test_connection()

                return jsonify({
                    'success': success,
                    'message': message
                })

            except Exception as e:
                logger.error(f"WordPress test error: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        # === Service Settings ===
        @self.app.route('/api/settings', methods=['GET'])
        def get_settings():
            """Get service settings."""
            try:
                return jsonify({
                    'success': True,
                    'settings': {
                        'auto_process_on_stop': self.database.get_setting('auto_process_on_stop', 'false') == 'true'
                    }
                })
            except Exception as e:
                logger.error(f"Get settings error: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/settings', methods=['POST'])
        def update_settings():
            """Update service settings."""
            try:
                data = request.get_json()
                if 'auto_process_on_stop' in data:
                    value = 'true' if data['auto_process_on_stop'] else 'false'
                    self.database.set_setting('auto_process_on_stop', value)
                return jsonify({'success': True})
            except Exception as e:
                logger.error(f"Update settings error: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        # === Image Management ===
        @self.app.route('/api/recordings/<int:recording_id>/images', methods=['POST'])
        def upload_image(recording_id):
            """Upload image to recording."""
            try:
                if 'file' not in request.files:
                    return jsonify({'success': False, 'error': 'No file provided'}), 400

                file = request.files['file']
                if file.filename == '':
                    return jsonify({'success': False, 'error': 'No file selected'}), 400

                # Validate file type
                allowed_extensions = {'png', 'jpg', 'jpeg', 'gif'}
                filename = secure_filename(file.filename)
                ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''

                if ext not in allowed_extensions:
                    return jsonify({
                        'success': False,
                        'error': f'Invalid file type. Allowed: {allowed_extensions}'
                    }), 400

                refused = self._refuse_if_published(recording_id)
                if refused:
                    return refused

                # Save file
                upload_dir = self.uploads_dir / str(recording_id)
                upload_dir.mkdir(parents=True, exist_ok=True)

                timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
                new_filename = f"{timestamp}_{filename}"
                file_path = upload_dir / new_filename
                file.save(str(file_path))

                # Add to database
                caption = request.form.get('caption', '')
                image_id = self.database.add_image(
                    recording_id,
                    str(file_path),
                    ImageType.USER_UPLOAD,
                    caption
                )

                return jsonify({
                    'success': True,
                    'image_id': image_id,
                    'path': str(file_path),
                    'message': 'Image uploaded successfully'
                })

            except Exception as e:
                logger.error(f"Upload image error: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/recordings/<int:recording_id>/images', methods=['GET'])
        def get_recording_images(recording_id):
            """Get all images for recording."""
            try:
                images = [
                    self._image_with_url(img)
                    for img in self.database.get_recording_images(recording_id)
                ]

                return jsonify({
                    'success': True,
                    'images': images,
                    'count': len(images)
                })

            except Exception as e:
                logger.error(f"Get images error: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/images/<int:image_id>', methods=['DELETE'])
        def delete_image(image_id):
            """Delete an image."""
            try:
                # Get image from database
                # Note: Need to add get_image method to Database class
                # For now, just delete from database
                self.database.delete_image(image_id)

                return jsonify({
                    'success': True,
                    'message': f'Image {image_id} deleted'
                })

            except Exception as e:
                logger.error(f"Delete image error: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        # === Serve images/plots ===
        @self.app.route('/plots/<int:recording_id>/<path:filename>')
        def serve_plot(recording_id, filename):
            """Serve plot image."""
            try:
                plot_dir = self.plots_dir / str(recording_id)
                return send_from_directory(plot_dir, filename)
            except Exception as e:
                logger.error(f"Serve plot error: {e}")
                return jsonify({'success': False, 'error': 'Plot not found'}), 404

        @self.app.route('/uploads/<int:recording_id>/<path:filename>')
        def serve_upload(recording_id, filename):
            """Serve uploaded image."""
            try:
                upload_dir = self.uploads_dir / str(recording_id)
                return send_from_directory(upload_dir, filename)
            except Exception as e:
                logger.error(f"Serve upload error: {e}")
                return jsonify({'success': False, 'error': 'Image not found'}), 404

    def run(self, debug: bool = False):
        """Start Flask server."""
        logger.info("="*60)
        logger.info("Event Recorder Web Interface")
        logger.info("="*60)
        logger.info(f"Server: http://{self.host}:{self.port}")
        logger.info(f"Open your browser and navigate to http://localhost:{self.port}")
        logger.info("="*60)

        self.app.run(host=self.host, port=self.port, debug=debug, threaded=True)

    def run_with_gunicorn(self):
        """Run with Gunicorn (production)."""
        import gunicorn.app.base

        class StandaloneApplication(gunicorn.app.base.BaseApplication):
            def __init__(self, app, options=None):
                self.options = options or {}
                self.application = app
                super().__init__()

            def load_config(self):
                for key, value in self.options.items():
                    self.cfg.set(key.lower(), value)

            def load(self):
                return self.application

        options = {
            'bind': f'{self.host}:{self.port}',
            'workers': 2,
            'timeout': 120,
            'accesslog': '-',
            'errorlog': '-',
            'loglevel': 'info'
        }

        logger.info("Starting Gunicorn server")
        StandaloneApplication(self.app, options).run()


def main():
    """CLI for testing web interface."""
    import argparse

    parser = argparse.ArgumentParser(description="Event Recorder Web Interface")
    parser.add_argument('--db', default='/data/recordings.db', help="Database path")
    parser.add_argument('--plots-dir', default='/data/plots', help="Plots directory")
    parser.add_argument('--host', default='0.0.0.0', help="Listen host")
    parser.add_argument('--port', type=int, default=5000, help="Listen port")
    parser.add_argument('--debug', action='store_true', help="Debug mode")

    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(level=logging.INFO,
                       format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    from .models import Database
    db = Database(args.db)

    web = WebInterface(db, plots_dir=args.plots_dir, host=args.host, port=args.port)
    web.run(debug=args.debug)


if __name__ == '__main__':
    main()
