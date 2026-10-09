"""
Recording service (TR-10): the one place a recording is started, stopped,
processed, published and deleted.

The GPS triggers in main.py and the routes in web_interface.py both call this,
so the two cannot drift apart. They had: auto-process was written twice, the
publish logic lived in a route, and a recording started from the web UI never
reached the service's own bookkeeping, so the clock-step repair skipped it and
shutdown did not end it.

Routes keep only the request and the response. Refusals come back as
RecordingError carrying the HTTP status that fits them.
"""

import json
import logging
import shutil
import threading
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional

from .models import Database, ImageType, RecordingStatus

logger = logging.getLogger(__name__)


class RecordingError(Exception):
    """A request the service refuses, with the HTTP status a route should give it."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class RecordingService:
    """Owns the life of a recording, whoever asks for the change."""

    def __init__(self, database: Database, data_recorder=None,
                 plots_dir: str = "/data/plots",
                 uploads_dir: str = "/data/uploads",
                 charts_config: Optional[Dict] = None,
                 plot_defaults: Optional[Dict] = None,
                 wordpress_publisher=None,
                 wordpress_config: Optional[Callable[[], Dict]] = None):
        """
        Args:
            database: Database instance
            data_recorder: DataRecorder, or None where nothing is recorded
                (tests, and a web interface run on its own)
            plots_dir: Generated plots and exports, one directory per recording
            uploads_dir: The crew's photos, one directory per recording
            charts_config: The `charts` service config section
            plot_defaults: The `plots` service config section
            wordpress_publisher: WordPressPublisher, or None when not configured
            wordpress_config: Returns the current `wordpress.default_site`
                section. A callable rather than a dict, because the config
                reloads while the service runs.
        """
        self.database = database
        self.data_recorder = data_recorder
        self.plots_dir = Path(plots_dir)
        self.uploads_dir = Path(uploads_dir)
        self.charts_config = charts_config
        self.plot_defaults = plot_defaults
        self.wordpress_publisher = wordpress_publisher
        self.wordpress_config = wordpress_config

        # Recordings started by this process. Only these can have been written
        # on a clock that has since been corrected (main._check_for_clock_step).
        self._started_this_run = set()
        self._lock = threading.Lock()

    @property
    def recordings_this_run(self) -> set:
        with self._lock:
            return set(self._started_this_run)

    def active_recording_ids(self) -> List[int]:
        """Recordings this process is recording now, whatever started them."""
        if not self.data_recorder:
            return []
        return self.data_recorder.get_active_recordings()

    # === Start and stop ===

    def start(self, name: str, description: str = "", topics: List[str] = None,
              trigger_type: str = "manual") -> int:
        """Create a recording and start recording its topics."""
        recording_id = self.database.create_recording(name, description,
                                                      trigger_type=trigger_type)
        if self.data_recorder:
            self.data_recorder.start_recording(recording_id, topics or [])
        with self._lock:
            self._started_this_run.add(recording_id)
        logger.info(f"Started recording {recording_id}: {name}")
        return recording_id

    def stop(self, recording_id: int) -> bool:
        """
        Stop an active recording, and process it if auto-process is on.

        Returns:
            True when auto-processing was started
        """
        recording = self._get(recording_id)
        if recording['status'] != RecordingStatus.ACTIVE:
            raise RecordingError(
                f"Recording is not active (status: {recording['status']})", 400)

        self._end(recording_id)

        if self.database.get_setting('auto_process_on_stop', 'false') == 'true':
            self.process_in_background(recording_id)
            return True
        return False

    def stop_all(self):
        """End every recording this process is recording, on shutdown."""
        for recording_id in self.active_recording_ids():
            logger.info(f"Stopping active recording {recording_id}")
            try:
                self._end(recording_id)
            except Exception as e:
                logger.error(f"Could not stop recording {recording_id}: {e}")

    def _end(self, recording_id: int):
        if self.data_recorder:
            self.data_recorder.stop_recording(recording_id)
        self.database.update_recording(
            recording_id,
            status=RecordingStatus.STOPPED,
            end_time=datetime.utcnow()
        )

    # === Processing ===

    def process(self, recording_id: int, plot_config: List[Dict] = None,
                export_config: Dict = None) -> Dict:
        """Generate plots, statistics and export files. Returns the processor's results."""
        # Imported here: data_processor pulls in matplotlib, which the web
        # interface and the tests should not pay for until something is drawn
        from .data_processor import DataProcessor
        processor = DataProcessor(self.database, str(self.plots_dir),
                                  self.charts_config, self.plot_defaults)
        return processor.process_recording(recording_id, plot_config, export_config)

    def process_in_background(self, recording_id: int) -> threading.Thread:
        def run():
            try:
                logger.info(f"Auto-processing recording {recording_id}")
                self.process(recording_id)
                logger.info(f"Auto-processing complete for recording {recording_id}")
            except Exception as e:
                logger.error(f"Auto-processing failed for recording {recording_id}: {e}")

        thread = threading.Thread(target=run, daemon=True,
                                  name=f"AutoProcess-{recording_id}")
        thread.start()
        logger.info(f"Auto-processing started for recording {recording_id}")
        return thread

    # === Status changes and deletion ===

    def reset_to_processed(self, recording_id: int) -> str:
        """Put a failed or published recording back to processed. Returns the old status."""
        recording = self._get(recording_id)
        if recording['status'] not in (RecordingStatus.FAILED, RecordingStatus.PUBLISHED):
            raise RecordingError(f"Cannot reset from status '{recording['status']}'", 400)
        self.database.update_recording(recording_id, status=RecordingStatus.PROCESSED)
        logger.info(f"Recording {recording_id} reset to processed (was {recording['status']})")
        return recording['status']

    def delete(self, recording_id: int):
        """Delete a stopped recording: its rows (by cascade), plots, exports and photos."""
        recording = self._get(recording_id)
        if recording['status'] == RecordingStatus.ACTIVE:
            raise RecordingError('Cannot delete active recording', 400)

        # The crew's photos as well as the generated files: nothing else would
        # ever remove them
        for files_dir in (self.plots_dir / str(recording_id),
                          self.uploads_dir / str(recording_id)):
            if files_dir.exists():
                shutil.rmtree(files_dir)

        self.database.delete_recording(recording_id)

    # === Publishing ===

    def publish(self, recording_id: int, category: str = 'Track Logs',
                template: str = None, auto_publish: Optional[bool] = None) -> Dict:
        """
        Publish a recording to WordPress.

        Returns:
            The post dict from the publisher, including `failed_uploads`
        """
        if not self.wordpress_publisher:
            raise RecordingError('WordPress publisher not configured', 400)

        recording = self._get(recording_id)

        # One request to see whether the site can be reached at all,
        # before sending it a few dozen files. Publishing from a phone
        # hotspot with a stale resolver spent seven minutes failing
        # every upload in turn, each with its own retries, and said
        # only that publishing had failed. The status is left alone
        # here: the boat being off the air is not a fault in the
        # recording, and it should publish on the next attempt without
        # having to be reset first.
        reachable, detail = self.wordpress_publisher.test_connection()
        if not reachable:
            logger.error(f"Not publishing recording {recording_id}: {detail}")
            raise RecordingError(f'Cannot reach WordPress: {detail}', 503)

        images = self.database.get_recording_images(recording_id)
        if not images:
            raise RecordingError('No images found for recording', 400)

        image_list = []
        for img in images:
            img_path = Path(img['image_path'])
            if img_path.exists():
                image_list.append({
                    'path': str(img_path),
                    'caption': img.get('caption', ''),
                    'image_type': img.get('image_type', ImageType.PLOT)
                })
            else:
                logger.warning(f"Image file not found: {img_path}")

        if not image_list:
            raise RecordingError('No image files found', 400)

        # Default publish mode from the main config's publish_status:
        # "publish" puts the post live at once, "draft" saves it as a draft.
        # The caller can still override it with an explicit auto_publish.
        if auto_publish is None:
            auto_publish = False
            if self.wordpress_config:
                try:
                    wp_cfg = self.wordpress_config()
                    if wp_cfg:
                        auto_publish = wp_cfg.get('publish_status', 'draft') == 'publish'
                except Exception:
                    pass

        recording_plots = self.plots_dir / str(recording_id)

        # Statistics JSON sidecar if present; the PNG is left out of the
        # uploads because the post renders the numbers as an HTML table
        statistics = None
        stats_json_path = recording_plots / 'statistics_summary.json'
        if stats_json_path.exists():
            try:
                with open(stats_json_path) as f:
                    statistics = json.load(f)
                image_list = [
                    img for img in image_list
                    if Path(img['path']).name != 'statistics_summary.png'
                ]
                logger.info("Loaded statistics JSON; statistics_summary.png excluded from upload")
            except Exception as e:
                logger.warning(f"Could not load statistics JSON: {e}")

        # Folium HTML maps; the matching PNGs are left out so the interactive
        # map replaces the static screenshot in the post
        map_htmls = []
        for html_file in sorted(recording_plots.glob('*.html')):
            map_htmls.append(str(html_file))
            image_list = [
                img for img in image_list
                if Path(img['path']).stem != html_file.stem
            ]
        if map_htmls:
            logger.info(
                f"Found {len(map_htmls)} map HTML file(s); "
                "matching PNG(s) excluded from upload"
            )

        export_list = []
        for exp in self.database.get_recording_exports(recording_id):
            exp_path = Path(exp['file_path'])
            if exp_path.exists():
                export_list.append({
                    'path': str(exp_path),
                    'label': exp.get('label', exp['export_type'].upper()),
                    'export_type': exp['export_type']
                })

        logger.info(f"Publishing recording {recording_id} to WordPress")
        post = self.wordpress_publisher.publish_recording(
            recording_data=recording,
            images=image_list,
            exports=export_list,
            statistics=statistics,
            map_htmls=map_htmls,
            template=template,
            category=category,
            auto_publish=auto_publish
        )

        if not post:
            self.database.update_recording(
                recording_id,
                status=RecordingStatus.FAILED,
                error_message="WordPress publishing failed"
            )
            raise RecordingError('Failed to create WordPress post', 500)

        self.database.update_recording(
            recording_id,
            status=RecordingStatus.PUBLISHED,
            wordpress_url=post['link']
        )
        logger.info(f"Recording published: {post['link']}")
        post.setdefault('failed_uploads', [])
        return post

    # === Helpers ===

    def _get(self, recording_id: int) -> Dict:
        recording = self.database.get_recording(recording_id)
        if not recording:
            raise RecordingError('Recording not found', 404)
        return recording
