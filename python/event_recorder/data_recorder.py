"""
MQTT data recorder with buffering and SQLite persistence.

Subscribes to MQTT topics and buffers messages for batch writing to database.
Follows pattern from emonMQTTToInflux.py.
"""

import logging
import time
from datetime import datetime
from typing import List, Optional, Callable
from threading import Thread, Lock
import paho.mqtt.client as mqtt

from .models import Database

logger = logging.getLogger(__name__)


class MessageBuffer:
    """
    Thread-safe message buffer for batch writes to database.

    Automatically flushes when buffer reaches size limit or time limit.
    """

    def __init__(self, database: Database, flush_interval: int = 5,
                 max_buffer_size: int = 1000):
        """
        Initialize message buffer.

        Args:
            database: Database instance
            flush_interval: Flush interval in seconds
            max_buffer_size: Maximum messages before forced flush
        """
        self.database = database
        self.flush_interval = flush_interval
        self.max_buffer_size = max_buffer_size

        self.buffer = []
        self.lock = Lock()
        self.last_flush_time = time.time()

        logger.info(f"MessageBuffer initialized (flush={flush_interval}s, max_size={max_buffer_size})")

    def add_message(self, recording_id: int, topic: str, payload: str,
                   timestamp: datetime = None):
        """
        Add message to buffer.

        Args:
            recording_id: Recording ID
            topic: MQTT topic
            payload: Message payload
            timestamp: Message timestamp (default: now)
        """
        if timestamp is None:
            timestamp = datetime.utcnow()

        with self.lock:
            self.buffer.append((recording_id, timestamp, topic, payload))

            # Check if should flush
            should_flush = (
                len(self.buffer) >= self.max_buffer_size or
                (time.time() - self.last_flush_time) >= self.flush_interval
            )

            if should_flush:
                self._flush_buffer()

    def _flush_buffer(self):
        """
        Flush buffer to database (internal, assumes lock is held).

        This is called from within add_message while lock is held.
        """
        if not self.buffer:
            return

        try:
            # Batch write to database
            self.database.add_messages_batch(self.buffer)
            message_count = len(self.buffer)
            self.buffer.clear()
            self.last_flush_time = time.time()
            logger.debug(f"Flushed {message_count} messages to database")
        except Exception as e:
            logger.error(f"Failed to flush buffer: {e}")
            # Keep messages in buffer for retry

    def flush(self):
        """Force flush buffer to database (public method)."""
        with self.lock:
            self._flush_buffer()

    def get_buffer_size(self) -> int:
        """Get current buffer size."""
        with self.lock:
            return len(self.buffer)


class DataRecorder:
    """
    MQTT data recorder with buffering.

    Subscribes to MQTT topics and records messages to database during
    active recording sessions.
    """

    def __init__(self, database: Database, mqtt_broker: str = "localhost",
                 mqtt_port: int = 1883, flush_interval: int = 5,
                 max_buffer_size: int = 1000):
        """
        Initialize data recorder.

        Args:
            database: Database instance
            mqtt_broker: MQTT broker hostname
            mqtt_port: MQTT broker port
            flush_interval: Buffer flush interval in seconds
            max_buffer_size: Maximum buffer size before flush
        """
        self.database = database
        self.mqtt_broker = mqtt_broker
        self.mqtt_port = mqtt_port

        # Message buffer
        self.buffer = MessageBuffer(database, flush_interval, max_buffer_size)

        # Active recordings: {recording_id: {topics: [...], enabled: bool}}
        self.active_recordings = {}
        self.recordings_lock = Lock()

        # MQTT client
        self.mqtt_client = mqtt.Client()
        self.mqtt_client.on_connect = self._on_connect
        self.mqtt_client.on_message = self._on_message
        self.mqtt_client.on_disconnect = self._on_disconnect

        # Track subscribed topics to avoid duplicate subscriptions
        self.subscribed_topics = set()

        # Connection status
        self.connected = False

        logger.info(f"DataRecorder initialized (broker={mqtt_broker}:{mqtt_port})")

    def connect(self):
        """Connect to MQTT broker."""
        try:
            logger.info(f"Connecting to MQTT broker at {self.mqtt_broker}:{self.mqtt_port}")
            self.mqtt_client.connect(self.mqtt_broker, self.mqtt_port, 120)
            self.mqtt_client.loop_start()
        except Exception as e:
            logger.error(f"Failed to connect to MQTT broker: {e}")
            raise

    def disconnect(self):
        """Disconnect from MQTT broker and flush buffer."""
        logger.info("Disconnecting from MQTT broker")
        self.buffer.flush()  # Ensure all messages saved
        self.mqtt_client.loop_stop()
        self.mqtt_client.disconnect()

    def _on_connect(self, client, userdata, flags, rc):
        """MQTT connect callback."""
        if rc == 0:
            self.connected = True
            logger.info(f"Connected to MQTT broker (result code {rc})")

            # Resubscribe to all topics
            with self.recordings_lock:
                all_topics = set()
                for rec_info in self.active_recordings.values():
                    all_topics.update(rec_info['topics'])

                for topic in all_topics:
                    client.subscribe(topic)
                    logger.info(f"Subscribed to topic: {topic}")
        else:
            logger.error(f"Failed to connect to MQTT broker (result code {rc})")
            self.connected = False

    def _on_disconnect(self, client, userdata, rc):
        """MQTT disconnect callback."""
        self.connected = False
        if rc != 0:
            logger.warning(f"Unexpected disconnect from MQTT broker (rc={rc})")
        else:
            logger.info("Disconnected from MQTT broker")

    def _on_message(self, client, userdata, msg):
        """
        MQTT message callback.

        Routes message to active recordings based on topic match.
        """
        topic = msg.topic
        try:
            payload = msg.payload.decode('utf-8')
        except UnicodeDecodeError:
            logger.warning(f"Failed to decode message from {topic}")
            return

        timestamp = datetime.utcnow()

        # Check which recordings should receive this message
        with self.recordings_lock:
            for recording_id, rec_info in self.active_recordings.items():
                if rec_info['enabled'] and self._topic_matches(topic, rec_info['topics']):
                    self.buffer.add_message(recording_id, topic, payload, timestamp)
                    logger.debug(f"Recorded message: {topic} -> recording {recording_id}")

    def _topic_matches(self, topic: str, topic_patterns: List[str]) -> bool:
        """
        Check if topic matches any of the patterns.

        Supports MQTT wildcards: + (single level), # (multi-level).

        Args:
            topic: Actual MQTT topic (e.g., "gps/speed/0")
            topic_patterns: List of patterns (e.g., ["gps/#", "battery/+/+"])

        Returns:
            bool: True if topic matches any pattern
        """
        for pattern in topic_patterns:
            if self._mqtt_topic_match(pattern, topic):
                return True
        return False

    def _mqtt_topic_match(self, pattern: str, topic: str) -> bool:
        """
        Check if topic matches MQTT wildcard pattern.

        Args:
            pattern: Pattern with wildcards (e.g., "gps/#")
            topic: Actual topic (e.g., "gps/speed/0")

        Returns:
            bool: True if matches
        """
        pattern_parts = pattern.split('/')
        topic_parts = topic.split('/')

        # Handle multi-level wildcard (#) - must be last
        if '#' in pattern_parts:
            hash_index = pattern_parts.index('#')
            if hash_index != len(pattern_parts) - 1:
                logger.warning(f"Invalid pattern: # must be last level: {pattern}")
                return False

            # Match up to #, then accept anything
            return pattern_parts[:hash_index] == topic_parts[:hash_index]

        # Must have same number of levels
        if len(pattern_parts) != len(topic_parts):
            return False

        # Check each level
        for pattern_part, topic_part in zip(pattern_parts, topic_parts):
            if pattern_part == '+':
                continue  # + matches any single level
            elif pattern_part != topic_part:
                return False

        return True

    def start_recording(self, recording_id: int, topics: List[str]):
        """
        Start recording from specified MQTT topics.

        Args:
            recording_id: Recording ID
            topics: List of MQTT topic patterns to record
        """
        with self.recordings_lock:
            if recording_id in self.active_recordings:
                logger.warning(f"Recording {recording_id} already active")
                return

            self.active_recordings[recording_id] = {
                'topics': topics,
                'enabled': True
            }

            # Subscribe to new topics
            for topic in topics:
                if topic not in self.subscribed_topics:
                    self.mqtt_client.subscribe(topic)
                    self.subscribed_topics.add(topic)
                    logger.info(f"Subscribed to topic: {topic} (recording {recording_id})")

        logger.info(f"Started recording {recording_id} with {len(topics)} topics")

    def stop_recording(self, recording_id: int):
        """
        Stop recording.

        Args:
            recording_id: Recording ID
        """
        with self.recordings_lock:
            if recording_id not in self.active_recordings:
                logger.warning(f"Recording {recording_id} not active")
                return

            # Mark as disabled (don't remove yet, messages may still be in buffer)
            self.active_recordings[recording_id]['enabled'] = False

        # Flush buffer to ensure all messages saved
        self.buffer.flush()

        # Now remove from active recordings
        with self.recordings_lock:
            topics = self.active_recordings[recording_id]['topics']
            del self.active_recordings[recording_id]

            # Unsubscribe from topics no longer needed
            self._cleanup_subscriptions()

        logger.info(f"Stopped recording {recording_id}")

    def pause_recording(self, recording_id: int):
        """
        Temporarily pause recording (don't unsubscribe).

        Args:
            recording_id: Recording ID
        """
        with self.recordings_lock:
            if recording_id in self.active_recordings:
                self.active_recordings[recording_id]['enabled'] = False
                logger.info(f"Paused recording {recording_id}")

    def resume_recording(self, recording_id: int):
        """
        Resume paused recording.

        Args:
            recording_id: Recording ID
        """
        with self.recordings_lock:
            if recording_id in self.active_recordings:
                self.active_recordings[recording_id]['enabled'] = True
                logger.info(f"Resumed recording {recording_id}")

    def _cleanup_subscriptions(self):
        """
        Unsubscribe from topics that are no longer needed by any active recording.

        Should be called with recordings_lock held.
        """
        # Collect all topics still needed
        needed_topics = set()
        for rec_info in self.active_recordings.values():
            needed_topics.update(rec_info['topics'])

        # Unsubscribe from topics no longer needed
        for topic in list(self.subscribed_topics):
            if topic not in needed_topics:
                self.mqtt_client.unsubscribe(topic)
                self.subscribed_topics.remove(topic)
                logger.info(f"Unsubscribed from topic: {topic}")

    def get_active_recordings(self) -> List[int]:
        """
        Get list of active recording IDs.

        Returns:
            List of recording IDs
        """
        with self.recordings_lock:
            return [
                recording_id
                for recording_id, rec_info in self.active_recordings.items()
                if rec_info['enabled']
            ]

    def get_buffer_status(self) -> dict:
        """
        Get current buffer status.

        Returns:
            Dict with buffer stats
        """
        return {
            'buffer_size': self.buffer.get_buffer_size(),
            'max_buffer_size': self.buffer.max_buffer_size,
            'flush_interval': self.buffer.flush_interval,
            'active_recordings': len(self.get_active_recordings()),
            'connected': self.connected,
            'subscribed_topics': list(self.subscribed_topics)
        }

    def shutdown(self):
        """Shutdown recorder gracefully."""
        logger.info("Shutting down data recorder")

        # Stop all recordings
        with self.recordings_lock:
            recording_ids = list(self.active_recordings.keys())

        for recording_id in recording_ids:
            self.stop_recording(recording_id)

        # Disconnect
        self.disconnect()


def main():
    """
    CLI for testing data recorder.

    Usage:
        python data_recorder.py [--broker BROKER] [--db DB_PATH]
    """
    import argparse

    parser = argparse.ArgumentParser(description="Event Recorder Data Recorder")
    parser.add_argument('--broker', default='localhost', help="MQTT broker")
    parser.add_argument('--port', type=int, default=1883, help="MQTT port")
    parser.add_argument('--db', default='/tmp/test_recordings.db', help="Database path")
    parser.add_argument('--topics', nargs='+', default=['test/#'], help="Topics to record")
    parser.add_argument('--duration', type=int, default=30, help="Recording duration (seconds)")

    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(level=logging.INFO,
                       format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    # Create database and recorder
    from .models import Database
    db = Database(args.db)
    recorder = DataRecorder(db, args.broker, args.port)

    try:
        # Connect
        recorder.connect()

        # Create test recording
        recording_id = db.create_recording("Test Recording", "CLI test")
        logger.info(f"Created recording {recording_id}")

        # Start recording
        recorder.start_recording(recording_id, args.topics)
        logger.info(f"Recording from topics: {args.topics}")

        # Record for specified duration
        logger.info(f"Recording for {args.duration} seconds...")
        time.sleep(args.duration)

        # Stop recording
        recorder.stop_recording(recording_id)
        db.update_recording(recording_id, status='stopped', end_time=datetime.utcnow())

        # Show stats
        message_count = db.get_recording_data_count(recording_id)
        topics = db.get_recording_topics(recording_id)
        logger.info(f"Recorded {message_count} messages from {len(topics)} topics")
        logger.info(f"Topics: {topics}")

    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    finally:
        recorder.shutdown()


if __name__ == '__main__':
    main()
