#!/usr/bin/env python
"""
Startup script for Emon Settings Manager Web Interface

This script makes it easy to start the settings web server without needing
to remember the Python command or module paths. It supports both Flask dev
mode and production mode with Gunicorn.

Usage:
    Windows:
        python start_settings_manager.py [--settings-path ./config] [--port 5000] [--debug]
    
    Linux/Mac:
        ./start_settings_manager.py [--settings-path ./config] [--port 5000] [--debug]
    
    With Gunicorn:
        python start_settings_manager.py --settings-path ./config --port 5000 --use-gunicorn
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

# Global app variable for gunicorn
app = None

def create_app(settings_path, port):
    """Create and configure the Flask app."""
    web_interface = SettingsWebInterface(
        settings_path=str(settings_path),
        port=port
    )
    return web_interface.app

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
  
  python start_settings_manager.py --settings-path ./config --port 5000 --use-gunicorn
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
        help='Enable debug mode with auto-reload (Flask dev server only)'
    )
    
    parser.add_argument(
        '--use-gunicorn',
        action='store_true',
        help='Use Gunicorn as production web server (overrides --debug)'
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
        
        if args.use_gunicorn:
            # Use Gunicorn for production
            try:
                import gunicorn.app.base
                
                class GunicornApp(gunicorn.app.base.BaseApplication):
                    def __init__(self, app, options=None):
                        self.application = app
                        self.options = options or {}
                        super().__init__()
                    
                    def load_config(self):
                        for key, value in self.options.items():
                            self.cfg.set(key.lower(), value)
                    
                    def load(self):
                        return self.application
                
                print(f"\n{'='*60}")
                print("Emon Settings Management Web Interface (Gunicorn)")
                print(f"{'='*60}")
                print(f"Settings Path: {settings_path}")
                print(f"Server: http://0.0.0.0:{args.port}")
                print(f"Open your browser and navigate to http://localhost:{args.port}")
                print(f"{'='*60}\n")
                
                flask_app = create_app(settings_path, args.port)
                
                gunicorn_options = {
                    'bind': f'0.0.0.0:{args.port}',
                    'workers': 1,
                    'timeout':120,
                    'access_log_format': '%({X-Forwarded-For}i)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s"',
                    'accesslog': '-',
                    'errorlog': '-',
                }
                
                gunicorn_app = GunicornApp(flask_app, gunicorn_options)
                gunicorn_app.run()
                
            except ImportError:
                print("Error: Gunicorn is not installed.")
                print("\nInstall it with:")
                print("  pip install gunicorn")
                sys.exit(1)
        else:
            # Use Flask development server
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
