"""
Event Recorder & WordPress Publisher - Main Service

Main entry point that orchestrates all components:
- Configuration management
- GPS trigger monitoring
- MQTT data recording
- Power outage recovery
"""

import json
import logging
import os
import signal
import sys
import time
import argparse
import threading
from datetime import datetime, timezone
from pathlib import Path

import paho.mqtt.client as mqtt

from .models import Database, RecordingStatus
from .config_manager import ConfigManager
from .data_recorder import DataRecorder
from .trigger_monitor import GPSTriggerMonitor
from .recovery_manager import RecoveryManager
from .web_interface import WebInterface
from .wordpress_publisher import WordPressPublisher

logger = logging.getLogger(__name__)


class EventRecorderService:
    """
    Main service class that coordinates all components.

    Manages lifecycle of GPS monitoring, data recording, and recovery.
    """

    def __init__(self, config_path: str, events_dir: str = None, data_dir: str = None):
        """
        Initialize event recorder service.

        Args:
            config_path: Path to service config file
            events_dir: Directory containing event configs
            data_dir: Data directory (database, plots)
        """
        logger.info("="*60)
        logger.info("Event Recorder & WordPress Publisher")
        logger.info("="*60)

        # Load configuration
        logger.info(f"Loading configuration from {config_path}")
        self.config = ConfigManager(config_path, events_dir)

        # Validate configuration
        errors = self.config.validate_config()
        if errors:
            logger.error("Configuration validation failed:")
            for error in errors:
                logger.error(f"  - {error}")
            raise ValueError("Invalid configuration")

        # Setup data directory
        if data_dir:
            self.data_dir = Path(data_dir)
        else:
            self.data_dir = Path(self.config.get('service.data_dir', '/data'))

        self.data_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Data directory: {self.data_dir}")

        # Initialize database
        db_path = self.config.get_database_path()
        if not Path(db_path).is_absolute():
            db_path = self.data_dir / db_path
        logger.info(f"Database: {db_path}")
        self.database = Database(str(db_path))

        # MQTT configuration
        mqtt_config = self.config.get_mqtt_config()
        self.mqtt_broker = mqtt_config['broker']
        self.mqtt_port = mqtt_config['port']

        # Initialize components
        recording_config = self.config.get_recording_config()
        flush_interval = recording_config.get('buffer_flush_interval', 5)
        max_buffer_size = recording_config.get('max_buffer_size', 1000)

        self.data_recorder = DataRecorder(
            self.database,
            self.mqtt_broker,
            self.mqtt_port,
            flush_interval,
            max_buffer_size
        )

        self.trigger_monitor = GPSTriggerMonitor(
            self.mqtt_broker,
            self.mqtt_port
        )

        self.recovery_manager = RecoveryManager(self.database)

        # Initialize WordPress publisher (optional)
        # get_wordpress_config() returns the default_site dict directly
        wp_config = self.config.get_wordpress_config()
        if wp_config and wp_config.get('site_url'):
            self.wordpress_publisher = WordPressPublisher(
                site_url=wp_config.get('site_url'),
                username=wp_config.get('username'),
                app_password=wp_config.get('app_password'),
                http_auth_username=wp_config.get('http_auth_username') or None,
                http_auth_password=wp_config.get('http_auth_password') or None,
            )
        else:
            self.wordpress_publisher = None

        # Initialize web interface
        self.web_interface = WebInterface(
            database=self.database,
            service_manager=None,  # Will be set after service is fully initialized
            wordpress_publisher=self.wordpress_publisher,
            plots_dir=str(self.data_dir / "plots"),
            uploads_dir=str(self.data_dir / "uploads"),
            port=5000
        )
        self.web_thread = None

        # Active recordings tracking: {monitor_id: recording_id}
        self.active_recordings = {}

        # Running flag
        self.running = False

        # MQTT status publisher (separate client so it never interferes with data recording)
        self._status_mqtt_client = None
        self._status_publisher_thread = None

        # Set service manager reference for web interface
        self.web_interface.service_manager = self

        logger.info("Service initialized successfully")

    def start(self):
        """Start the service."""
        logger.info("Starting event recorder service")
        self.running = True

        try:
            # Run recovery first
            self._run_recovery()

            # Connect to MQTT
            logger.info("Connecting to MQTT broker")
            self.data_recorder.connect()
            self.trigger_monitor.connect()

            # Wait for MQTT connections
            time.sleep(2)

            if not self.data_recorder.connected:
                raise ConnectionError("Failed to connect data recorder to MQTT")
            if not self.trigger_monitor.connected:
                raise ConnectionError("Failed to connect trigger monitor to MQTT")

            # Setup event monitors from configuration
            self._setup_event_monitors()

            # Start MQTT recording status publisher
            self._start_status_publisher()

            # Start web interface in separate thread
            logger.info("Starting web interface on port 5000")
            self.web_thread = threading.Thread(
                target=self.web_interface.run,
                daemon=True,
                name="WebInterface"
            )
            self.web_thread.start()
            logger.info("Web interface started")

            logger.info("="*60)
            logger.info("Service started successfully")
            logger.info("Monitoring for GPS triggers...")
            logger.info("Web UI: http://localhost:5000")
            logger.info("="*60)

            # Main loop
            self._run_main_loop()

        except Exception as e:
            logger.error(f"Service failed to start: {e}")
            raise

    def _run_recovery(self):
        """Run power outage recovery on startup."""
        logger.info("Running recovery check")

        def process_callback(recording_id):
            logger.info(f"Recovery: recording {recording_id} needs processing")
            # TODO: Trigger data processing (Phase 2)
            # For now, just mark as stopped
            self.database.update_recording(recording_id, status=RecordingStatus.STOPPED)

        summary = self.recovery_manager.auto_recover(on_process_callback=process_callback)
        logger.info(f"Recovery complete: {summary}")

    def _setup_event_monitors(self):
        """Setup GPS trigger monitors from event configurations."""
        event_configs = self.config.get_enabled_event_configs()

        if not event_configs:
            logger.warning("No enabled event configurations found")
            return

        logger.info(f"Setting up {len(event_configs)} event monitors")

        for event_name, event_config in event_configs.items():
            try:
                logger.info(f"Adding monitor: {event_name}")

                # Create callbacks
                def on_start(monitor_id, config, event_name=event_name):
                    return self._on_trigger_start(monitor_id, config, event_name)

                def on_stop(monitor_id, recording_id):
                    return self._on_trigger_stop(monitor_id, recording_id)

                # Add monitor
                self.trigger_monitor.add_monitor(
                    event_name,
                    event_config,
                    on_start=on_start,
                    on_stop=on_stop
                )

                logger.info(f"  Monitor '{event_name}' added successfully")

            except Exception as e:
                logger.error(f"Failed to add monitor '{event_name}': {e}")

    def _on_trigger_start(self, monitor_id: str, config: dict, event_name: str) -> int:
        """
        Handle start trigger.

        Args:
            monitor_id: Monitor identifier
            config: Event configuration
            event_name: Event name

        Returns:
            int: Recording ID
        """
        logger.info(f"START TRIGGER: {event_name}")

        # Create recording
        recording_name = f"{event_name} - {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}"
        recording_description = config.get('description', '')

        recording_id = self.database.create_recording(
            recording_name,
            recording_description,
            trigger_type=config.get('start_condition', {}).get('type', 'unknown')
        )

        logger.info(f"Created recording {recording_id}: {recording_name}")

        # Start recording MQTT topics
        record_topics = config.get('record_topics', [])
        self.data_recorder.start_recording(recording_id, record_topics)

        # Track active recording
        self.active_recordings[monitor_id] = recording_id

        return recording_id

    def _on_trigger_stop(self, monitor_id: str, recording_id: int):
        """
        Handle stop trigger.

        Args:
            monitor_id: Monitor identifier
            recording_id: Recording ID
        """
        logger.info(f"STOP TRIGGER: monitor={monitor_id}, recording={recording_id}")

        # Stop recording
        self.data_recorder.stop_recording(recording_id)

        # Update recording status
        self.database.update_recording(
            recording_id,
            status=RecordingStatus.STOPPED,
            end_time=datetime.utcnow()
        )

        # Get stats
        message_count = self.database.get_recording_data_count(recording_id)
        topics = self.database.get_recording_topics(recording_id)

        logger.info(f"Recording {recording_id} completed:")
        logger.info(f"  Messages: {message_count}")
        logger.info(f"  Topics: {len(topics)}")

        # Remove from active recordings
        if monitor_id in self.active_recordings:
            del self.active_recordings[monitor_id]

        # Auto-process if setting is enabled
        if self.database.get_setting('auto_process_on_stop', 'false') == 'true':
            t = threading.Thread(
                target=self._auto_process_recording,
                args=(recording_id,),
                daemon=True,
                name=f"AutoProcess-{recording_id}"
            )
            t.start()
            logger.info(f"Auto-processing started for recording {recording_id}")

    def _auto_process_recording(self, recording_id: int):
        """Background thread: process a recording after it stops."""
        try:
            logger.info(f"Auto-processing recording {recording_id}")
            from .data_processor import DataProcessor
            processor = DataProcessor(self.database, str(self.data_dir / "plots"))
            processor.process_recording(recording_id)
            logger.info(f"Auto-processing complete for recording {recording_id}")
        except Exception as e:
            logger.error(f"Auto-processing failed for recording {recording_id}: {e}")

    def _start_status_publisher(self):
        """Connect a dedicated MQTT client and start the 1-second status publisher thread."""
        try:
            client = mqtt.Client()
            client.connect(self.mqtt_broker, self.mqtt_port, keepalive=60)
            client.loop_start()
            self._status_mqtt_client = client
            logger.info("Status publisher MQTT client connected")
        except Exception as e:
            logger.warning(f"Could not connect status publisher to MQTT broker: {e} — status publishing disabled")
            return

        self._status_publisher_thread = threading.Thread(
            target=self._status_publisher_loop,
            daemon=True,
            name="StatusPublisher"
        )
        self._status_publisher_thread.start()
        logger.info("Recording status publisher started (1 s interval, topic: event_recorder/recording/<id>/status)")

    def _status_publisher_loop(self):
        """Publish recording status every second for each active recording.

        Queries the database rather than relying on the in-memory
        active_recordings dict so that manually-started recordings (via the
        web interface) are also included.
        """
        while self.running:
            try:
                active = self.database.get_recordings_by_status(RecordingStatus.ACTIVE)
                for recording in active:
                    self._publish_recording_status(recording['id'])
            except Exception as e:
                logger.debug(f"Status publisher loop error: {e}")
            time.sleep(1)

    def _publish_recording_status(self, recording_id: int):
        """Gather stats and publish a status message for one active recording."""
        if not self._status_mqtt_client:
            return
        try:
            recording = self.database.get_recording(recording_id)
            if not recording:
                return

            # Calculate elapsed duration
            start_raw = recording.get('start_time')
            duration_seconds = 0
            if start_raw:
                from dateutil import parser as _du
                start_dt = _du.parse(str(start_raw))
                # Normalise timezone: compare in UTC
                if start_dt.tzinfo is None:
                    now = datetime.utcnow()
                else:
                    now = datetime.now(timezone.utc)
                duration_seconds = max(0, int((now - start_dt).total_seconds()))

            hours, remainder = divmod(duration_seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            duration_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

            message_count = self.database.get_recording_data_count(recording_id)
            photo_count = self.database.get_recording_photo_count(recording_id)

            payload = {
                'recording_id': recording_id,
                'name': recording.get('name', ''),
                'duration': duration_str,
                'duration_seconds': duration_seconds,
                'message_count': message_count,
                'photo_count': photo_count,
                'start_time': str(recording.get('start_time', '')),
                'status': 'active',
            }

            topic = f"event_recorder/recording/{recording_id}/status"
            self._status_mqtt_client.publish(topic, json.dumps(payload), qos=0, retain=False)
            logger.debug(
                f"Status [{recording_id}] {duration_str} | "
                f"{message_count} msgs | {photo_count} photos"
            )

        except Exception as e:
            logger.warning(f"Could not publish status for recording {recording_id}: {e}")

    def _run_main_loop(self):
        """Main service loop."""
        check_interval = 60  # Check every 60 seconds

        while self.running:
            try:
                time.sleep(check_interval)

                # Check for configuration changes
                self.config.check_and_reload()

                # Log status
                if self.active_recordings:
                    logger.info(f"Active recordings: {len(self.active_recordings)}")

                # Get buffer status
                buffer_status = self.data_recorder.get_buffer_status()
                if buffer_status['buffer_size'] > 0:
                    logger.debug(f"Buffer: {buffer_status['buffer_size']} messages")

            except KeyboardInterrupt:
                logger.info("Received interrupt signal")
                break
            except Exception as e:
                logger.error(f"Error in main loop: {e}")

    def stop(self):
        """Stop the service gracefully."""
        logger.info("Stopping event recorder service")
        self.running = False

        # Stop all active recordings
        for monitor_id, recording_id in list(self.active_recordings.items()):
            logger.info(f"Stopping active recording {recording_id}")
            self.data_recorder.stop_recording(recording_id)
            self.database.update_recording(
                recording_id,
                status=RecordingStatus.STOPPED,
                end_time=datetime.utcnow()
            )

        # Shutdown status publisher
        if self._status_mqtt_client:
            self._status_mqtt_client.loop_stop()
            self._status_mqtt_client.disconnect()
            self._status_mqtt_client = None

        # Shutdown components
        self.data_recorder.shutdown()
        self.trigger_monitor.shutdown()

        # Show final stats
        db_stats = self.database.get_database_stats()
        logger.info("Service Statistics:")
        logger.info(f"  Total recordings: {db_stats['recordings_count']}")
        logger.info(f"  Total messages: {db_stats['recording_data_count']}")
        logger.info(f"  Database size: {db_stats['database_size_mb']:.2f} MB")

        logger.info("Service stopped")


def main():
    """
    Main entry point.

    Usage:
        python -m event_recorder.main --config /config/event_recorder_config.yml
    """
    parser = argparse.ArgumentParser(
        description='Event Recorder & WordPress Publisher Service',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run with default settings
  python -m event_recorder.main --config /config/event_recorder_config.yml

  # Specify events directory
  python -m event_recorder.main --config /config/event_recorder_config.yml \\
      --events-dir /config/events

  # Specify data directory
  python -m event_recorder.main --config /config/event_recorder_config.yml \\
      --data-dir /data
        """
    )

    parser.add_argument(
        '--config',
        required=True,
        help='Path to service configuration file (event_recorder_config.yml)'
    )

    parser.add_argument(
        '--events-dir',
        help='Path to events configuration directory (optional)'
    )

    parser.add_argument(
        '--data-dir',
        help='Path to data directory for database and plots (optional)'
    )

    parser.add_argument(
        '--log-level',
        default='INFO',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
        help='Logging level (default: INFO)'
    )

    parser.add_argument(
        '--debug',
        action='store_true',
        help='Enable remote debugging via debugpy on port 5678'
    )

    parser.add_argument(
        '--wait-for-debugger',
        action='store_true',
        help='Pause startup until VSCode debugger attaches (implies --debug)'
    )

    args = parser.parse_args()

    # --wait-for-debugger implies --debug
    if args.wait_for_debugger:
        args.debug = True

    # Setup logging
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Enable remote debugging if DEBUG env var or --debug flag is set
    if args.debug or os.environ.get('DEBUG', '0') == '1':
        try:
            import debugpy
            debugpy.listen(("0.0.0.0", 5678))
            logging.info("debugpy listening on port 5678 - waiting for VSCode to attach...")
            if args.wait_for_debugger or os.environ.get('WAIT_FOR_DEBUGGER', '0') == '1':
                debugpy.wait_for_client()
                logging.info("Debugger attached")
        except ImportError:
            logging.warning("debugpy not installed - remote debugging unavailable (pip install debugpy)")

    # Create service
    try:
        service = EventRecorderService(
            args.config,
            args.events_dir,
            args.data_dir
        )

        # Setup signal handlers for graceful shutdown
        def signal_handler(sig, frame):
            logger.info(f"Received signal {sig}")
            service.stop()
            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        # Start service
        service.start()

    except Exception as e:
        logger.error(f"Service failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
