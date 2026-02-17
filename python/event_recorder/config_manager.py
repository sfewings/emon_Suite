"""
Configuration manager for event recorder.

Loads and manages YAML configuration files with time-based selection
following emon_Suite patterns.
"""

import os
import yaml
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional
import re

logger = logging.getLogger(__name__)


class ConfigManager:
    """
    Manages service and event configurations with time-based YAML file selection.

    Follows emon_Suite pattern of timestamped config files (YYYYMMDD-HHMM.yml).
    """

    def __init__(self, config_path: str, events_dir: str = None):
        """
        Initialize configuration manager.

        Args:
            config_path: Path to main service config file (event_recorder_config.yml)
            events_dir: Optional directory containing event config files
                       If None, looks for 'events' subdirectory next to config_path
        """
        self.config_path = Path(config_path)

        if events_dir:
            self.events_dir = Path(events_dir)
        else:
            # Default: events/ subdirectory next to config file
            self.events_dir = self.config_path.parent / 'events'

        self.service_config = None
        self.event_configs = {}
        self.last_scan_time = None

        logger.info(f"ConfigManager initialized")
        logger.info(f"  Service config: {self.config_path}")
        logger.info(f"  Events directory: {self.events_dir}")

        # Load configurations
        self.reload()

    def reload(self):
        """Reload all configuration files."""
        self._load_service_config()
        self._load_event_configs()

    def _load_service_config(self):
        """Load main service configuration file."""
        if not self.config_path.exists():
            raise FileNotFoundError(f"Service config not found: {self.config_path}")

        with open(self.config_path, 'r') as f:
            self.service_config = yaml.safe_load(f)

        # Substitute environment variables
        self.service_config = self._substitute_env_vars(self.service_config)

        logger.info(f"Loaded service config from {self.config_path}")

    def _load_event_configs(self):
        """
        Load event configuration files with time-based selection.

        Scans events directory for YYYYMMDD-HHMM.yml files and selects
        the most recent file <= current time (emon_Suite pattern).
        """
        if not self.events_dir.exists():
            logger.warning(f"Events directory not found: {self.events_dir}")
            self.event_configs = {}
            return

        # Get all .yml files in events directory
        config_files = list(self.events_dir.glob('*.yml'))

        if not config_files:
            logger.warning(f"No event config files found in {self.events_dir}")
            self.event_configs = {}
            return

        # Parse timestamped files and find most recent <= now
        current_time = datetime.now()
        timestamped_files = []

        for file_path in config_files:
            match = re.match(r'(\d{8})-(\d{4})\.yml', file_path.name)
            if match:
                date_str = match.group(1)  # YYYYMMDD
                time_str = match.group(2)  # HHMM

                try:
                    file_time = datetime.strptime(f"{date_str}{time_str}", "%Y%m%d%H%M")
                    timestamped_files.append((file_time, file_path))
                except ValueError:
                    logger.warning(f"Invalid timestamp in filename: {file_path.name}")
                    continue

        # Sort by timestamp and find most recent <= current_time
        timestamped_files.sort(key=lambda x: x[0], reverse=True)

        config_file = None
        for file_time, file_path in timestamped_files:
            if file_time <= current_time:
                config_file = file_path
                break

        if not config_file:
            logger.warning("No suitable time-based config found, will check for default")
            # Try to find a default config file
            default_config = self.events_dir / 'events_config.yml'
            if default_config.exists():
                config_file = default_config
            else:
                self.event_configs = {}
                return

        # Load the selected config file
        with open(config_file, 'r') as f:
            config_data = yaml.safe_load(f)

        # Substitute environment variables
        config_data = self._substitute_env_vars(config_data)

        # Extract events
        if 'events' in config_data:
            self.event_configs = config_data['events']
            logger.info(f"Loaded {len(self.event_configs)} event configs from {config_file.name}")
        else:
            logger.warning(f"No 'events' section found in {config_file.name}")
            self.event_configs = {}

        self.last_scan_time = current_time

    def _substitute_env_vars(self, config: Dict) -> Dict:
        """
        Recursively substitute environment variables in config.

        Supports ${VAR_NAME} syntax.

        Args:
            config: Configuration dict

        Returns:
            Dict with substituted values
        """
        if isinstance(config, dict):
            return {k: self._substitute_env_vars(v) for k, v in config.items()}
        elif isinstance(config, list):
            return [self._substitute_env_vars(item) for item in config]
        elif isinstance(config, str):
            # Find ${VAR_NAME} patterns
            pattern = r'\$\{([^}]+)\}'
            matches = re.findall(pattern, config)
            for var_name in matches:
                var_value = os.environ.get(var_name, '')
                if not var_value:
                    logger.warning(f"Environment variable not set: {var_name}")
                config = config.replace(f"${{{var_name}}}", var_value)
            return config
        else:
            return config

    def get_service_config(self) -> Dict:
        """
        Get main service configuration.

        Returns:
            Dict: Service configuration
        """
        return self.service_config

    def get_event_configs(self) -> Dict[str, Dict]:
        """
        Get all event configurations.

        Returns:
            Dict mapping event name to config dict
        """
        return self.event_configs

    def get_event_config(self, event_name: str) -> Optional[Dict]:
        """
        Get specific event configuration by name.

        Args:
            event_name: Event configuration name

        Returns:
            Dict with event config or None if not found
        """
        return self.event_configs.get(event_name)

    def get_enabled_event_configs(self) -> Dict[str, Dict]:
        """
        Get only enabled event configurations.

        Returns:
            Dict mapping event name to config dict (only enabled)
        """
        return {
            name: config
            for name, config in self.event_configs.items()
            if config.get('enabled', True)
        }

    def check_and_reload(self, force: bool = False):
        """
        Check if new config files are available and reload if needed.

        Args:
            force: Force reload even if no new files
        """
        if force:
            logger.info("Force reloading configurations")
            self.reload()
            return

        # Check if events directory has new files (timestamp-based)
        if not self.events_dir.exists():
            return

        current_time = datetime.now()

        # Only check every 60 seconds
        if self.last_scan_time and (current_time - self.last_scan_time).seconds < 60:
            return

        # Find most recent config file
        config_files = list(self.events_dir.glob('*.yml'))
        timestamped_files = []

        for file_path in config_files:
            match = re.match(r'(\d{8})-(\d{4})\.yml', file_path.name)
            if match:
                date_str = match.group(1)
                time_str = match.group(2)
                try:
                    file_time = datetime.strptime(f"{date_str}{time_str}", "%Y%m%d%H%M")
                    if file_time <= current_time:
                        timestamped_files.append((file_time, file_path))
                except ValueError:
                    continue

        if not timestamped_files:
            return

        # Get most recent applicable file
        timestamped_files.sort(key=lambda x: x[0], reverse=True)
        latest_file_time = timestamped_files[0][0]

        # If newer than last scan, reload
        if not self.last_scan_time or latest_file_time > self.last_scan_time:
            logger.info(f"New configuration file detected, reloading")
            self._load_event_configs()

    # === Convenience methods for accessing nested config values ===

    def get(self, key_path: str, default=None):
        """
        Get configuration value using dot notation.

        Args:
            key_path: Dot-separated path (e.g., "service.mqtt_broker")
            default: Default value if not found

        Returns:
            Configuration value or default

        Example:
            config.get("service.mqtt_broker") -> "mqtt"
            config.get("wordpress.default_site.site_url") -> "https://..."
        """
        keys = key_path.split('.')
        value = self.service_config

        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default

        return value

    def get_mqtt_config(self) -> Dict:
        """Get MQTT broker configuration."""
        return {
            'broker': self.get('service.mqtt_broker', 'localhost'),
            'port': self.get('service.mqtt_port', 1883),
        }

    def get_database_path(self) -> str:
        """Get database file path."""
        return self.get('service.database_path', '/data/recordings.db')

    def get_plots_dir(self) -> str:
        """Get plots output directory."""
        return self.get('plots_dir', '/data/plots')

    def get_wordpress_config(self, site: str = 'default_site') -> Dict:
        """
        Get WordPress site configuration.

        Args:
            site: Site identifier (default: 'default_site')

        Returns:
            Dict with WordPress config (site_url, username, password, etc.)
        """
        return self.get(f'wordpress.{site}', {})

    def get_recording_config(self) -> Dict:
        """Get recording parameters (buffer size, flush interval, etc.)."""
        return self.get('recording', {})

    def get_plot_config(self) -> Dict:
        """Get plot generation defaults (dpi, dimensions, style)."""
        return self.get('plots', {})

    def validate_config(self) -> List[str]:
        """
        Validate configuration and return list of errors.

        Returns:
            List of error messages (empty if valid)
        """
        errors = []

        # Check required service config sections
        required_sections = ['service', 'recording', 'plots', 'wordpress']
        for section in required_sections:
            if section not in self.service_config:
                errors.append(f"Missing required section: {section}")

        # Check required service fields
        if 'service' in self.service_config:
            service = self.service_config['service']
            required_fields = ['mqtt_broker', 'database_path', 'plots_dir']
            for field in required_fields:
                if field not in service:
                    errors.append(f"Missing required field: service.{field}")

        # Validate event configs
        for event_name, event_config in self.event_configs.items():
            required_event_fields = ['monitor_topics', 'start_condition',
                                    'stop_condition', 'record_topics']
            for field in required_event_fields:
                if field not in event_config:
                    errors.append(f"Event '{event_name}': missing required field '{field}'")

            # Validate condition structure
            for condition_type in ['start_condition', 'stop_condition']:
                if condition_type in event_config:
                    condition = event_config[condition_type]
                    if 'type' not in condition:
                        errors.append(f"Event '{event_name}': {condition_type} missing 'type' field")

        return errors


def main():
    """
    CLI for testing configuration loading.

    Usage:
        python config_manager.py [config_path] [events_dir]
    """
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Event Recorder Configuration Manager")
    parser.add_argument('config_path', nargs='?',
                       default='/config/event_recorder_config.yml',
                       help="Path to service config file")
    parser.add_argument('--events-dir',
                       help="Path to events config directory")
    parser.add_argument('--validate', action='store_true',
                       help="Validate configuration")

    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(level=logging.INFO,
                       format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    try:
        config = ConfigManager(args.config_path, args.events_dir)

        print("\n=== Service Configuration ===")
        print(json.dumps(config.get_service_config(), indent=2, default=str))

        print("\n=== Event Configurations ===")
        for name, event_config in config.get_event_configs().items():
            print(f"\n{name}:")
            print(json.dumps(event_config, indent=2, default=str))

        if args.validate:
            print("\n=== Validation ===")
            errors = config.validate_config()
            if errors:
                print("Errors found:")
                for error in errors:
                    print(f"  - {error}")
            else:
                print("✓ Configuration is valid")

    except Exception as e:
        logger.error(f"Failed to load configuration: {e}")
        raise


if __name__ == '__main__':
    main()
