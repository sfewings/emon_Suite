"""
GPS trigger monitor for automatic recording start/stop detection.

Monitors GPS position via MQTT and detects vehicle movement using Haversine
distance formula. Implements state machine for trigger conditions.
"""

import logging
import math
import time
from datetime import datetime
from typing import Dict, Optional, Callable, Tuple
from threading import Thread, Lock
from enum import Enum
import paho.mqtt.client as mqtt

logger = logging.getLogger(__name__)


class TriggerState(Enum):
    """Trigger state machine states."""
    IDLE = "idle"
    MONITORING = "monitoring"
    CONDITION_MET = "condition_met"
    TRIGGERED = "triggered"


class GPSTriggerMonitor:
    """
    Monitors GPS position and detects movement-based triggers.

    Uses Haversine formula to calculate distance between GPS coordinates
    and detects when vehicle starts moving or stops.
    """

    def __init__(self, mqtt_broker: str = "localhost", mqtt_port: int = 1883):
        """
        Initialize GPS trigger monitor.

        Args:
            mqtt_broker: MQTT broker hostname
            mqtt_port: MQTT broker port
        """
        self.mqtt_broker = mqtt_broker
        self.mqtt_port = mqtt_port

        # MQTT client
        self.mqtt_client = mqtt.Client()
        self.mqtt_client.on_connect = self._on_connect
        self.mqtt_client.on_message = self._on_message

        # GPS position tracking
        self.current_position = None  # (latitude, longitude, timestamp)
        self.position_lock = Lock()

        # Monitor configurations: {monitor_id: config}
        self.monitors = {}
        self.monitors_lock = Lock()

        # State tracking for each monitor: {monitor_id: state_data}
        self.monitor_states = {}

        # Callbacks for trigger events
        self.on_start_callback = None
        self.on_stop_callback = None

        # Connection status
        self.connected = False

        logger.info(f"GPSTriggerMonitor initialized (broker={mqtt_broker}:{mqtt_port})")

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
        """Disconnect from MQTT broker."""
        logger.info("Disconnecting from MQTT broker")
        self.mqtt_client.loop_stop()
        self.mqtt_client.disconnect()

    def _on_connect(self, client, userdata, flags, rc):
        """MQTT connect callback."""
        if rc == 0:
            self.connected = True
            logger.info(f"Connected to MQTT broker (result code {rc})")

            # Subscribe to all monitored topics
            with self.monitors_lock:
                subscribed_topics = set()
                for monitor_config in self.monitors.values():
                    for topic in monitor_config['config'].get('monitor_topics', []):
                        if topic not in subscribed_topics:
                            client.subscribe(topic)
                            subscribed_topics.add(topic)
                            logger.info(f"Subscribed to GPS topic: {topic}")
        else:
            logger.error(f"Failed to connect to MQTT broker (result code {rc})")
            self.connected = False

    def _on_message(self, client, userdata, msg):
        """
        MQTT message callback for GPS updates.

        Expects GPS messages in numeric format (e.g., "-31.9505" for latitude).
        """
        topic = msg.topic
        try:
            value = float(msg.payload.decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            logger.warning(f"Invalid GPS value from {topic}: {msg.payload}")
            return

        timestamp = datetime.utcnow()

        # Update position based on topic
        if 'latitude' in topic.lower():
            self._update_latitude(value, timestamp)
        elif 'longitude' in topic.lower():
            self._update_longitude(value, timestamp)

        # Check all monitor conditions
        self._check_triggers()

    def _update_latitude(self, latitude: float, timestamp: datetime):
        """Update current latitude."""
        with self.position_lock:
            if self.current_position:
                lat, lon, ts = self.current_position
                self.current_position = (latitude, lon, timestamp)
            else:
                self.current_position = (latitude, None, timestamp)

    def _update_longitude(self, longitude: float, timestamp: datetime):
        """Update current longitude."""
        with self.position_lock:
            if self.current_position:
                lat, lon, ts = self.current_position
                self.current_position = (lat, longitude, timestamp)
            else:
                self.current_position = (None, longitude, timestamp)

    def get_current_position(self) -> Optional[Tuple[float, float, datetime]]:
        """
        Get current GPS position.

        Returns:
            Tuple of (latitude, longitude, timestamp) or None
        """
        with self.position_lock:
            if self.current_position:
                lat, lon, ts = self.current_position
                if lat is not None and lon is not None:
                    return (lat, lon, ts)
        return None

    def add_monitor(self, monitor_id: str, config: Dict,
                   on_start: Callable = None, on_stop: Callable = None):
        """
        Add GPS movement monitor.

        Args:
            monitor_id: Unique monitor identifier
            config: Monitor configuration dict with:
                - monitor_topics: List of GPS topics (latitude, longitude)
                - start_condition: Start trigger condition dict
                - stop_condition: Stop trigger condition dict
                - record_topics: Topics to record when triggered
            on_start: Callback when start condition met (args: monitor_id, config)
            on_stop: Callback when stop condition met (args: monitor_id, recording_id)
        """
        with self.monitors_lock:
            self.monitors[monitor_id] = {
                'config': config,
                'on_start': on_start,
                'on_stop': on_stop,
                'enabled': True
            }

            # Initialize state
            self.monitor_states[monitor_id] = {
                'state': TriggerState.MONITORING,
                'recording_id': None,
                'last_position': None,
                'condition_start_time': None,
                'stationary_start_time': None
            }

            # Subscribe to topics
            for topic in config.get('monitor_topics', []):
                self.mqtt_client.subscribe(topic)
                logger.info(f"Monitor '{monitor_id}': subscribed to {topic}")

        logger.info(f"Added monitor '{monitor_id}'")

    def remove_monitor(self, monitor_id: str):
        """
        Remove GPS movement monitor.

        Args:
            monitor_id: Monitor identifier
        """
        with self.monitors_lock:
            if monitor_id in self.monitors:
                # Unsubscribe from topics if no other monitors need them
                topics = self.monitors[monitor_id]['config'].get('monitor_topics', [])
                del self.monitors[monitor_id]
                del self.monitor_states[monitor_id]

                # Check if topics still needed
                needed_topics = set()
                for m in self.monitors.values():
                    needed_topics.update(m['config'].get('monitor_topics', []))

                for topic in topics:
                    if topic not in needed_topics:
                        self.mqtt_client.unsubscribe(topic)

                logger.info(f"Removed monitor '{monitor_id}'")

    def _check_triggers(self):
        """Check all monitor triggers against current GPS position."""
        current_pos = self.get_current_position()
        if not current_pos:
            return

        current_lat, current_lon, current_time = current_pos

        with self.monitors_lock:
            for monitor_id, monitor in self.monitors.items():
                if not monitor['enabled']:
                    continue

                config = monitor['config']
                state = self.monitor_states[monitor_id]

                # Check based on current state
                if state['state'] == TriggerState.MONITORING:
                    self._check_start_condition(monitor_id, monitor, state,
                                               current_lat, current_lon, current_time)
                elif state['state'] == TriggerState.TRIGGERED:
                    self._check_stop_condition(monitor_id, monitor, state,
                                              current_lat, current_lon, current_time)

    def _check_start_condition(self, monitor_id: str, monitor: Dict, state: Dict,
                               lat: float, lon: float, timestamp: datetime):
        """
        Check if start condition is met.

        Detects vehicle movement based on GPS position changes.
        Compares current position against an anchor point (last known
        stationary position) rather than the previous message, so that
        continuous small movements accumulate correctly.
        """
        config = monitor['config']
        start_condition = config.get('start_condition', {})

        condition_type = start_condition.get('type', 'gps_movement')

        if condition_type == 'gps_movement':
            distance_threshold = start_condition.get('distance_threshold', 20)  # meters
            duration = start_condition.get('duration', 10)  # seconds

            # Need anchor position to calculate distance from
            if state['last_position'] is None:
                state['last_position'] = (lat, lon, timestamp)
                return

            anchor_lat, anchor_lon, anchor_time = state['last_position']

            # Calculate distance from anchor (last stationary position)
            distance = self._haversine_distance(anchor_lat, anchor_lon, lat, lon)
            logger.debug(f"Monitor '{monitor_id}': distance from anchor = {distance:.1f}m")
            if distance > distance_threshold:
                # Vehicle has moved away from anchor
                if state['condition_start_time'] is None:
                    state['condition_start_time'] = timestamp
                    logger.debug(f"Monitor '{monitor_id}': movement detected ({distance:.1f}m from anchor)")
                else:
                    # Check if movement sustained for required duration
                    elapsed = (timestamp - state['condition_start_time']).total_seconds()
                    if elapsed >= duration:
                        # Trigger start!
                        logger.info(f"Monitor '{monitor_id}': START trigger (moved {distance:.1f}m for {elapsed:.0f}s)")
                        self._trigger_start(monitor_id, monitor, state)
                        state['condition_start_time'] = None
                        # Update anchor to current position for stop detection
                        state['last_position'] = (lat, lon, timestamp)
                # Don't update anchor while movement is being tracked
            else:
                # Still near anchor, reset timer and update anchor
                state['condition_start_time'] = None
                state['last_position'] = (lat, lon, timestamp)

        elif condition_type == 'anchor_departure':
            # Start recording when vehicle moves outside a fixed anchor location.
            # The anchor is a configured lat/lon - no dynamic position tracking needed.
            anchor_lat = start_condition.get('anchor_lat')
            anchor_lon = start_condition.get('anchor_lon')
            radius = start_condition.get('radius', 100)       # meters
            duration = start_condition.get('duration', 10)    # seconds

            if anchor_lat is None or anchor_lon is None:
                logger.error(f"Monitor '{monitor_id}': anchor_departure requires anchor_lat and anchor_lon")
                return

            distance = self._haversine_distance(anchor_lat, anchor_lon, lat, lon)
            logger.debug(f"Monitor '{monitor_id}': {distance:.1f}m from configured anchor ({anchor_lat},{anchor_lon})")

            if distance > radius:
                # Outside the anchor zone
                if state['condition_start_time'] is None:
                    state['condition_start_time'] = timestamp
                    logger.debug(f"Monitor '{monitor_id}': departed anchor zone ({distance:.1f}m > {radius}m radius)")
                else:
                    elapsed = (timestamp - state['condition_start_time']).total_seconds()
                    if elapsed >= duration:
                        logger.info(f"Monitor '{monitor_id}': START trigger (anchor departure {distance:.1f}m for {elapsed:.0f}s)")
                        self._trigger_start(monitor_id, monitor, state)
                        state['condition_start_time'] = None
            else:
                # Still inside anchor zone, reset timer
                state['condition_start_time'] = None

        else:
            logger.warning(f"Monitor '{monitor_id}': unknown start condition type '{condition_type}'")

    def _check_stop_condition(self, monitor_id: str, monitor: Dict, state: Dict,
                              lat: float, lon: float, timestamp: datetime):
        """
        Check if stop condition is met.

        Detects vehicle stopped based on GPS position not changing.
        Uses anchor-based comparison: sets an anchor when the vehicle
        first appears stationary, then checks subsequent positions
        stay within threshold of that anchor for the required duration.
        """
        config = monitor['config']
        stop_condition = config.get('stop_condition', {})

        condition_type = stop_condition.get('type', 'gps_stopped')

        if condition_type == 'gps_stopped':
            distance_threshold = stop_condition.get('distance_threshold', 5)  # meters
            duration = stop_condition.get('duration', 60)  # seconds

            # Need anchor position
            if state['last_position'] is None:
                state['last_position'] = (lat, lon, timestamp)
                return

            anchor_lat, anchor_lon, anchor_time = state['last_position']

            # Calculate distance from anchor
            distance = self._haversine_distance(anchor_lat, anchor_lon, lat, lon)

            if distance < distance_threshold:
                # Vehicle stationary (within threshold of anchor)
                if state['stationary_start_time'] is None:
                    state['stationary_start_time'] = timestamp
                    logger.debug(f"Monitor '{monitor_id}': stationary detected ({distance:.1f}m from anchor)")
                else:
                    # Check if stationary for required duration
                    elapsed = (timestamp - state['stationary_start_time']).total_seconds()
                    if elapsed >= duration:
                        # Trigger stop!
                        logger.info(f"Monitor '{monitor_id}': STOP trigger (stationary for {elapsed:.0f}s)")
                        self._trigger_stop(monitor_id, monitor, state)
                        state['stationary_start_time'] = None
                # Don't update anchor while stationary - keep measuring from same point
            else:
                # Moved away from anchor, reset timer and set new anchor
                state['stationary_start_time'] = None
                state['last_position'] = (lat, lon, timestamp)

        elif condition_type == 'anchor_return':
            # Stop recording when vehicle returns inside a fixed anchor location.
            # Paired with anchor_departure start condition.
            anchor_lat = stop_condition.get('anchor_lat')
            anchor_lon = stop_condition.get('anchor_lon')
            radius = stop_condition.get('radius', 100)      # meters
            duration = stop_condition.get('duration', 30)   # seconds

            if anchor_lat is None or anchor_lon is None:
                logger.error(f"Monitor '{monitor_id}': anchor_return requires anchor_lat and anchor_lon")
                return

            distance = self._haversine_distance(anchor_lat, anchor_lon, lat, lon)
            logger.debug(f"Monitor '{monitor_id}': {distance:.1f}m from configured anchor ({anchor_lat},{anchor_lon})")

            if distance <= radius:
                # Inside the anchor zone (returned home)
                if state['stationary_start_time'] is None:
                    state['stationary_start_time'] = timestamp
                    logger.debug(f"Monitor '{monitor_id}': returned inside anchor zone ({distance:.1f}m <= {radius}m radius)")
                else:
                    elapsed = (timestamp - state['stationary_start_time']).total_seconds()
                    if elapsed >= duration:
                        logger.info(f"Monitor '{monitor_id}': STOP trigger (anchor return within {radius}m for {elapsed:.0f}s)")
                        self._trigger_stop(monitor_id, monitor, state)
                        state['stationary_start_time'] = None
            else:
                # Still outside anchor zone, reset timer
                state['stationary_start_time'] = None

        else:
            logger.warning(f"Monitor '{monitor_id}': unknown stop condition type '{condition_type}'")

    def _haversine_distance(self, lat1: float, lon1: float,
                           lat2: float, lon2: float) -> float:
        """
        Calculate distance between two GPS coordinates using Haversine formula.

        Args:
            lat1: Latitude of point 1 (degrees)
            lon1: Longitude of point 1 (degrees)
            lat2: Latitude of point 2 (degrees)
            lon2: Longitude of point 2 (degrees)

        Returns:
            float: Distance in meters
        """
        # Earth radius in meters
        R = 6371000

        # Convert to radians
        lat1_rad = math.radians(lat1)
        lat2_rad = math.radians(lat2)
        delta_lat = math.radians(lat2 - lat1)
        delta_lon = math.radians(lon2 - lon1)

        # Haversine formula
        a = (math.sin(delta_lat / 2) ** 2 +
             math.cos(lat1_rad) * math.cos(lat2_rad) *
             math.sin(delta_lon / 2) ** 2)
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        distance = R * c

        return distance

    def _trigger_start(self, monitor_id: str, monitor: Dict, state: Dict):
        """
        Trigger start callback.

        Args:
            monitor_id: Monitor identifier
            monitor: Monitor dict
            state: State dict
        """
        state['state'] = TriggerState.TRIGGERED

        # Call callback if provided
        if monitor['on_start']:
            try:
                recording_id = monitor['on_start'](monitor_id, monitor['config'])
                state['recording_id'] = recording_id
                logger.info(f"Monitor '{monitor_id}': started recording {recording_id}")
            except Exception as e:
                logger.error(f"Monitor '{monitor_id}': start callback failed: {e}")

    def _trigger_stop(self, monitor_id: str, monitor: Dict, state: Dict):
        """
        Trigger stop callback.

        Args:
            monitor_id: Monitor identifier
            monitor: Monitor dict
            state: State dict
        """
        recording_id = state['recording_id']
        state['state'] = TriggerState.MONITORING
        state['recording_id'] = None

        # Call callback if provided
        if monitor['on_stop']:
            try:
                monitor['on_stop'](monitor_id, recording_id)
                logger.info(f"Monitor '{monitor_id}': stopped recording {recording_id}")
            except Exception as e:
                logger.error(f"Monitor '{monitor_id}': stop callback failed: {e}")

    def get_monitor_status(self) -> Dict:
        """
        Get status of all monitors.

        Returns:
            Dict with monitor statuses
        """
        with self.monitors_lock:
            status = {}
            for monitor_id, monitor in self.monitors.items():
                state = self.monitor_states[monitor_id]
                status[monitor_id] = {
                    'enabled': monitor['enabled'],
                    'state': state['state'].value,
                    'recording_id': state['recording_id'],
                    'has_position': state['last_position'] is not None
                }
            return status

    def shutdown(self):
        """Shutdown monitor gracefully."""
        logger.info("Shutting down GPS trigger monitor")
        self.disconnect()


def main():
    """
    CLI for testing GPS trigger monitor.

    Loads event monitors from the time-appropriate config file in the events
    directory (emon_Suite YYYYMMDD-HHMM.yml pattern), using the same
    ConfigManager as the main service.

    Usage:
        python trigger_monitor.py --config /config/event_recorder_config.yml
        python trigger_monitor.py --config /config/event_recorder_config.yml --events-dir /config/events
        python trigger_monitor.py --broker localhost --port 1883  # fallback test mode
    """
    import argparse
    from .config_manager import ConfigManager

    parser = argparse.ArgumentParser(description="GPS Trigger Monitor Test")
    parser.add_argument('--config',
                        help="Path to event_recorder_config.yml (loads events from adjacent events/ dir)")
    parser.add_argument('--events-dir',
                        help="Override events config directory")
    parser.add_argument('--broker', default='localhost',
                        help="MQTT broker hostname (used when --config is not provided)")
    parser.add_argument('--port', type=int, default=1883,
                        help="MQTT broker port (used when --config is not provided)")
    parser.add_argument('--log-level', default='INFO',
                        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                        help="Logging level (default: INFO)")

    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(level=getattr(logging, args.log_level),
                        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    # Test callbacks
    def on_start(monitor_id, config):
        logger.info(f"*** START TRIGGERED: {monitor_id} ***")
        return 999  # Mock recording ID

    def on_stop(monitor_id, recording_id):
        logger.info(f"*** STOP TRIGGERED: {monitor_id}, recording={recording_id} ***")

    if args.config:
        # Load from config files using ConfigManager (same as main service)
        try:
            config = ConfigManager(args.config, args.events_dir)
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
            raise

        mqtt_config = config.get_mqtt_config()
        broker = mqtt_config['broker']
        port = mqtt_config['port']

        event_configs = config.get_enabled_event_configs()
        if not event_configs:
            logger.warning("No enabled event configs found - nothing to monitor")
            return

        logger.info(f"Loaded {len(event_configs)} enabled event(s): {list(event_configs.keys())}")

        monitor = GPSTriggerMonitor(broker, port)

        try:
            monitor.connect()
            time.sleep(1)  # Allow connection to establish

            for event_name, event_config in event_configs.items():
                monitor.add_monitor(event_name, event_config, on_start, on_stop)
                start_type = event_config.get('start_condition', {}).get('type', '?')
                stop_type = event_config.get('stop_condition', {}).get('type', '?')
                logger.info(f"Monitor '{event_name}': start={start_type}, stop={stop_type}")

            logger.info("Monitoring active. Press Ctrl+C to stop.")

            while True:
                time.sleep(5)
                pos = monitor.get_current_position()
                if pos:
                    lat, lon, _ = pos
                    logger.info(f"Position: {lat:.6f}, {lon:.6f}")
                status = monitor.get_monitor_status()
                for name, s in status.items():
                    logger.info(f"  [{name}] state={s['state']} recording={s['recording_id']} has_pos={s['has_position']}")

        except KeyboardInterrupt:
            logger.info("Interrupted by user")
        finally:
            monitor.shutdown()

    else:
        # Fallback: hardcoded test config when no config file given
        logger.warning("No --config provided, using built-in test config")
        logger.info(f"Broker: {args.broker}:{args.port}")

        test_config = {
            'monitor_topics': ['gps/latitude/0', 'gps/longitude/0'],
            'start_condition': {
                'type': 'gps_movement',
                'distance_threshold': 20,
                'duration': 10
            },
            'stop_condition': {
                'type': 'gps_stopped',
                'distance_threshold': 5,
                'duration': 60
            }
        }

        monitor = GPSTriggerMonitor(args.broker, args.port)

        try:
            monitor.connect()
            monitor.add_monitor('test_monitor', test_config, on_start, on_stop)

            logger.info("Monitoring GPS topics. Press Ctrl+C to stop.")
            logger.info("Publish test messages:")
            logger.info("  mosquitto_pub -h localhost -t 'gps/latitude/0' -m '-31.9505'")
            logger.info("  mosquitto_pub -h localhost -t 'gps/longitude/0' -m '115.8605'")

            while True:
                time.sleep(1)
                pos = monitor.get_current_position()
                if pos:
                    lat, lon, _ = pos
                    logger.info(f"Current position: {lat:.6f}, {lon:.6f}")

        except KeyboardInterrupt:
            logger.info("Interrupted by user")
        finally:
            monitor.shutdown()


if __name__ == '__main__':
    main()
