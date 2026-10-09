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
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional

from . import post_renderer
from .models import Artefacts, Database, ImageType, PostState, RecordingStatus

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
                 wordpress_config: Optional[Callable[[], Dict]] = None,
                 event_configs: Optional[Callable[[], Dict]] = None):
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
        # Returns the enabled event configs, {key: config}. A callable, like
        # wordpress_config, because the config reloads while the service runs.
        self.event_configs = event_configs

        # Recordings started by this process. Only these can have been written
        # on a clock that has since been corrected (main._check_for_clock_step).
        self._started_this_run = set()
        # The latest publish job per recording (TR-11). In memory: a restart
        # mid-publish loses the job, not the post, which is found again by
        # its stored id on the next attempt.
        self._publish_jobs = {}
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
              trigger_type: str = "manual", event_key: str = "manual") -> int:
        """Create a recording and start recording its topics."""
        recording_id = self.database.create_recording(name, description,
                                                      trigger_type=trigger_type,
                                                      event_key=event_key)
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
        # Processed while still recording: the plots stop short of the end
        if self.database.get_recording(recording_id)['artefacts'] == Artefacts.FRESH:
            self.database.update_recording(recording_id, artefacts=Artefacts.STALE)

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
        """
        Clear a failed process or publish so it can be tried again. Returns
        the stage the recording was at.

        Before TR-12 this was also how a published recording was made
        publishable again. That is no longer needed: a publish updates the
        recording's own post (TR-11). So a published recording is refused
        here, as anything else that has not failed is.
        """
        recording = self._get(recording_id)
        stage = recording['stage']
        if recording['post_state'] == PostState.PUBLISH_FAILED:
            # Back to where the post was before the attempt: none, unless
            # an earlier publish put it out
            self.database.set_post_state(
                recording_id,
                PostState.PUBLISHED if recording.get('wp_post_id') else PostState.NONE)
        elif recording['artefacts'] == Artefacts.FAILED:
            self.database.update_recording(recording_id, artefacts=Artefacts.NONE,
                                           error_message=None)
        else:
            raise RecordingError(f"Nothing to reset: the recording is {stage}", 400)
        logger.info(f"Recording {recording_id} reset (was {stage})")
        return stage

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

    def start_publish(self, recording_id: int, **options) -> Dict:
        """
        Start publishing in the background (TR-11) and return the job.

        Only what can be answered at once is checked here. Everything that
        talks to WordPress happens in the job, because from a phone hotspot
        that is minutes, and a request held open that long is one a phone
        gives up on while the upload carries on unseen.
        """
        if not self.wordpress_publisher:
            raise RecordingError('WordPress publisher not configured', 400)
        self._get(recording_id)

        with self._lock:
            job = self._publish_jobs.get(recording_id)
            if job and job['state'] == 'running':
                raise RecordingError('Already publishing this recording', 409)
            job = {
                'recording_id': recording_id,
                'state': 'running',
                'step': 'Starting',
                'done': 0,
                'total': 0,
                'post': None,
                'error': None,
                'status': None,
                'started_at': datetime.utcnow().isoformat(),
                'finished_at': None,
            }
            self._publish_jobs[recording_id] = job

        def progress(step, done, total):
            with self._lock:
                job.update(step=step, done=done, total=total)

        def run():
            try:
                # One button on the event page: a recording not yet processed,
                # or processed before it changed, is drawn first
                if self.database.get_recording(recording_id)['artefacts'] != Artefacts.FRESH:
                    progress('Drawing the charts', 0, 0)
                    results = self.process(recording_id)
                    if results.get('status') != 'success':
                        raise RecordingError(
                            f"Could not draw the charts: {results.get('error', 'processing failed')}", 500)
                post = self.publish(recording_id, progress=progress, **options)
                outcome = {'state': 'done', 'step': 'Published', 'post': post}
            except RecordingError as e:
                outcome = {'state': 'failed', 'error': str(e), 'status': e.status}
            except Exception as e:
                logger.error(f"Publishing recording {recording_id} failed: {e}")
                outcome = {'state': 'failed', 'error': str(e), 'status': 500}
            with self._lock:
                job.update(outcome, finished_at=datetime.utcnow().isoformat())

        threading.Thread(target=run, daemon=True,
                         name=f"Publish-{recording_id}").start()
        return self.publish_job(recording_id)

    def publish_job(self, recording_id: int) -> Optional[Dict]:
        """The latest publish job for a recording, as a copy, or None."""
        with self._lock:
            job = self._publish_jobs.get(recording_id)
            return dict(job) if job else None

    def publish(self, recording_id: int, category: str = 'Track Logs',
                template: str = None, auto_publish: Optional[bool] = None,
                progress: Optional[Callable[[str, int, int], None]] = None) -> Dict:
        """
        Publish a recording to WordPress, there and then. start_publish() runs
        this in the background; this is the work itself.

        A recording is one post for its whole life: once published, a later
        publish updates that post rather than making another. It refuses if
        the post was changed in wp-admin since, because that work would be
        overwritten, and creates a new post only if the old one is gone.

        Returns:
            The post dict from the publisher, including `failed_uploads`
        """
        if not self.wordpress_publisher:
            raise RecordingError('WordPress publisher not configured', 400)

        recording = self._get(recording_id)

        def step(text):
            if progress:
                progress(text, 0, 0)

        # One request to see whether the site can be reached at all,
        # before sending it a few dozen files. Publishing from a phone
        # hotspot with a stale resolver spent seven minutes failing
        # every upload in turn, each with its own retries, and said
        # only that publishing had failed. The status is left alone
        # here: the boat being off the air is not a fault in the
        # recording, and it should publish on the next attempt without
        # having to be reset first.
        step('Connecting to WordPress')
        reachable, detail = self.wordpress_publisher.test_connection()
        if not reachable:
            logger.error(f"Not publishing recording {recording_id}: {detail}")
            raise RecordingError(f'Cannot reach WordPress: {detail}', 503)

        post_id = self._existing_post_id(recording_id)

        images = self.database.get_recording_images(recording_id)
        if not images:
            raise RecordingError('No images found for recording', 400)

        inputs = self._gather(recording_id)
        # The statistics table and the interactive map stand in for their
        # PNGs, so a recording with only those still has something to post
        if not (inputs['images'] or inputs['statistics'] or inputs['map_htmls']):
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

        draft = self.database.get_draft(recording_id)
        blocks = draft['blocks'] if draft else self.default_blocks()

        # The post's state from here on, never the recording's (TR-12). Set
        # only now, after the refusals above, which leave the post as it was.
        logger.info(f"Publishing recording {recording_id} to WordPress")
        self.database.set_post_state(recording_id, PostState.PUBLISHING)
        try:
            post = self.wordpress_publisher.publish_recording(
                recording_data=recording,
                images=inputs['images'],
                exports=inputs['exports'],
                statistics=inputs['statistics'],
                map_htmls=inputs['map_htmls'],
                template=template,
                category=category,
                auto_publish=auto_publish,
                post_id=post_id,
                progress=progress,
                blocks=blocks,
                draft=draft
            )
        except Exception as e:
            self.database.set_post_state(recording_id, PostState.PUBLISH_FAILED,
                                         f"WordPress publishing failed: {e}")
            raise

        if not post:
            self.database.set_post_state(recording_id, PostState.PUBLISH_FAILED,
                                         "WordPress publishing failed")
            raise RecordingError('Failed to create WordPress post', 500)

        self.database.save_post_ref(recording_id, post['id'],
                                    post.get('modified_gmt'), post.get('status'))
        # A WordPress draft is still WordPress's to finish (Q5); 'future' is
        # a post that will go live by itself, so it counts as published
        self.database.set_post_state(
            recording_id,
            PostState.WP_DRAFT if post.get('status') in ('draft', 'pending')
            else PostState.PUBLISHED)
        self.database.update_recording(recording_id, wordpress_url=post['link'])
        logger.info(f"Recording published: {post['link']}")
        post.setdefault('failed_uploads', [])
        return post

    def _existing_post_id(self, recording_id: int) -> Optional[int]:
        """
        The post to update, or None to create one.

        Raises RecordingError (409) when the post was edited in WordPress
        since this recording last published it.
        """
        ref = self.database.get_post_draft(recording_id)
        if not ref or not ref.get('wp_post_id'):
            self._refuse_if_published_untracked(recording_id)
            return None
        post_id = ref['wp_post_id']

        try:
            current = self.wordpress_publisher.get_post(post_id)
        except Exception as e:
            # Not knowing is not the same as it being gone: answering this
            # with a new post is how a recording ends up published twice
            raise RecordingError(f'Could not check post {post_id} in WordPress: {e}', 503)

        if current is None:
            logger.warning(f"Post {post_id} for recording {recording_id} is gone "
                           f"from WordPress; publishing a new one")
            return None

        if current.get('modified_gmt') != ref.get('wp_modified'):
            raise RecordingError(
                f"Post {post_id} has been edited in WordPress since it was published "
                f"from here (last changed {current.get('modified_gmt')} UTC). "
                f"Publishing again would overwrite that, so it has not been done.",
                409)
        return post_id

    def _refuse_if_published_untracked(self, recording_id: int):
        """
        A recording published before TR-11 has a link but no post id, and no
        record of when WordPress last changed the post. Publishing it again
        would make a second post, and there is no way to tell whether the
        first was edited in wp-admin since, which the Track Logs on
        enchantee.org often are. So while that post exists, refuse; once it
        has been deleted there, publish afresh.
        """
        link = self._get(recording_id).get('wordpress_url')
        if not link:
            return
        try:
            post = self.wordpress_publisher.find_post_by_link(link)
        except Exception as e:
            raise RecordingError(f'Could not check {link} in WordPress: {e}', 503)
        if post:
            raise RecordingError(
                f"This recording was published as {link} before the recorder kept "
                f"track of its posts, so it cannot tell whether that post has been "
                f"edited in WordPress since. Change it there, or delete it there and "
                f"publish again.", 409)
        logger.info(f"{link} is gone from WordPress; publishing recording "
                    f"{recording_id} as a new post")

    def _gather(self, recording_id: int) -> Dict:
        """
        What a post is made from, as files on the Pi: images (plots and
        photos), the statistics, the folium maps and the exports. Shared by
        publish and preview, so the preview is drawn from what would go out.
        """
        images = []
        for img in self.database.get_recording_images(recording_id):
            img_path = Path(img['image_path'])
            if img_path.exists():
                images.append({
                    'path': str(img_path),
                    'caption': img.get('caption', ''),
                    'image_type': img.get('image_type', ImageType.PLOT)
                })
            else:
                logger.warning(f"Image file not found: {img_path}")

        recording_plots = self.plots_dir / str(recording_id)

        # Statistics JSON sidecar if present; the PNG is left out because the
        # post renders the numbers as an HTML table
        statistics = None
        stats_json_path = recording_plots / 'statistics_summary.json'
        if stats_json_path.exists():
            try:
                with open(stats_json_path) as f:
                    statistics = json.load(f)
                images = [img for img in images
                          if Path(img['path']).name != 'statistics_summary.png']
            except Exception as e:
                logger.warning(f"Could not load statistics JSON: {e}")

        # Folium HTML maps; the matching PNGs are left out so the interactive
        # map replaces the static screenshot in the post
        map_htmls = []
        for html_file in sorted(recording_plots.glob('*.html')):
            map_htmls.append(str(html_file))
            images = [img for img in images if Path(img['path']).stem != html_file.stem]

        exports = []
        for exp in self.database.get_recording_exports(recording_id):
            exp_path = Path(exp['file_path'])
            if exp_path.exists():
                exports.append({
                    'path': str(exp_path),
                    'label': exp.get('label', exp['export_type'].upper()),
                    'export_type': exp['export_type']
                })

        return {'images': images, 'statistics': statistics,
                'map_htmls': map_htmls, 'exports': exports}

    # === Which recording the event page opens (FR-28) ===

    # Recordings started this close together are one outing: the boat's two
    # triggers both fire for every sail, a few seconds apart
    SAME_OUTING = timedelta(hours=12)

    def editor_default_keys(self) -> set:
        """Event keys marked `editor_default: true` in the event config."""
        if not self.event_configs:
            return set()
        try:
            return {key for key, config in self.event_configs().items()
                    if config.get('editor_default')}
        except Exception as e:
            logger.warning(f"Could not read the event config for editor_default: {e}")
            return set()

    def editor_choice(self) -> Dict:
        """
        The recording the event page opens with no id, and the others it
        could have opened, for the switcher.

        1. An active recording of an editor_default event
        2. Otherwise the most recent active recording
        3. Otherwise the newest unpublished recording, preferring an
           editor_default one from the same outing. Only the same outing: a
           week-old unpublished anchor recording is not what today's crew want.

        Returns:
            {'recording': dict or None, 'candidates': [dict, ...]}, the
            candidates being the active recordings, or the unpublished ones
            from the chosen recording's outing
        """
        defaults = self.editor_default_keys()
        recordings = self.database.get_all_recordings(limit=200)

        active = [r for r in recordings if r['status'] == RecordingStatus.ACTIVE]
        if active:
            pool = active
        else:
            pool = [r for r in recordings
                    if r['status'] == RecordingStatus.STOPPED
                    and r['post_state'] not in PostState.OWNED_BY_WORDPRESS]
            if pool:
                newest = self._started(pool[0])
                pool = [r for r in pool if newest - self._started(r) <= self.SAME_OUTING]
        if not pool:
            return {'recording': None, 'candidates': []}

        # get_all_recordings is newest first, and sorted() keeps that order
        # among equals, so this is: default event first, then most recent
        pool = sorted(pool, key=lambda r: r.get('event_key') not in defaults)
        return {'recording': pool[0], 'candidates': pool}

    @staticmethod
    def _started(recording: Dict) -> datetime:
        value = recording['start_time']
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(str(value))

    # === Drafts (FR-24) ===

    def layout(self) -> str:
        """
        The layout a new draft starts from, and a recording with no draft
        publishes as: the ship's log (FR-25, approved 2026-10-09). The
        `post_layout` setting can put 'track_log' back.
        """
        name = self.database.get_setting('post_layout', post_renderer.DEFAULT_LAYOUT)
        return name if name in post_renderer.LAYOUTS else post_renderer.DEFAULT_LAYOUT

    def default_blocks(self) -> List[Dict]:
        return [dict(block) for block in post_renderer.LAYOUTS[self.layout()]]

    def get_draft(self, recording_id: int) -> Dict:
        """
        The recording's draft: the stored one, or what a new one would start
        as. `stored` says which. Nothing is written until the first edit.
        """
        recording = self._get(recording_id)
        draft = self.database.get_draft(recording_id)
        if draft:
            draft['stored'] = True
            return draft
        return {
            'title': recording['name'],
            'excerpt': recording.get('description') or '',
            'categories': ['Track Logs'],
            'crew': [],
            'story': '',
            'wind': '',
            'blocks': self.default_blocks(),
            'revision': 0,
            'stored': False,
        }

    def save_draft(self, recording_id: int, changes: Dict, base_revision: int) -> Dict:
        """
        Apply changes to the draft, if it is still at `base_revision`.

        Refused (409) when another save has happened since, and when
        WordPress already has the post (Q5). Unknown fields are refused
        (400), so a typo is an error rather than a change that vanishes.
        """
        self._check_draft_changes(recording_id, changes)

        draft = self.get_draft(recording_id)
        draft.update(changes)
        revision = self.database.save_draft(recording_id, draft, base_revision)
        if revision is None:
            current = self.get_draft(recording_id)
            raise RecordingError(
                f"The draft was changed elsewhere (now revision {current['revision']}, "
                f"this edit was based on {base_revision})", 409)
        return self.get_draft(recording_id)

    def save_draft_fields(self, recording_id: int, changes: Dict) -> Dict:
        """
        Save some fields from the event page (FR-27). Unlike save_draft there
        is no revision to match: each field keeps its own, so another
        device's edit of a different field is never undone, and the later of
        two edits of one field stands.
        """
        self._check_draft_changes(recording_id, changes)
        self.database.save_draft_fields(recording_id, self.get_draft(recording_id), changes)
        return self.get_draft(recording_id)

    def _check_draft_changes(self, recording_id: int, changes: Dict):
        recording = self._get(recording_id)
        if recording['post_state'] in PostState.OWNED_BY_WORDPRESS:
            raise RecordingError('Recording is already published; change the post in WordPress', 409)
        unknown = set(changes) - set(self.database.DRAFT_FIELDS)
        if unknown:
            raise RecordingError(f"Not draft fields: {', '.join(sorted(unknown))}", 400)
        for field in ('categories', 'crew', 'blocks'):
            if field in changes and not isinstance(changes[field], list):
                raise RecordingError(f"{field} must be a list", 400)
        for block in changes.get('blocks', []):
            if not isinstance(block, dict) or block.get('type') not in post_renderer.BLOCK_TYPES:
                raise RecordingError(f"Not a block: {block}", 400)

    # enchantee.org's categories as surveyed on 2026-10-09, for the event page
    # until FR-30 fetches the live list; offered in this order
    KNOWN_CATEGORIES = ["Ship's Log", "Track Logs", "Twilight", "Club event", "Rottnest",
                        "Dolphins", "Whales", "Maintenance", "No Sail", "Arduino"]

    def categories_available(self) -> List[str]:
        cached = self.database.get_setting('wp_categories')
        if cached:
            try:
                return json.loads(cached)
            except ValueError:
                pass
        return list(self.KNOWN_CATEGORIES)

    def crew_suggestions(self) -> List[str]:
        """Names from earlier drafts, the most often sailed first (FR-26)."""
        counts = {}
        for draft in self.database.get_all_drafts():
            for name in draft.get('crew') or []:
                counts[name] = counts.get(name, 0) + 1
        return sorted(counts, key=lambda name: (-counts[name], name.lower()))

    def page_state(self, recording_id: Optional[int],
                   media_url: Callable[[str], str]) -> Dict:
        """
        Everything the event page shows, in one answer, so a poll is one
        request. With no id, FR-28 chooses the recording.
        """
        choice = self.editor_choice()
        if recording_id:
            recording = self._get(recording_id)
        else:
            recording = choice['recording']
        if recording is None:
            return {'recording': None, 'candidates': []}
        rid = recording['id']

        draft = self.get_draft(rid)
        active = recording['status'] == RecordingStatus.ACTIVE
        timing = dict(recording)
        if active:
            timing['end_time'] = datetime.utcnow()
        photos = [{'image_id': img['id'], 'url': media_url(img['image_path']),
                   'caption': img.get('caption') or ''}
                  for img in self.database.get_recording_images(rid)
                  if img.get('image_type') == ImageType.USER_UPLOAD]

        candidates = choice['candidates']
        if all(c['id'] != rid for c in candidates):
            candidates = [recording] + candidates
        return {
            'recording': {key: recording.get(key) for key in (
                'id', 'name', 'status', 'stage', 'artefacts', 'post_state', 'post_error',
                'start_time', 'end_time', 'event_key', 'wordpress_url')},
            'elapsed_seconds': int((self._started_end(timing) - self._started(recording))
                                   .total_seconds()),
            'time_line': post_renderer.log_time_line(timing),
            'draft': draft,
            'photos': photos,
            'candidates': [{key: c.get(key) for key in ('id', 'name', 'status', 'start_time', 'event_key')}
                           for c in candidates],
            'categories_available': self.categories_available(),
            'crew_suggestions': self.crew_suggestions(),
            'publish_job': self.publish_job(rid),
            'can_publish': (bool(self.wordpress_publisher) and not active
                            and recording['post_state'] not in PostState.OWNED_BY_WORDPRESS),
        }

    def _started_end(self, recording: Dict) -> datetime:
        end = recording.get('end_time')
        if not end:
            return self._started(recording)
        return end if isinstance(end, datetime) else datetime.fromisoformat(str(end))

    def preview(self, recording_id: int, media_url: Callable[[str], str],
                layout: Optional[str] = None) -> str:
        """
        The post as it would be published, drawn by the same renderer from
        the same inputs, with image and download URLs on the Pi.

        Args:
            media_url: Turns a file path into the URL the Pi serves it at
            layout: Draw this layout instead of the draft's blocks, to
                compare (FR-25)
        """
        recording = self._get(recording_id)
        inputs = self._gather(recording_id)
        draft = self.get_draft(recording_id)
        if layout:
            if layout not in post_renderer.LAYOUTS:
                raise RecordingError(f"No layout '{layout}'", 400)
            blocks = post_renderer.LAYOUTS[layout]
        else:
            blocks = draft['blocks']

        media = [dict(img, url=media_url(img['path']), large_url=media_url(img['path']),
                      id=None) for img in inputs['images']]
        downloads = [{'url': media_url(exp['path']), 'label': exp['label'],
                      'export_type': exp['export_type']} for exp in inputs['exports']]
        ctx = post_renderer.PostContext(recording, media=media,
                                        statistics=inputs['statistics'],
                                        map_htmls=inputs['map_htmls'],
                                        downloads=downloads, draft=draft)
        return post_renderer.render(blocks, ctx)

    # === Helpers ===

    def _get(self, recording_id: int) -> Dict:
        recording = self.database.get_recording(recording_id)
        if not recording:
            raise RecordingError('Recording not found', 404)
        return recording
