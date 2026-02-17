"""
Event Recorder & WordPress Publisher - Main Service

Main entry point that orchestrates all components:
- Configuration management
- GPS trigger monitoring
- MQTT data recording
- Power outage recovery
"""

import logging
import signal
import sys
import time
import argparse
import threading
from datetime import datetime
from pathlib import Path

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
                app_password=wp_config.get('app_password')
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

        # TODO: Trigger data processing (Phase 2)

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

    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

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
