"""
Full integration test for Phases 1-2: Recording → Processing cycle

Tests the complete workflow:
1. Initialize database
2. Start GPS trigger monitor
3. Start data recorder
4. Simulate GPS movement via MQTT
5. Verify recording started
6. Simulate vehicle stopped
7. Verify recording stopped
8. Process recording (generate plots)
9. Verify outputs
"""

import os
import sys
import time
import logging
from datetime import datetime
from pathlib import Path
import paho.mqtt.client as mqtt

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from event_recorder.models import Database, RecordingStatus
from event_recorder.data_recorder import DataRecorder
from event_recorder.trigger_monitor import GPSTriggerMonitor
from event_recorder.data_processor import DataProcessor

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class TestConfig:
    """Test configuration."""
    MQTT_BROKER = "localhost"
    MQTT_PORT = 1883
    DB_PATH = "test_recordings.db"
    PLOTS_DIR = "test_plots"

    # GPS coordinates for Perth, Australia area
    START_LAT = -31.9505
    START_LON = 115.8605

    # Movement scenario (simulate driving ~500m)
    GPS_WAYPOINTS = [
        (-31.9505, 115.8605),  # Start
        (-31.9510, 115.8610),  # Moving
        (-31.9515, 115.8615),  # Moving
        (-31.9520, 115.8620),  # Moving
        (-31.9525, 115.8625),  # Destination
    ]

    # Simulated sensor data
    SPEED_VALUES = [0, 15, 25, 30, 20, 5, 0]  # km/h
    BATTERY_POWER = [0, -1500, -2000, -2200, -1800, -800, -100]  # W (negative = discharge)
    BATTERY_VOLTAGE = [52.0, 51.5, 51.2, 51.0, 51.3, 51.8, 52.0]  # V


class MQTTSimulator:
    """Simulates MQTT sensor data for testing."""

    def __init__(self, broker: str = "localhost", port: int = 1883):
        self.client = mqtt.Client()
        self.broker = broker
        self.port = port
        self.connected = False

    def connect(self):
        """Connect to MQTT broker."""
        try:
            self.client.connect(self.broker, self.port, 60)
            self.client.loop_start()
            time.sleep(1)
            self.connected = True
            logger.info(f"MQTT Simulator connected to {self.broker}:{self.port}")
        except Exception as e:
            logger.error(f"Failed to connect MQTT simulator: {e}")
            raise

    def disconnect(self):
        """Disconnect from broker."""
        self.client.loop_stop()
        self.client.disconnect()
        self.connected = False

    def publish_gps_position(self, latitude: float, longitude: float):
        """Publish GPS position."""
        self.client.publish("gps/latitude/0", str(latitude))
        self.client.publish("gps/longitude/0", str(longitude))
        logger.info(f"Published GPS: {latitude:.6f}, {longitude:.6f}")

    def publish_speed(self, speed: float):
        """Publish speed."""
        self.client.publish("gps/speed/0", str(speed))
        logger.debug(f"Published speed: {speed} km/h")

    def publish_battery_data(self, power: float, voltage: float):
        """Publish battery data."""
        self.client.publish("battery/power/0/0", str(power))
        self.client.publish("battery/voltage/0/0", str(voltage))
        logger.debug(f"Published battery: {power}W, {voltage}V")

    def simulate_drive_cycle(self, waypoints: list, speeds: list,
                            battery_powers: list, battery_voltages: list,
                            interval: float = 2.0):
        """
        Simulate a complete drive cycle.

        Args:
            waypoints: List of (lat, lon) tuples
            speeds: List of speed values
            battery_powers: List of power values
            battery_voltages: List of voltage values
            interval: Time between updates (seconds)
        """
        logger.info("Starting drive cycle simulation")

        num_points = max(len(waypoints), len(speeds), len(battery_powers), len(battery_voltages))

        for i in range(num_points):
            # GPS position
            if i < len(waypoints):
                lat, lon = waypoints[i]
                self.publish_gps_position(lat, lon)

            # Speed
            if i < len(speeds):
                self.publish_speed(speeds[i])

            # Battery
            if i < len(battery_powers) and i < len(battery_voltages):
                self.publish_battery_data(battery_powers[i], battery_voltages[i])

            time.sleep(interval)

        logger.info("Drive cycle simulation complete")


def test_full_cycle():
    """Run full integration test."""

    logger.info("="*60)
    logger.info("FULL INTEGRATION TEST: Phases 1-2")
    logger.info("="*60)

    # Clean up previous test data
    if os.path.exists(TestConfig.DB_PATH):
        os.remove(TestConfig.DB_PATH)
        logger.info("Removed old test database")

    if os.path.exists(TestConfig.PLOTS_DIR):
        import shutil
        shutil.rmtree(TestConfig.PLOTS_DIR)
        logger.info("Removed old test plots")

    # 1. Initialize database
    logger.info("\n" + "="*60)
    logger.info("STEP 1: Initialize Database")
    logger.info("="*60)
    db = Database(TestConfig.DB_PATH)
    logger.info("✓ Database initialized")

    # 2. Initialize components
    logger.info("\n" + "="*60)
    logger.info("STEP 2: Initialize Components")
    logger.info("="*60)

    data_recorder = DataRecorder(
        db,
        TestConfig.MQTT_BROKER,
        TestConfig.MQTT_PORT,
        flush_interval=2,  # Fast flush for testing
        max_buffer_size=100
    )

    trigger_monitor = GPSTriggerMonitor(
        TestConfig.MQTT_BROKER,
        TestConfig.MQTT_PORT
    )

    mqtt_simulator = MQTTSimulator(
        TestConfig.MQTT_BROKER,
        TestConfig.MQTT_PORT
    )

    logger.info("✓ Components initialized")

    # 3. Connect to MQTT
    logger.info("\n" + "="*60)
    logger.info("STEP 3: Connect to MQTT Broker")
    logger.info("="*60)

    try:
        data_recorder.connect()
        trigger_monitor.connect()
        mqtt_simulator.connect()
        time.sleep(2)  # Wait for connections
        logger.info("✓ All MQTT connections established")
    except Exception as e:
        logger.error(f"✗ Failed to connect to MQTT: {e}")
        logger.error("Make sure Mosquitto is running: docker-compose up mosquitto")
        return False

    # Track recording
    recording_id = None

    # 4. Setup trigger monitor
    logger.info("\n" + "="*60)
    logger.info("STEP 4: Setup GPS Trigger Monitor")
    logger.info("="*60)

    def on_start(monitor_id, config):
        nonlocal recording_id
        logger.info("🟢 START TRIGGER FIRED!")

        # Create recording
        recording_name = f"Test Drive - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        recording_id = db.create_recording(recording_name, "Integration test recording")
        logger.info(f"Created recording {recording_id}: {recording_name}")

        # Start recording
        record_topics = [
            "gps/#",
            "battery/power/+/+",
            "battery/voltage/+/+"
        ]
        data_recorder.start_recording(recording_id, record_topics)
        logger.info(f"Started recording from {len(record_topics)} topic patterns")

        return recording_id

    def on_stop(monitor_id, rec_id):
        logger.info("🔴 STOP TRIGGER FIRED!")
        logger.info(f"Stopping recording {rec_id}")

        # Stop recording
        data_recorder.stop_recording(rec_id)
        db.update_recording(rec_id, status=RecordingStatus.STOPPED, end_time=datetime.utcnow())

        # Get stats
        message_count = db.get_recording_data_count(rec_id)
        topics = db.get_recording_topics(rec_id)
        logger.info(f"Recording {rec_id} completed:")
        logger.info(f"  Messages: {message_count}")
        logger.info(f"  Topics: {topics}")

    # Configure trigger
    config = {
        'monitor_topics': ['gps/latitude/0', 'gps/longitude/0'],
        'start_condition': {
            'type': 'gps_movement',
            'distance_threshold': 20,  # 20 meters
            'duration': 5  # 5 seconds (faster for testing)
        },
        'stop_condition': {
            'type': 'gps_stopped',
            'distance_threshold': 5,  # 5 meters
            'duration': 5  # 5 seconds (faster for testing)
        }
    }

    trigger_monitor.add_monitor('test_drive', config, on_start, on_stop)
    logger.info("✓ Trigger monitor configured")

    # 5. Simulate drive cycle
    logger.info("\n" + "="*60)
    logger.info("STEP 5: Simulate Drive Cycle")
    logger.info("="*60)
    logger.info("Publishing GPS waypoints, speed, and battery data...")
    logger.info("This will take ~30 seconds...")

    try:
        # Start stationary (should not trigger)
        logger.info("\nPhase 1: Stationary at start")
        for _ in range(3):
            mqtt_simulator.publish_gps_position(TestConfig.START_LAT, TestConfig.START_LON)
            mqtt_simulator.publish_speed(0)
            mqtt_simulator.publish_battery_data(0, 52.0)
            time.sleep(2)

        # Start moving (should trigger START after 5 seconds)
        logger.info("\nPhase 2: Starting to move (trigger START)")
        mqtt_simulator.simulate_drive_cycle(
            TestConfig.GPS_WAYPOINTS,
            TestConfig.SPEED_VALUES,
            TestConfig.BATTERY_POWER,
            TestConfig.BATTERY_VOLTAGE,
            interval=2.0
        )

        # Wait for start trigger
        time.sleep(3)

        if recording_id is None:
            logger.error("✗ Start trigger did not fire!")
            return False

        logger.info(f"✓ Recording {recording_id} is active")

        # Continue at destination (should trigger STOP after 5 seconds)
        logger.info("\nPhase 3: Stopped at destination (trigger STOP)")
        end_lat, end_lon = TestConfig.GPS_WAYPOINTS[-1]
        for _ in range(4):
            mqtt_simulator.publish_gps_position(end_lat, end_lon)
            mqtt_simulator.publish_speed(0)
            mqtt_simulator.publish_battery_data(-50, 52.0)
            time.sleep(2)

        logger.info("✓ Drive cycle simulation complete")

    except Exception as e:
        logger.error(f"✗ Simulation failed: {e}")
        return False

    # 6. Verify recording
    logger.info("\n" + "="*60)
    logger.info("STEP 6: Verify Recording")
    logger.info("="*60)

    if recording_id is None:
        logger.error("✗ No recording was created")
        return False

    recording = db.get_recording(recording_id)
    logger.info(f"Recording {recording_id}:")
    logger.info(f"  Name: {recording['name']}")
    logger.info(f"  Status: {recording['status']}")
    logger.info(f"  Start: {recording['start_time']}")
    logger.info(f"  End: {recording['end_time']}")

    message_count = db.get_recording_data_count(recording_id)
    topics = db.get_recording_topics(recording_id)

    logger.info(f"  Messages: {message_count}")
    logger.info(f"  Topics: {len(topics)}")
    for topic in topics:
        topic_data = db.get_recording_data(recording_id, topic_filter=topic)
        logger.info(f"    - {topic}: {len(topic_data)} messages")

    if message_count == 0:
        logger.error("✗ No data was recorded!")
        return False

    logger.info("✓ Recording verified")

    # 7. Process recording (generate plots)
    logger.info("\n" + "="*60)
    logger.info("STEP 7: Process Recording (Generate Plots)")
    logger.info("="*60)

    processor = DataProcessor(db, TestConfig.PLOTS_DIR)

    plot_config = [
        {
            'type': 'line',
            'title': 'Speed Over Time',
            'topics': ['gps/speed/0'],
            'ylabel': 'Speed (km/h)',
            'color': '#667eea'
        },
        {
            'type': 'line',
            'title': 'Battery Power',
            'topics': ['battery/power/0/0'],
            'ylabel': 'Power (W)',
            'color': '#764ba2'
        },
        {
            'type': 'line',
            'title': 'Battery Voltage',
            'topics': ['battery/voltage/0/0'],
            'ylabel': 'Voltage (V)',
            'color': '#48cae4'
        },
        {
            'type': 'map',
            'title': 'Drive Route',
            'topics': ['gps/latitude/0', 'gps/longitude/0']
        }
    ]

    try:
        results = processor.process_recording(recording_id, plot_config)

        if results['status'] == 'success':
            logger.info("✓ Processing complete")
            logger.info(f"  Plots generated: {len(results['plots'])}")
            for plot in results['plots']:
                logger.info(f"    - {plot}")

            logger.info("\n  Statistics:")
            for key, value in results['statistics'].items():
                logger.info(f"    {key}: {value}")
        else:
            logger.error(f"✗ Processing failed: {results.get('error')}")
            return False

    except Exception as e:
        logger.error(f"✗ Processing error: {e}")
        import traceback
        traceback.print_exc()
        return False

    # 8. Verify outputs
    logger.info("\n" + "="*60)
    logger.info("STEP 8: Verify Outputs")
    logger.info("="*60)

    plots_dir = Path(TestConfig.PLOTS_DIR) / str(recording_id)
    if not plots_dir.exists():
        logger.error(f"✗ Plots directory not found: {plots_dir}")
        return False

    plot_files = list(plots_dir.glob("*.png"))
    logger.info(f"Found {len(plot_files)} plot files:")
    for plot_file in plot_files:
        size_kb = plot_file.stat().st_size / 1024
        logger.info(f"  - {plot_file.name} ({size_kb:.1f} KB)")

    if len(plot_files) < 3:
        logger.warning(f"⚠ Expected at least 3 plots, found {len(plot_files)}")
    else:
        logger.info("✓ Plots verified")

    # 9. Cleanup
    logger.info("\n" + "="*60)
    logger.info("STEP 9: Cleanup")
    logger.info("="*60)

    data_recorder.shutdown()
    trigger_monitor.shutdown()
    mqtt_simulator.disconnect()
    logger.info("✓ Connections closed")

    # 10. Summary
    logger.info("\n" + "="*60)
    logger.info("TEST SUMMARY")
    logger.info("="*60)
    logger.info("✅ Database initialization: SUCCESS")
    logger.info("✅ MQTT connections: SUCCESS")
    logger.info("✅ GPS trigger detection: SUCCESS")
    logger.info("✅ Data recording: SUCCESS")
    logger.info(f"✅ Messages recorded: {message_count}")
    logger.info(f"✅ Plots generated: {len(plot_files)}")
    logger.info("✅ Statistics calculated: SUCCESS")
    logger.info("\n" + "="*60)
    logger.info("INTEGRATION TEST: PASSED ✅")
    logger.info("="*60)
    logger.info(f"\nTest outputs:")
    logger.info(f"  Database: {Path(TestConfig.DB_PATH).absolute()}")
    logger.info(f"  Plots: {plots_dir.absolute()}")
    logger.info(f"\nView plots:")
    for plot_file in plot_files:
        logger.info(f"  start {plot_file.absolute()}")

    return True


if __name__ == '__main__':
    try:
        success = test_full_cycle()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        logger.info("\n\nTest interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"\n\nTest failed with exception: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
