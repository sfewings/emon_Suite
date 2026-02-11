#!/usr/bin/env python
"""
Startup script for Emon Settings Manager Web Interface

This script makes it easy to start the settings web server without needing
to remember the Python command or module paths.

Usage:
    Windows:
        python start_settings_manager.py [--settings-path ./config] [--port 5000] [--debug]
    
    Linux/Mac:
        ./start_settings_manager.py [--settings-path ./config] [--port 5000] [--debug]
"""

import sys
import os
from pathlib import Path

# Try to import the required modules
try:
    import flask
except ImportError:
    print("Error: Flask is not installed.")
    print("\nInstall required dependencies with:")
    print("  pip install flask pyyaml")
    sys.exit(1)

try:
    import yaml
except ImportError:
    print("Error: PyYAML is not installed.")
    print("\nInstall required dependencies with:")
    print("  pip install flask pyyaml")
    sys.exit(1)

# Add pyemonlib to path
current_dir = Path(__file__).parent
sys.path.insert(0, str(current_dir))

try:
    from emon_settings_web import SettingsWebInterface
except ImportError as e:
    print(f"Error: Could not import emon_settings_web: {e}")
    print("\nMake sure this script is in the pyemonlib directory.")
    sys.exit(1)

import argparse

def main():
    parser = argparse.ArgumentParser(
        prog='Emon Settings Manager',
        description='Web-based settings file manager for emon applications',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python start_settings_manager.py
  
  python start_settings_manager.py --settings-path /path/to/config
  
  python start_settings_manager.py --port 8080
  
  python start_settings_manager.py --settings-path ./config --port 5000 --debug
        """
    )
    
    parser.add_argument(
        '--settings-path',
        default='./emon_config.yml',
        help='Path to settings file or directory (default: ./emon_config.yml)'
    )
    
    parser.add_argument(
        '--port',
        type=int,
        default=5000,
        help='Port to run server on (default: 5000)'
    )
    
    parser.add_argument(
        '--debug',
        action='store_true',
        help='Enable debug mode with auto-reload'
    )
    
    args = parser.parse_args()
    
    try:
        # Verify settings path exists or can be created
        settings_path = Path(args.settings_path)
        if not settings_path.exists():
            print(f"Note: Settings path does not exist: {args.settings_path}")
            if settings_path.suffix == '':  # It's a directory
                print(f"Creating directory: {args.settings_path}")
                settings_path.mkdir(parents=True, exist_ok=True)
        
        # Create and run web interface
        web_interface = SettingsWebInterface(
            settings_path=str(settings_path),
            port=args.port
        )
        
        web_interface.run(debug=args.debug)
        
    except KeyboardInterrupt:
        print("\n\nShutting down...")
        sys.exit(0)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
