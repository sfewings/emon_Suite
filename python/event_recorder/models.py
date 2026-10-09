"""
SQLite database models and schema for event recorder.

Provides database initialization, table creation, and data access methods
with power-outage resilience via WAL mode.
"""

import sqlite3
import json
import re
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from contextlib import contextmanager

logger = logging.getLogger(__name__)


class RecordingStatus:
    """
    The recording's own life, in `recordings.status` (TR-12).

    ACTIVE, STOPPED and FAILED are the only values written. FAILED means the
    recording itself failed (nothing was recorded), never that processing or
    publishing did: those are Artefacts.FAILED and PostState.PUBLISH_FAILED.

    PROCESSING, PROCESSED and PUBLISHED are what this one field used to say
    about the artefacts and the post as well. The table's CHECK constraint
    still allows them, and _split_status() rewrites any it finds, but nothing
    writes them now. They remain as the names of display stages (stage_of).
    """
    ACTIVE = 'active'
    STOPPED = 'stopped'
    PROCESSING = 'processing'
    PROCESSED = 'processed'
    PUBLISHED = 'published'
    FAILED = 'failed'


class Artefacts:
    """The plots, statistics and exports, in `recordings.artefacts` (TR-12)."""
    NONE = 'none'
    PROCESSING = 'processing'
    FRESH = 'fresh'
    # Processed, then the recording changed: more data after an early
    # process, or its times moved by the clock-step repair
    STALE = 'stale'
    FAILED = 'failed'


class PostState:
    """The WordPress post, in `post_drafts.post_state` (TR-12)."""
    NONE = 'none'
    PUBLISHING = 'publishing'
    WP_DRAFT = 'wp_draft'
    PUBLISHED = 'published'
    PUBLISH_FAILED = 'publish_failed'

    # WordPress owns the post in these, so the recording is locked (Q5)
    OWNED_BY_WORDPRESS = (WP_DRAFT, PUBLISHED)


def stage_of(recording: Dict) -> str:
    """
    One label for where a recording has got to, for lists and filters.

    Derived from the three states, never stored, so it cannot disagree with
    them. The values are the ones the single status field used to hold, plus
    'publishing', so the existing dashboard reads it unchanged.
    """
    post = recording.get('post_state') or PostState.NONE
    if recording['status'] == RecordingStatus.ACTIVE:
        return 'active'
    if recording['status'] == RecordingStatus.FAILED:
        return 'failed'
    if post == PostState.PUBLISHING:
        return 'publishing'
    if post in PostState.OWNED_BY_WORDPRESS:
        return 'published'
    if post == PostState.PUBLISH_FAILED:
        return 'failed'
    artefacts = recording.get('artefacts') or Artefacts.NONE
    if artefacts == Artefacts.PROCESSING:
        return 'processing'
    if artefacts in (Artefacts.FRESH, Artefacts.STALE):
        return 'processed'
    if artefacts == Artefacts.FAILED:
        return 'failed'
    return 'stopped'


class ImageType:
    """Image type constants."""
    PLOT = 'plot'
    USER_UPLOAD = 'user_upload'


class ExportType:
    """Export file type constants."""
    CSV = 'csv'
    KML = 'kml'
    GPX = 'gpx'


class Database:
    """SQLite database manager with WAL mode for crash resilience."""

    def __init__(self, db_path: str):
        """
        Initialize database connection.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # Initialize database if doesn't exist
        if not self.db_path.exists():
            logger.info(f"Creating new database at {self.db_path}")
            self.init_database()
        else:
            logger.info(f"Using existing database at {self.db_path}")
            self._migrate_database()

        # Enable WAL mode for crash resilience
        with self.get_connection() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")  # Faster writes, still safe
            logger.info("WAL mode enabled for crash resilience")

    @contextmanager
    def get_connection(self, foreign_keys: bool = True):
        """
        Context manager for database connections.

        Args:
            foreign_keys: Enforce foreign keys on this connection. SQLite
                ignores every REFERENCES and ON DELETE CASCADE in the schema
                unless each connection turns this on, which until TR-9 none
                did: deleting a recording left all of its data behind. Only
                migrations turn it off (see _migrate_database).

        Yields:
            sqlite3.Connection: Database connection

        Example:
            with db.get_connection() as conn:
                conn.execute(...)
        """
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row  # Enable column access by name
        if foreign_keys:
            conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Database error: {e}")
            raise
        finally:
            conn.close()

    def _migrate_database(self):
        """
        Apply schema migrations to existing databases.

        SQLite doesn't support ALTER TABLE to modify CHECK constraints, so
        migrations that change constraints require table recreation.

        Foreign keys are off for all of it. Recreating a table renames the old
        one and drops it, and with foreign keys on, the drop cascades:
        recreating `recordings` would delete every recording's data.

        Turning them off is not enough on its own. Since SQLite 3.26 a rename
        also rewrites the REFERENCES in every child table to the new name,
        whatever foreign_keys says, so the rename-and-drop left the children
        pointing at a table that no longer exists. Nothing noticed while
        foreign keys were never enforced; with them enforced, every insert into
        recording_data fails. legacy_alter_table stops the rewrite, and
        _repair_dangling_references() mends databases it already happened to.
        """
        with self.get_connection(foreign_keys=False) as conn:
            conn.execute("PRAGMA legacy_alter_table=ON")

            # Check if the recordings table CHECK constraint includes 'processed'
            cursor = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='recordings'"
            )
            row = cursor.fetchone()
            if row and "'processed'" not in row['sql']:
                logger.info("Migrating recordings table: adding 'processed' status")
                conn.execute("ALTER TABLE recordings RENAME TO recordings_old")
                conn.execute("""
                    CREATE TABLE recordings (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL,
                        description TEXT,
                        status TEXT NOT NULL CHECK(status IN ('active', 'stopped', 'processing', 'processed', 'published', 'failed')),
                        start_time TIMESTAMP NOT NULL,
                        end_time TIMESTAMP,
                        trigger_type TEXT,
                        wordpress_url TEXT,
                        error_message TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                conn.execute("INSERT INTO recordings SELECT * FROM recordings_old")
                conn.execute("DROP TABLE recordings_old")
                logger.info("Migration complete: recordings table updated")

            # Add service_settings table if missing
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='service_settings'"
            )
            if not cursor.fetchone():
                logger.info("Migrating: adding service_settings table")
                conn.execute("""
                    CREATE TABLE service_settings (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    )
                """)
                logger.info("Migration complete: service_settings table added")

            # Add recording_exports table if missing
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='recording_exports'"
            )
            if not cursor.fetchone():
                logger.info("Migrating: adding recording_exports table")
                conn.execute("""
                    CREATE TABLE recording_exports (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        recording_id INTEGER NOT NULL,
                        export_type TEXT NOT NULL CHECK(export_type IN ('csv', 'kml', 'gpx')),
                        file_path TEXT NOT NULL UNIQUE,
                        label TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (recording_id) REFERENCES recordings(id) ON DELETE CASCADE
                    )
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_recording_exports_recording_id
                    ON recording_exports(recording_id)
                """)
                logger.info("Migration complete: recording_exports table added")

            self._repair_dangling_references(conn)

            # Add post_drafts table if missing (TR-11)
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='post_drafts'"
            )
            if not cursor.fetchone():
                logger.info("Migrating: adding post_drafts table")
                conn.execute(self.POST_DRAFTS_SQL)

            self._split_status(conn)
            self._add_event_key(conn)

            # Rows left behind by deletes made before foreign keys were
            # enforced. Done once: it scans recording_data, which is the bulk
            # of the file on the Pi's SD card.
            cursor = conn.execute(
                "SELECT value FROM service_settings WHERE key = 'orphans_removed'"
            )
            if not cursor.fetchone():
                for table in ('recording_data', 'recording_images', 'recording_exports'):
                    removed = conn.execute(f"""
                        DELETE FROM {table}
                        WHERE recording_id NOT IN (SELECT id FROM recordings)
                    """).rowcount
                    if removed:
                        logger.info(f"Migration: removed {removed} orphaned {table} rows")
                conn.execute(
                    "INSERT INTO service_settings (key, value) VALUES ('orphans_removed', ?)",
                    (datetime.utcnow().isoformat(),)
                )

    # One row per recording that has been, or is going to be, a post. TR-11
    # needs only the WordPress side: which post it is, and when WordPress last
    # changed it, so a republish updates that post rather than making another,
    # and refuses to overwrite edits made in wp-admin since. FR-24 adds the
    # draft itself to this table.
    POST_DRAFTS_SQL = """
        CREATE TABLE IF NOT EXISTS post_drafts (
            recording_id INTEGER PRIMARY KEY,
            wp_post_id INTEGER,
            wp_modified TEXT,
            wp_status TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (recording_id) REFERENCES recordings(id) ON DELETE CASCADE
        )
    """

    def _split_status(self, conn):
        """
        TR-12: give the artefacts and the post states of their own, and move
        what the single status said about them into those.

        Columns are added rather than the table rebuilt, so the old status
        values stay allowed by its CHECK constraint; they are rewritten here
        and nothing writes them again. Runs on every start and does nothing
        once there is nothing left to move.
        """
        def columns(table):
            return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}

        if 'artefacts' not in columns('recordings'):
            logger.info("Migrating: adding recordings.artefacts and processed_at")
            conn.execute("ALTER TABLE recordings ADD COLUMN artefacts TEXT NOT NULL DEFAULT 'none'")
            conn.execute("ALTER TABLE recordings ADD COLUMN processed_at TIMESTAMP")
        if 'post_state' not in columns('post_drafts'):
            logger.info("Migrating: adding post_drafts.post_state and post_error")
            conn.execute("ALTER TABLE post_drafts ADD COLUMN post_state TEXT NOT NULL DEFAULT 'none'")
            conn.execute("ALTER TABLE post_drafts ADD COLUMN post_error TEXT")

        # FR-24: the draft itself. JSON in TEXT for the lists. `revision`
        # counts saves, so a save based on an older one can be refused
        # rather than silently undo another device's edit.
        if 'blocks' not in columns('post_drafts'):
            logger.info("Migrating: adding the draft to post_drafts")
            for column in ("title TEXT", "excerpt TEXT", "categories TEXT", "crew TEXT",
                           "story TEXT", "wind TEXT", "blocks TEXT",
                           "revision INTEGER NOT NULL DEFAULT 0"):
                conn.execute(f"ALTER TABLE post_drafts ADD COLUMN {column}")

        # FR-27: the revision at which each field last changed, JSON
        # {field: revision}, so the event page can save one field without
        # disturbing another device's edit of a different one
        if 'field_revisions' not in columns('post_drafts'):
            conn.execute("ALTER TABLE post_drafts ADD COLUMN field_revisions TEXT")

        def set_post_state(where, state, error_sql='NULL'):
            conn.execute(f"""
                INSERT INTO post_drafts (recording_id, post_state, post_error)
                SELECT id, '{state}', {error_sql} FROM recordings WHERE {where}
                ON CONFLICT(recording_id) DO UPDATE SET
                    post_state = excluded.post_state, post_error = excluded.post_error
            """)

        # A post id stored by TR-11 with no state yet: that post is out
        untracked = """wp_post_id IS NOT NULL AND post_state = 'none'"""

        moved = conn.execute("""
            SELECT COUNT(*) FROM recordings
            WHERE status IN ('processing', 'processed', 'published')
               OR (status = 'failed' AND COALESCE(error_message, '') NOT LIKE 'No data recorded%')
        """).fetchone()[0] + conn.execute(
            f"SELECT COUNT(*) FROM post_drafts WHERE {untracked}").fetchone()[0]
        if not moved:
            return
        logger.info(f"Migrating: splitting the status of {moved} recordings")

        conn.execute(f"""
            UPDATE post_drafts SET post_state = CASE
                WHEN wp_status IN ('draft', 'pending') THEN '{PostState.WP_DRAFT}'
                ELSE '{PostState.PUBLISHED}' END
            WHERE {untracked}
        """)

        # A post that went out: processed, and published. 'processed' with a
        # link is one too: the old way to republish, or add a photo to a
        # published recording, was to reset it to processed first.
        set_post_state("status = 'published'", PostState.PUBLISHED)
        set_post_state("""status = 'processed' AND wordpress_url IS NOT NULL
                          AND id NOT IN (SELECT recording_id FROM post_drafts
                                         WHERE post_state != 'none')""",
                       PostState.PUBLISHED)
        conn.execute(f"""UPDATE recordings SET status = 'stopped', artefacts = '{Artefacts.FRESH}'
                         WHERE status = 'published'""")

        conn.execute(f"""UPDATE recordings SET status = 'stopped', artefacts = '{Artefacts.FRESH}'
                         WHERE status = 'processed'""")

        # Processing that was interrupted: as if never started
        conn.execute(f"""UPDATE recordings SET status = 'stopped', artefacts = '{Artefacts.NONE}'
                         WHERE status = 'processing'""")

        # 'failed' meant three things. A publish that failed was processed
        # first; the message the publisher left says which one it was.
        publish_failed = "status = 'failed' AND error_message LIKE '%WordPress%'"
        set_post_state(publish_failed, PostState.PUBLISH_FAILED, 'error_message')
        conn.execute(f"""UPDATE recordings SET status = 'stopped', artefacts = '{Artefacts.FRESH}'
                         WHERE {publish_failed}""")

        # Only a recording with nothing in it failed as a recording (recovery
        # says so in those words). Any other failure was processing's.
        conn.execute(f"""UPDATE recordings SET status = 'stopped', artefacts = '{Artefacts.FAILED}'
                         WHERE status = 'failed'
                           AND COALESCE(error_message, '') NOT LIKE 'No data recorded%'""")

    def _add_event_key(self, conn):
        """
        FR-28: which event started a recording, as its key in the event
        config ('anchor_track_recording'), or 'manual'.

        Recordings made before this have it only as the start of their name,
        "anchor_track_recording - 2026-10-07 18:03:28", so they are filled in
        from that once, when the column is added. Nothing reads the name for
        it afterwards: the name is the post title, which the crew now edit.
        """
        columns = {row[1] for row in conn.execute("PRAGMA table_info(recordings)")}
        if 'event_key' in columns:
            return
        logger.info("Migrating: adding recordings.event_key")
        conn.execute("ALTER TABLE recordings ADD COLUMN event_key TEXT")
        for row in conn.execute("SELECT id, name, trigger_type FROM recordings").fetchall():
            if row['trigger_type'] == 'manual':
                key = 'manual'
            else:
                match = re.match(r'([a-z0-9_]+) - \d{4}-\d{2}-\d{2}', row['name'] or '')
                key = match.group(1) if match else None
            if key:
                conn.execute("UPDATE recordings SET event_key = ? WHERE id = ?", (key, row['id']))

    DANGLING_REFERENCE = 'REFERENCES "recordings_old"'

    def _repair_dangling_references(self, conn):
        """
        Point child tables back at `recordings` after the 'processed'
        migration repointed them at the `recordings_old` it then dropped.

        Only the text of the constraint is wrong; the rows are fine. So this
        edits the stored CREATE TABLE statements in place, the way SQLite's
        documentation describes for changing a constraint, rather than copying
        recording_data, which on the Pi is most of the file. The schema
        version is bumped so the change is reread, and the database is
        checked before the transaction is allowed to commit.
        """
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND sql LIKE ?",
            (f'%{self.DANGLING_REFERENCE}%',)
        ).fetchall()
        if not rows:
            return
        tables = [row['name'] for row in rows]
        logger.warning(
            f"Repairing foreign keys left pointing at the dropped recordings_old: "
            f"{', '.join(tables)}"
        )

        version = conn.execute("PRAGMA schema_version").fetchone()[0]
        conn.execute("PRAGMA writable_schema=ON")
        conn.execute(
            f"""UPDATE sqlite_master SET sql = replace(sql, ?, 'REFERENCES recordings')
                WHERE type='table' AND name IN ({','.join('?' * len(tables))})""",
            (self.DANGLING_REFERENCE, *tables)
        )
        conn.execute(f"PRAGMA schema_version={version + 1}")
        conn.execute("PRAGMA writable_schema=OFF")

        result = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if result != 'ok':
            raise sqlite3.DatabaseError(f"integrity check after repair: {result}")
        logger.info("Foreign key repair complete")

    def init_database(self):
        """Create database schema with all tables and indexes."""
        with self.get_connection() as conn:
            # Recordings table - session metadata
            conn.execute("""
                CREATE TABLE IF NOT EXISTS recordings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    description TEXT,
                    status TEXT NOT NULL CHECK(status IN ('active', 'stopped', 'processing', 'processed', 'published', 'failed')),
                    start_time TIMESTAMP NOT NULL,
                    end_time TIMESTAMP,
                    trigger_type TEXT,
                    wordpress_url TEXT,
                    error_message TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Recording data table - MQTT messages
            conn.execute("""
                CREATE TABLE IF NOT EXISTS recording_data (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    recording_id INTEGER NOT NULL,
                    timestamp TIMESTAMP NOT NULL,
                    topic TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    FOREIGN KEY (recording_id) REFERENCES recordings(id) ON DELETE CASCADE
                )
            """)

            # Indexes for performance
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_recording_data_recording_id
                ON recording_data(recording_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_recording_data_timestamp
                ON recording_data(timestamp)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_recording_data_topic
                ON recording_data(topic)
            """)

            # Recording images table - plots and uploads
            conn.execute("""
                CREATE TABLE IF NOT EXISTS recording_images (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    recording_id INTEGER NOT NULL,
                    image_path TEXT NOT NULL,
                    image_type TEXT NOT NULL CHECK(image_type IN ('plot', 'user_upload')),
                    caption TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (recording_id) REFERENCES recordings(id) ON DELETE CASCADE
                )
            """)

            # Recording exports table - CSV, KML, GPX download files
            conn.execute("""
                CREATE TABLE IF NOT EXISTS recording_exports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    recording_id INTEGER NOT NULL,
                    export_type TEXT NOT NULL CHECK(export_type IN ('csv', 'kml', 'gpx')),
                    file_path TEXT NOT NULL UNIQUE,
                    label TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (recording_id) REFERENCES recordings(id) ON DELETE CASCADE
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_recording_exports_recording_id
                ON recording_exports(recording_id)
            """)

            # Configurations table - event trigger definitions
            conn.execute("""
                CREATE TABLE IF NOT EXISTS configurations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    monitor_topics TEXT NOT NULL,
                    start_condition TEXT NOT NULL,
                    stop_condition TEXT NOT NULL,
                    record_topics TEXT NOT NULL,
                    plot_config TEXT,
                    wordpress_site TEXT,
                    auto_publish BOOLEAN DEFAULT 1,
                    enabled BOOLEAN DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Service settings table - key/value store for runtime settings
            conn.execute("""
                CREATE TABLE IF NOT EXISTS service_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)

            conn.execute(self.POST_DRAFTS_SQL)
            self._split_status(conn)
            self._add_event_key(conn)

            logger.info("Database schema created successfully")

    # === Recording Operations ===

    def create_recording(self, name: str, description: str = "",
                        trigger_type: str = "gps_movement",
                        event_key: str = None) -> int:
        """
        Create a new recording session.

        Args:
            name: Recording name
            description: Optional description
            trigger_type: Type of trigger (default: gps_movement)
            event_key: The event config key that started it, or 'manual' (FR-28)

        Returns:
            int: Recording ID
        """
        with self.get_connection() as conn:
            cursor = conn.execute("""
                INSERT INTO recordings (name, description, status, start_time, trigger_type, event_key)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (name, description, RecordingStatus.ACTIVE, datetime.utcnow(), trigger_type,
                  event_key))
            recording_id = cursor.lastrowid
            logger.info(f"Created recording {recording_id}: {name}")
            return recording_id

    def update_recording(self, recording_id: int, **kwargs):
        """
        Update recording fields.

        Args:
            recording_id: Recording ID
            **kwargs: Fields to update (status, end_time, name, description, etc.)
        """
        if not kwargs:
            return

        # Build dynamic UPDATE query
        set_clauses = []
        values = []
        for key, value in kwargs.items():
            set_clauses.append(f"{key} = ?")
            values.append(value)

        # Always update updated_at
        set_clauses.append("updated_at = ?")
        values.append(datetime.utcnow())

        values.append(recording_id)  # For WHERE clause

        query = f"""
            UPDATE recordings
            SET {', '.join(set_clauses)}
            WHERE id = ?
        """

        with self.get_connection() as conn:
            conn.execute(query, values)
            logger.info(f"Updated recording {recording_id}: {kwargs}")

    # A recording with its post's state beside it, so a reader has all three
    # of TR-12's states in one row, and the stage derived from them
    RECORDING_SELECT = """
        SELECT r.*, COALESCE(d.post_state, 'none') AS post_state,
               d.post_error, d.wp_post_id
        FROM recordings r LEFT JOIN post_drafts d ON d.recording_id = r.id
    """

    @staticmethod
    def _recording(row) -> Dict:
        recording = dict(row)
        recording['stage'] = stage_of(recording)
        return recording

    def get_recording(self, recording_id: int) -> Optional[Dict]:
        """
        Get recording by ID.

        Args:
            recording_id: Recording ID

        Returns:
            Dict with recording data or None if not found
        """
        with self.get_connection() as conn:
            cursor = conn.execute(
                self.RECORDING_SELECT + " WHERE r.id = ?", (recording_id,))
            row = cursor.fetchone()
            return self._recording(row) if row else None

    def get_recordings_by_status(self, status: str) -> List[Dict]:
        """
        Get all recordings with specified status.

        Args:
            status: Recording status (active, stopped, processing, published, failed)

        Returns:
            List of recording dicts
        """
        with self.get_connection() as conn:
            cursor = conn.execute(
                self.RECORDING_SELECT + " WHERE r.status = ? ORDER BY r.start_time DESC",
                (status,))
            return [self._recording(row) for row in cursor.fetchall()]

    def get_all_recordings(self, limit: int = 100, offset: int = 0) -> List[Dict]:
        """
        Get all recordings with pagination.

        Args:
            limit: Maximum number of recordings to return
            offset: Number of recordings to skip

        Returns:
            List of recording dicts
        """
        with self.get_connection() as conn:
            cursor = conn.execute(
                self.RECORDING_SELECT + " ORDER BY r.start_time DESC LIMIT ? OFFSET ?",
                (limit, offset))
            return [self._recording(row) for row in cursor.fetchall()]

    def delete_recording(self, recording_id: int):
        """
        Delete recording and all associated data (cascades).

        Args:
            recording_id: Recording ID
        """
        with self.get_connection() as conn:
            conn.execute("DELETE FROM recordings WHERE id = ?", (recording_id,))
            logger.info(f"Deleted recording {recording_id}")

    # === Recording Data Operations ===

    def add_message(self, recording_id: int, topic: str, payload: str,
                   timestamp: datetime = None):
        """
        Add single MQTT message to recording.

        Args:
            recording_id: Recording ID
            topic: MQTT topic
            payload: Message payload (string)
            timestamp: Message timestamp (default: now)
        """
        if timestamp is None:
            timestamp = datetime.utcnow()

        with self.get_connection() as conn:
            conn.execute("""
                INSERT INTO recording_data (recording_id, timestamp, topic, payload)
                VALUES (?, ?, ?, ?)
            """, (recording_id, timestamp, topic, payload))

    def add_messages_batch(self, messages: List[Tuple[int, datetime, str, str]]):
        """
        Add multiple MQTT messages in batch (for performance).

        Args:
            messages: List of tuples (recording_id, timestamp, topic, payload)
        """
        if not messages:
            return
        with self.get_connection() as conn:
            # Rows for a recording that no longer exists are dropped rather
            # than allowed to fail the batch. The buffer keeps a failed batch
            # and retries it, so one such row would block every recording's
            # data from then on.
            ids = {m[0] for m in messages}
            existing = {row[0] for row in conn.execute(
                f"SELECT id FROM recordings WHERE id IN ({','.join('?' * len(ids))})",
                tuple(ids)
            )}
            if existing != ids:
                logger.warning(
                    f"Dropping buffered messages for deleted recording(s) "
                    f"{sorted(ids - existing)}"
                )
                messages = [m for m in messages if m[0] in existing]
            conn.executemany("""
                INSERT INTO recording_data (recording_id, timestamp, topic, payload)
                VALUES (?, ?, ?, ?)
            """, messages)

    def get_recording_data(self, recording_id: int, topic_filter: str = None,
                          limit: int = None) -> List[Dict]:
        """
        Get recorded data for a recording session.

        Args:
            recording_id: Recording ID
            topic_filter: Optional MQTT topic filter (SQL LIKE pattern)
            limit: Optional limit on number of records

        Returns:
            List of data records
        """
        query = """
            SELECT timestamp, topic, payload
            FROM recording_data
            WHERE recording_id = ?
        """
        params = [recording_id]

        if topic_filter:
            query += " AND topic LIKE ?"
            params.append(topic_filter)

        query += " ORDER BY timestamp ASC"

        if limit:
            query += f" LIMIT {limit}"

        with self.get_connection() as conn:
            cursor = conn.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def get_recording_data_count(self, recording_id: int) -> int:
        """
        Get count of messages in recording.

        Args:
            recording_id: Recording ID

        Returns:
            int: Message count
        """
        with self.get_connection() as conn:
            cursor = conn.execute("""
                SELECT COUNT(*) as count
                FROM recording_data
                WHERE recording_id = ?
            """, (recording_id,))
            return cursor.fetchone()['count']

    def get_recording_photo_count(self, recording_id: int) -> int:
        """Count user-uploaded photos for a recording."""
        with self.get_connection() as conn:
            cursor = conn.execute("""
                SELECT COUNT(*) as count
                FROM recording_images
                WHERE recording_id = ? AND image_type = 'user_upload'
            """, (recording_id,))
            return cursor.fetchone()['count']

    def get_recording_topics(self, recording_id: int) -> List[str]:
        """
        Get list of unique topics in recording.

        Args:
            recording_id: Recording ID

        Returns:
            List of topic names
        """
        with self.get_connection() as conn:
            cursor = conn.execute("""
                SELECT DISTINCT topic
                FROM recording_data
                WHERE recording_id = ?
                ORDER BY topic
            """, (recording_id,))
            return [row['topic'] for row in cursor.fetchall()]

    # === Image Operations ===

    def add_image(self, recording_id: int, image_path: str,
                 image_type: str = ImageType.PLOT, caption: str = None) -> int:
        """
        Add image to recording.

        Args:
            recording_id: Recording ID
            image_path: Path to image file
            image_type: 'plot' or 'user_upload'
            caption: Optional caption

        Returns:
            int: Image ID
        """
        with self.get_connection() as conn:
            cursor = conn.execute("""
                INSERT INTO recording_images (recording_id, image_path, image_type, caption)
                VALUES (?, ?, ?, ?)
            """, (recording_id, image_path, image_type, caption))
            return cursor.lastrowid

    def get_recording_images(self, recording_id: int) -> List[Dict]:
        """
        Get all images for recording.

        Args:
            recording_id: Recording ID

        Returns:
            List of image dicts
        """
        with self.get_connection() as conn:
            cursor = conn.execute("""
                SELECT * FROM recording_images
                WHERE recording_id = ?
                ORDER BY created_at
            """, (recording_id,))
            return [dict(row) for row in cursor.fetchall()]

    def delete_image(self, image_id: int):
        """
        Delete image record.

        Args:
            image_id: Image ID
        """
        with self.get_connection() as conn:
            conn.execute("DELETE FROM recording_images WHERE id = ?", (image_id,))

    def shift_recording_times(self, recording_id: int, delta_seconds: float) -> int:
        """
        Move every timestamp of one recording by a fixed amount.

        For repairing a recording made while the clock was wrong. The boat can
        be under way before the GPS gets its first fix, so a recording can
        start on a clock that is months out and still be running when the fix
        arrives and the clock steps to the truth. Shifting what was already
        written by the size of that step leaves the whole recording on one
        timescale, rather than half in each.

        The shift is done here rather than in SQL because SQLite's date
        functions round to milliseconds, and these timestamps carry
        microseconds.

        Args:
            recording_id: Recording to move
            delta_seconds: Seconds to add, as measured by the clock step

        Returns:
            int: Number of data rows moved
        """
        delta = timedelta(seconds=delta_seconds)

        def shifted(value):
            if not value:
                return value
            return (datetime.fromisoformat(str(value)) + delta).isoformat(sep=' ')

        with self.get_connection() as conn:
            row = conn.execute(
                "SELECT start_time, end_time FROM recordings WHERE id = ?",
                (recording_id,)
            ).fetchone()
            if row is None:
                return 0

            conn.execute(
                "UPDATE recordings SET start_time = ?, end_time = ? WHERE id = ?",
                (shifted(row['start_time']), shifted(row['end_time']), recording_id)
            )

            data = conn.execute(
                "SELECT id, timestamp FROM recording_data WHERE recording_id = ?",
                (recording_id,)
            ).fetchall()
            conn.executemany(
                "UPDATE recording_data SET timestamp = ? WHERE id = ?",
                [(shifted(r['timestamp']), r['id']) for r in data]
            )

            # Plots drawn before the move carry the old times
            conn.execute(
                f"UPDATE recordings SET artefacts = '{Artefacts.STALE}' "
                f"WHERE id = ? AND artefacts = '{Artefacts.FRESH}'",
                (recording_id,)
            )

            return len(data)

    def delete_plot_images(self, recording_id: int) -> int:
        """
        Delete the generated-plot image records for a recording.

        User uploads are left alone: they are the crew's photos, not something
        processing can recreate.

        Args:
            recording_id: Recording ID

        Returns:
            int: Number of rows deleted
        """
        with self.get_connection() as conn:
            cursor = conn.execute("""
                DELETE FROM recording_images
                WHERE recording_id = ? AND image_type = ?
            """, (recording_id, ImageType.PLOT))
            return cursor.rowcount

    # === Export Operations ===

    def add_export(self, recording_id: int, export_type: str,
                   file_path: str, label: str = None) -> int:
        """
        Register an export file for a recording.

        Uses INSERT OR IGNORE so re-processing is idempotent (UNIQUE on file_path).

        Args:
            recording_id: Recording ID
            export_type: 'csv', 'kml', or 'gpx'
            file_path: Absolute path to the file on disk
            label: Human-readable label

        Returns:
            int: Export record ID (0 if row already existed)
        """
        with self.get_connection() as conn:
            cursor = conn.execute("""
                INSERT OR IGNORE INTO recording_exports
                    (recording_id, export_type, file_path, label)
                VALUES (?, ?, ?, ?)
            """, (recording_id, export_type, file_path, label))
            return cursor.lastrowid

    def delete_recording_exports(self, recording_id: int) -> int:
        """
        Delete the export records for a recording (the files on disk are left).

        Args:
            recording_id: Recording ID

        Returns:
            int: Number of rows deleted
        """
        with self.get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM recording_exports WHERE recording_id = ?",
                (recording_id,)
            )
            return cursor.rowcount

    def get_recording_exports(self, recording_id: int) -> List[Dict]:
        """
        Get all export files for a recording.

        Args:
            recording_id: Recording ID

        Returns:
            List of export dicts
        """
        with self.get_connection() as conn:
            cursor = conn.execute("""
                SELECT * FROM recording_exports
                WHERE recording_id = ?
                ORDER BY export_type, created_at
            """, (recording_id,))
            return [dict(row) for row in cursor.fetchall()]

    def delete_export(self, export_id: int):
        """Delete export record (does not delete the file on disk)."""
        with self.get_connection() as conn:
            conn.execute("DELETE FROM recording_exports WHERE id = ?", (export_id,))

    # === Post Draft Operations ===

    def get_post_draft(self, recording_id: int) -> Optional[Dict]:
        """The recording's post_drafts row, or None if it has never been a post."""
        with self.get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM post_drafts WHERE recording_id = ?", (recording_id,)
            ).fetchone()
            return dict(row) if row else None

    def save_post_ref(self, recording_id: int, wp_post_id: int,
                      wp_modified: str, wp_status: str):
        """Record which WordPress post a recording is, as WordPress last left it."""
        with self.get_connection() as conn:
            conn.execute("""
                INSERT INTO post_drafts (recording_id, wp_post_id, wp_modified, wp_status, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(recording_id) DO UPDATE SET
                    wp_post_id = excluded.wp_post_id,
                    wp_modified = excluded.wp_modified,
                    wp_status = excluded.wp_status,
                    updated_at = excluded.updated_at
            """, (recording_id, wp_post_id, wp_modified, wp_status, datetime.utcnow()))

    DRAFT_FIELDS = ('title', 'excerpt', 'categories', 'crew', 'story', 'wind', 'blocks')
    DRAFT_JSON_FIELDS = ('categories', 'crew', 'blocks')

    def get_draft(self, recording_id: int) -> Optional[Dict]:
        """The stored draft (FR-24), lists decoded, or None if never saved."""
        ref = self.get_post_draft(recording_id)
        if not ref or ref.get('blocks') is None:
            return None
        draft = {field: ref.get(field) for field in self.DRAFT_FIELDS}
        for field in self.DRAFT_JSON_FIELDS:
            draft[field] = json.loads(draft[field]) if draft[field] else []
        draft['revision'] = ref['revision']
        draft['field_revisions'] = json.loads(ref['field_revisions']) if ref.get('field_revisions') else {}
        return draft

    def get_all_drafts(self) -> List[Dict]:
        """Every stored draft, for what the crew have written before (FR-26, FR-30)."""
        with self.get_connection() as conn:
            ids = [row[0] for row in conn.execute(
                "SELECT recording_id FROM post_drafts WHERE blocks IS NOT NULL")]
        return [self.get_draft(rid) for rid in ids]

    def save_draft_fields(self, recording_id: int, start: Dict, changes: Dict) -> int:
        """
        Change some fields of a draft, whoever else has changed others (FR-27).

        The event page saves one field at a time from more than one device.
        Each field records the revision it last changed at; a save touches
        only its own fields, so the phone's title and the iPad's story never
        undo each other. Two saves of the same field: the later one stands,
        and the field's revision tells the other device it was overtaken.

        Args:
            start: The whole draft to begin from if none is stored yet
            changes: {field: value}, draft fields only

        Returns:
            The draft's new revision
        """
        with self.get_connection() as conn:
            # The write lock before the read: two saves at once would
            # otherwise both read revision n and both write n + 1
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT blocks, revision, field_revisions FROM post_drafts WHERE recording_id = ?",
                (recording_id,)).fetchone()
            if row is None or row['blocks'] is None:
                conn.execute("INSERT OR IGNORE INTO post_drafts (recording_id) VALUES (?)",
                             (recording_id,))
                fields = dict(start, **changes)
                revisions = {}
                revision = (row['revision'] if row else 0) + 1
            else:
                fields = dict(changes)
                revisions = json.loads(row['field_revisions']) if row['field_revisions'] else {}
                revision = row['revision'] + 1
            for field in changes:
                revisions[field] = revision

            names = [f for f in self.DRAFT_FIELDS if f in fields]
            values = [json.dumps(fields[f] or []) if f in self.DRAFT_JSON_FIELDS else fields[f]
                      for f in names]
            sets = ''.join(f"{f} = ?, " for f in names)
            conn.execute(
                f"""UPDATE post_drafts SET {sets}revision = ?, field_revisions = ?, updated_at = ?
                    WHERE recording_id = ?""",
                (*values, revision, json.dumps(revisions), datetime.utcnow(), recording_id))
            return revision

    def save_draft(self, recording_id: int, draft: Dict, base_revision: int) -> Optional[int]:
        """
        Store a whole draft, if nobody has saved since `base_revision`.

        Returns the new revision, or None when the stored draft has moved on,
        in which case nothing is written. The check and the write are one
        statement, so two devices saving at once cannot both win.
        """
        values = [json.dumps(draft.get(f) or []) if f in self.DRAFT_JSON_FIELDS
                  else draft.get(f) for f in self.DRAFT_FIELDS]
        with self.get_connection() as conn:
            conn.execute("INSERT OR IGNORE INTO post_drafts (recording_id) VALUES (?)",
                         (recording_id,))
            sets = ', '.join(f"{f} = ?" for f in self.DRAFT_FIELDS)
            changed = conn.execute(
                f"""UPDATE post_drafts SET {sets}, revision = revision + 1, updated_at = ?
                    WHERE recording_id = ? AND revision = ?""",
                (*values, datetime.utcnow(), recording_id, base_revision)
            ).rowcount
            if not changed:
                return None
            return conn.execute("SELECT revision FROM post_drafts WHERE recording_id = ?",
                                (recording_id,)).fetchone()[0]

    def set_post_state(self, recording_id: int, state: str, error: str = None):
        """Set where the recording's post has got to (TR-12), with the error if it failed."""
        with self.get_connection() as conn:
            conn.execute("""
                INSERT INTO post_drafts (recording_id, post_state, post_error, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(recording_id) DO UPDATE SET
                    post_state = excluded.post_state,
                    post_error = excluded.post_error,
                    updated_at = excluded.updated_at
            """, (recording_id, state, error, datetime.utcnow()))

    # === Service Settings Operations ===

    def get_setting(self, key: str, default: str = None) -> Optional[str]:
        """Get a service setting value by key."""
        with self.get_connection() as conn:
            cursor = conn.execute(
                "SELECT value FROM service_settings WHERE key = ?", (key,)
            )
            row = cursor.fetchone()
            return row['value'] if row else default

    def set_setting(self, key: str, value: str):
        """Set a service setting value (insert or replace)."""
        with self.get_connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO service_settings (key, value) VALUES (?, ?)",
                (key, value)
            )

    # === Configuration Operations ===

    def create_configuration(self, name: str, monitor_topics: List[str],
                            start_condition: Dict, stop_condition: Dict,
                            record_topics: List[str], plot_config: Dict = None,
                            wordpress_site: str = "default_site",
                            auto_publish: bool = False, enabled: bool = True) -> int:
        """
        Create event configuration.

        Args:
            name: Configuration name
            monitor_topics: Topics to monitor for triggers
            start_condition: Start condition dict
            stop_condition: Stop condition dict
            record_topics: Topics to record
            plot_config: Plot configuration dict
            wordpress_site: WordPress site identifier
            auto_publish: Auto-publish to WordPress
            enabled: Configuration enabled

        Returns:
            int: Configuration ID
        """
        with self.get_connection() as conn:
            cursor = conn.execute("""
                INSERT INTO configurations
                (name, monitor_topics, start_condition, stop_condition,
                 record_topics, plot_config, wordpress_site, auto_publish, enabled)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                name,
                json.dumps(monitor_topics),
                json.dumps(start_condition),
                json.dumps(stop_condition),
                json.dumps(record_topics),
                json.dumps(plot_config) if plot_config else None,
                wordpress_site,
                auto_publish,
                enabled
            ))
            return cursor.lastrowid

    def get_configuration(self, config_id: int) -> Optional[Dict]:
        """
        Get configuration by ID with JSON parsing.

        Args:
            config_id: Configuration ID

        Returns:
            Dict with configuration data or None
        """
        with self.get_connection() as conn:
            cursor = conn.execute("SELECT * FROM configurations WHERE id = ?", (config_id,))
            row = cursor.fetchone()
            if not row:
                return None

            config = dict(row)
            # Parse JSON fields
            config['monitor_topics'] = json.loads(config['monitor_topics'])
            config['start_condition'] = json.loads(config['start_condition'])
            config['stop_condition'] = json.loads(config['stop_condition'])
            config['record_topics'] = json.loads(config['record_topics'])
            if config['plot_config']:
                config['plot_config'] = json.loads(config['plot_config'])
            return config

    def get_enabled_configurations(self) -> List[Dict]:
        """
        Get all enabled configurations.

        Returns:
            List of configuration dicts with parsed JSON
        """
        with self.get_connection() as conn:
            cursor = conn.execute("""
                SELECT * FROM configurations
                WHERE enabled = 1
                ORDER BY name
            """)
            configs = []
            for row in cursor.fetchall():
                config = dict(row)
                config['monitor_topics'] = json.loads(config['monitor_topics'])
                config['start_condition'] = json.loads(config['start_condition'])
                config['stop_condition'] = json.loads(config['stop_condition'])
                config['record_topics'] = json.loads(config['record_topics'])
                if config['plot_config']:
                    config['plot_config'] = json.loads(config['plot_config'])
                configs.append(config)
            return configs

    def update_configuration(self, config_id: int, **kwargs):
        """
        Update configuration fields.

        Args:
            config_id: Configuration ID
            **kwargs: Fields to update

        Note: JSON fields (lists/dicts) are automatically serialized
        """
        if not kwargs:
            return

        # JSON fields that need serialization
        json_fields = {'monitor_topics', 'start_condition', 'stop_condition',
                      'record_topics', 'plot_config'}

        set_clauses = []
        values = []
        for key, value in kwargs.items():
            if key in json_fields and value is not None:
                value = json.dumps(value)
            set_clauses.append(f"{key} = ?")
            values.append(value)

        set_clauses.append("updated_at = ?")
        values.append(datetime.utcnow())
        values.append(config_id)

        query = f"""
            UPDATE configurations
            SET {', '.join(set_clauses)}
            WHERE id = ?
        """

        with self.get_connection() as conn:
            conn.execute(query, values)

    def delete_configuration(self, config_id: int):
        """
        Delete configuration.

        Args:
            config_id: Configuration ID
        """
        with self.get_connection() as conn:
            conn.execute("DELETE FROM configurations WHERE id = ?", (config_id,))

    # === Utility Methods ===

    def get_database_stats(self) -> Dict:
        """
        Get database statistics.

        Returns:
            Dict with table counts and database size
        """
        stats = {}

        with self.get_connection() as conn:
            # Table counts
            for table in ['recordings', 'recording_data', 'recording_images', 'configurations']:
                cursor = conn.execute(f"SELECT COUNT(*) as count FROM {table}")
                stats[f'{table}_count'] = cursor.fetchone()['count']

            # Database size
            stats['database_size_mb'] = self.db_path.stat().st_size / (1024 * 1024)

        return stats


def main():
    """
    CLI for database operations.

    Usage:
        python models.py --init-db [db_path]
        python models.py --stats [db_path]
    """
    import argparse

    parser = argparse.ArgumentParser(description="Event Recorder Database Management")
    parser.add_argument('--init-db', action='store_true', help="Initialize database")
    parser.add_argument('--stats', action='store_true', help="Show database statistics")
    parser.add_argument('--db-path', default="/data/recordings.db", help="Database path")

    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(level=logging.INFO,
                       format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    db = Database(args.db_path)

    if args.init_db:
        print(f"Database initialized at {args.db_path}")

    if args.stats:
        stats = db.get_database_stats()
        print("\nDatabase Statistics:")
        print(f"  Recordings: {stats['recordings_count']}")
        print(f"  Messages: {stats['recording_data_count']}")
        print(f"  Images: {stats['recording_images_count']}")
        print(f"  Configurations: {stats['configurations_count']}")
        print(f"  Database size: {stats['database_size_mb']:.2f} MB")


if __name__ == '__main__':
    main()
