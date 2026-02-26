"""
SQLite database models and schema for event recorder.

Provides database initialization, table creation, and data access methods
with power-outage resilience via WAL mode.
"""

import sqlite3
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from contextlib import contextmanager

logger = logging.getLogger(__name__)


class RecordingStatus:
    """Recording status constants."""
    ACTIVE = 'active'
    STOPPED = 'stopped'
    PROCESSING = 'processing'
    PROCESSED = 'processed'
    PUBLISHED = 'published'
    FAILED = 'failed'


class ImageType:
    """Image type constants."""
    PLOT = 'plot'
    USER_UPLOAD = 'user_upload'


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

        # Enable WAL mode for crash resilience
        with self.get_connection() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")  # Faster writes, still safe
            logger.info("WAL mode enabled for crash resilience")

    @contextmanager
    def get_connection(self):
        """
        Context manager for database connections.

        Yields:
            sqlite3.Connection: Database connection

        Example:
            with db.get_connection() as conn:
                conn.execute(...)
        """
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row  # Enable column access by name
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Database error: {e}")
            raise
        finally:
            conn.close()

    def init_database(self):
        """Create database schema with all tables and indexes."""
        with self.get_connection() as conn:
            # Recordings table - session metadata
            conn.execute("""
                CREATE TABLE IF NOT EXISTS recordings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    description TEXT,
                    status TEXT NOT NULL CHECK(status IN ('active', 'stopped', 'processing', 'published', 'failed')),
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

            logger.info("Database schema created successfully")

    # === Recording Operations ===

    def create_recording(self, name: str, description: str = "",
                        trigger_type: str = "gps_movement") -> int:
        """
        Create a new recording session.

        Args:
            name: Recording name
            description: Optional description
            trigger_type: Type of trigger (default: gps_movement)

        Returns:
            int: Recording ID
        """
        with self.get_connection() as conn:
            cursor = conn.execute("""
                INSERT INTO recordings (name, description, status, start_time, trigger_type)
                VALUES (?, ?, ?, ?, ?)
            """, (name, description, RecordingStatus.ACTIVE, datetime.utcnow(), trigger_type))
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

    def get_recording(self, recording_id: int) -> Optional[Dict]:
        """
        Get recording by ID.

        Args:
            recording_id: Recording ID

        Returns:
            Dict with recording data or None if not found
        """
        with self.get_connection() as conn:
            cursor = conn.execute("""
                SELECT * FROM recordings WHERE id = ?
            """, (recording_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_recordings_by_status(self, status: str) -> List[Dict]:
        """
        Get all recordings with specified status.

        Args:
            status: Recording status (active, stopped, processing, published, failed)

        Returns:
            List of recording dicts
        """
        with self.get_connection() as conn:
            cursor = conn.execute("""
                SELECT * FROM recordings WHERE status = ?
                ORDER BY start_time DESC
            """, (status,))
            return [dict(row) for row in cursor.fetchall()]

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
            cursor = conn.execute("""
                SELECT * FROM recordings
                ORDER BY start_time DESC
                LIMIT ? OFFSET ?
            """, (limit, offset))
            return [dict(row) for row in cursor.fetchall()]

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
        with self.get_connection() as conn:
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
