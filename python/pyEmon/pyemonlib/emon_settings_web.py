"""
Web interface for managing emon settings files.

Provides REST API endpoints for:
- Listing available settings files
- Reading settings file contents
- Creating new settings files
- Modifying existing settings files
- Validating YAML syntax

Usage:
    python emon_settings_web.py --settings-path ./config/ --port 5000
"""

import os
import sys
import json
import yaml
import argparse
import datetime
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_from_directory
from werkzeug.exceptions import BadRequest

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(__file__))
from emon_settings import EmonSettings


class SettingsWebInterface:
    """Web interface for emon settings management."""
    
    def __init__(self, settings_path="./emon_config.yml", port=5000):
        """
        Initialize the web interface.
        
        Args:
            settings_path: Path to settings file or directory
            port: Port to run Flask server on
        """
        self.settings_manager = EmonSettings(settings_path)
        self.port = port
        self.app = Flask(__name__, 
                        template_folder=os.path.join(os.path.dirname(__file__), 'web_templates'),
                        static_folder=os.path.join(os.path.dirname(__file__), 'web_static'))
        
        # Register routes
        self._register_routes()
    
    def _register_routes(self):
        """Register Flask routes."""
        
        @self.app.route('/')
        def index():
            """Serve main web interface."""
            return render_template('index.html')
        
        @self.app.route('/static/<path:filename>')
        def serve_static(filename):
            """Serve static files."""
            return send_from_directory(self.app.static_folder, filename)
        
        @self.app.route('/api/settings/list', methods=['GET'])
        def list_settings():
            """Get list of available settings files."""
            try:
                files_dict = self.settings_manager.get_available_settings_files()
                current = self.settings_manager.get_current_settings_file()
                
                return jsonify({
                    'success': True,
                    'files': [
                        {
                            'filename': dt_tuple[1],
                            'path': dt_tuple[2],
                            'datetime': dt_tuple[0].isoformat() if dt_tuple[0] else None,
                            'isCurrent': dt_tuple[2] == current
                        }
                        for dt_tuple in files_dict.values()
                    ],
                    'current': current
                })
            except Exception as e:
                return jsonify({'success': False, 'error': str(e)}), 500
        
        @self.app.route('/api/settings/read/<filename>', methods=['GET'])
        def read_settings(filename):
            """Read contents of a settings file."""
            try:
                # Security: prevent directory traversal
                if '..' in filename or '/' in filename or '\\' in filename:
                    raise BadRequest('Invalid filename')
                
                files_dict = self.settings_manager.get_available_settings_files()
                filepath = None
                
                # Get the file path from the dictionary
                if filename in files_dict:
                    filepath = files_dict[filename][2]  # Extract full_path from tuple
                
                if not filepath or not os.path.exists(filepath):
                    return jsonify({'success': False, 'error': 'File not found'}), 404
                
                with open(filepath, 'r') as f:
                    content = f.read()
                
                return jsonify({
                    'success': True,
                    'filename': filename,
                    'content': content
                })
            except Exception as e:
                return jsonify({'success': False, 'error': str(e)}), 500
        
        @self.app.route('/api/settings/validate', methods=['POST'])
        def validate_settings():
            """Validate YAML syntax."""
            try:
                data = request.get_json()
                yaml_content = data.get('content', '')
                
                # Try to parse YAML
                yaml.safe_load(yaml_content)
                
                return jsonify({
                    'success': True,
                    'valid': True,
                    'message': 'YAML syntax is valid'
                })
            except yaml.YAMLError as e:
                return jsonify({
                    'success': True,
                    'valid': False,
                    'message': str(e)
                })
            except Exception as e:
                return jsonify({
                    'success': False,
                    'error': str(e)
                }), 500
        
        @self.app.route('/api/settings/save', methods=['POST'])
        def save_settings():
            """Save a new or modified settings file."""
            try:
                data = request.get_json()
                filename = data.get('filename', '')
                content = data.get('content', '')
                
                # Validate filename format
                if not filename:
                    return jsonify({
                        'success': False,
                        'error': 'Filename is required'
                    }), 400
                
                # Check if it's a timestamped filename (YYYYMMDD-hhmm.yml or emon_config.yml)
                if filename != 'emon_config.yml':
                    # Validate timestamped format
                    pattern = r'^\d{8}-\d{4}\.yml$'
                    if not __import__('re').match(pattern, filename):
                        return jsonify({
                            'success': False,
                            'error': f'Invalid filename format. Use YYYYMMDD-hhmm.yml format (e.g., 20250122-1430.yml) or emon_config.yml'
                        }), 400
                
                # Validate YAML syntax
                try:
                    yaml.safe_load(content)
                except yaml.YAMLError as e:
                    return jsonify({
                        'success': False,
                        'error': f'Invalid YAML syntax: {str(e)}'
                    }), 400
                
                # Determine target directory
                if os.path.isdir(self.settings_manager.settingsPath):
                    target_dir = self.settings_manager.settingsPath
                else:
                    target_dir = os.path.dirname(self.settings_manager.settingsPath) or '.'
                
                # Create directory if it doesn't exist
                os.makedirs(target_dir, exist_ok=True)
                
                # Save file
                filepath = os.path.join(target_dir, filename)
                with open(filepath, 'w') as f:
                    f.write(content)
                
                # Reload settings manager to pick up new file
                self.settings_manager.reload_settings()
                
                return jsonify({
                    'success': True,
                    'message': f'Settings saved to {filename}',
                    'filename': filename,
                    'filepath': filepath
                })
            except Exception as e:
                return jsonify({
                    'success': False,
                    'error': str(e)
                }), 500
        
        @self.app.route('/api/settings/delete/<filename>', methods=['POST'])
        def delete_settings(filename):
            """Delete a settings file."""
            try:
                # Security: prevent directory traversal
                if '..' in filename or '/' in filename or '\\' in filename:
                    raise BadRequest('Invalid filename')
                
                # Don't allow deleting the main config file
                if filename == 'emon_config.yml':
                    return jsonify({
                        'success': False,
                        'error': 'Cannot delete emon_config.yml'
                    }), 400
                
                files = self.settings_manager.get_available_settings_files()
                filepath = None
                
                for f in files:
                    if f['filename'] == filename:
                        filepath = f['path']
                        break
                
                if not filepath or not os.path.exists(filepath):
                    return jsonify({
                        'success': False,
                        'error': 'File not found'
                    }), 404
                
                os.remove(filepath)
                
                # Reload settings manager
                self.settings_manager.reload_settings()
                
                return jsonify({
                    'success': True,
                    'message': f'{filename} deleted successfully'
                })
            except Exception as e:
                return jsonify({
                    'success': False,
                    'error': str(e)
                }), 500
        
        @self.app.route('/api/settings/current', methods=['GET'])
        def get_current_settings():
            """Get currently loaded settings."""
            try:
                settings = self.settings_manager.get_settings()
                current_file = self.settings_manager.get_current_settings_file()
                
                return jsonify({
                    'success': True,
                    'currentFile': current_file,
                    'settings': settings if isinstance(settings, dict) else {}
                })
            except Exception as e:
                return jsonify({
                    'success': False,
                    'error': str(e)
                }), 500
    
    def run(self, debug=False):
        """Start the Flask server."""
        print(f"\n{'='*60}")
        print("Emon Settings Management Web Interface")
        print(f"{'='*60}")
        print(f"Settings Path: {self.settings_manager.settingsPath}")
        print(f"Server: http://localhost:{self.port}")
        print(f"Open your browser and navigate to http://localhost:{self.port}")
        print(f"{'='*60}\n")
        
        self.app.run(host='0.0.0.0', port=self.port, debug=debug)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Emon Settings Management Web Interface',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run with default settings
  python emon_settings_web.py
  
  # Run with custom settings directory
  python emon_settings_web.py --settings-path /path/to/config
  
  # Run on custom port
  python emon_settings_web.py --port 8080
  
  # Run in debug mode
  python emon_settings_web.py --debug
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
        help='Enable debug mode'
    )
    
    args = parser.parse_args()
    
    # Validate settings path exists
    if not os.path.exists(args.settings_path):
        print(f"Warning: Settings path does not exist: {args.settings_path}")
        print(f"Creating directory: {args.settings_path}")
        os.makedirs(args.settings_path, exist_ok=True)
    
    # Create and run web interface
    web_interface = SettingsWebInterface(
        settings_path=args.settings_path,
        port=args.port
    )
    
    web_interface.run(debug=args.debug)


if __name__ == '__main__':
    main()
