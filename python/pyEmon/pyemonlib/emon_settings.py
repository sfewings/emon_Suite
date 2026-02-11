"""
Shared settings management module for emon applications.

Handles loading and managing multiple timestamped settings files with automatic
selection based on time. Supports both legacy emon_config.yml and new YYYYMMDD-hhmm.yml
timestamped settings files.

Usage:
    settings_manager = EmonSettings(settingsPath="./config/")
    settings = settings_manager.get_settings()
    settings_manager.check_and_reload_settings()
"""

import time
import datetime
import os
import yaml
import re


class EmonSettings:
    """
    Manages settings file loading and reloading with support for timestamped configuration files.
    
    Files are expected to be named in YYYYMMDD-hhmm.yml format, representing the date and time
    from which the settings file should be used. The legacy emon_config.yml format is also
    supported as a fallback.
    """
    
    def __init__(self, settingsPath="./emon_config.yml"):
        """
        Initialize the settings manager.
        
        Args:
            settingsPath: Path to settings file or directory containing settings files
        """
        self.settingsPath = settingsPath
        if( os.path.isdir(settingsPath) ):
            self.settingsDirectory = settingsPath
        else:
            self.settingsDirectory = os.path.dirname(settingsPath) or "."
        self.currentSettingsFile = None
        self.availableSettingsFiles = {}  # Dictionary: filename -> (datetime, filename, full_path) tuple
        self.lastSettingsFileCheck = 0
        self.settingsCheckInterval = 60  # Check for new settings files every 60 seconds
        self.settings = {}
        self.currentNodes = []
        print(f"Initializing EmonSettings with path: {self.settingsPath}, directory: {self.settingsDirectory}")
        # Load initial settings
        self._load_settings()
    
    def _parse_settings_filename(self, filename):
        """
        Parse a settings filename to extract the datetime.
        Expects format: YYYYMMDD-hhmm.yml
        
        Args:
            filename: Filename to parse
            
        Returns:
            timezone-aware datetime object if valid format, None otherwise
        """
        if not filename.endswith('.yml'):
            return None
        
        base = filename[:-4]  # Remove .yml extension
        if not re.match(r'^\d{8}-\d{4}$', base):
            return None
        
        try:
            date_str = base[:8]  # YYYYMMDD
            time_str = base[9:13]  # hhmm
            datetime_str = f"{date_str}{time_str}"
            naive_dt = datetime.datetime.strptime(datetime_str, "%Y%m%d%H%M")
            
            # Get local timezone offset
            local_tz = datetime.datetime.now().astimezone().tzinfo
            
            # Return timezone-aware datetime
            return naive_dt.replace(tzinfo=local_tz)
        except ValueError:
            return None
    
    def _scan_settings_files(self):
        """
        Scan the settings directory for all valid settings files.
        
        Returns:
            Dictionary with filename as key and (datetime, filename, full_path) tuple as value
            Chronologically organized with emon_config.yml as fallback
        """
        settings_files = {}
        
        if not os.path.isdir(self.settingsDirectory):
            return settings_files
        
        try:
            for filename in os.listdir(self.settingsDirectory):
                if filename == "emon_config.yml":
                    # Support the legacy single config file
                    dt = datetime.datetime.max.replace(tzinfo=datetime.datetime.now().astimezone().tzinfo)
                    settings_files[filename] = (dt, filename, os.path.join(self.settingsDirectory, filename))
                else:
                    dt = self._parse_settings_filename(filename)
                    if dt is not None:
                        full_path = os.path.join(self.settingsDirectory, filename).replace('\\', '/')
                        settings_files[filename] = (dt, filename, full_path)
        except Exception as e:
            print(f"Error scanning settings directory: {e}")
        
        return settings_files
    
    def _get_applicable_settings_file(self, current_time=None):
        """
        Determine which settings file should be used for the given time.
        
        Selects the most recent file whose timestamp is <= current_time.
        Falls back to emon_config.yml if no timestamped files match.
        
        Args:
            current_time: datetime object (defaults to current system time if None)
            
        Returns:
            Full path to applicable settings file, or None if none found
        """
        if current_time is None:
            current_time = datetime.datetime.now().astimezone()
        
        applicable_file = None
     
        
        # Sort files by datetime and find the most recent one <= current_time
        sorted_files = sorted(self.availableSettingsFiles.values(), key=lambda x: x[0])
        applicable_file = sorted_files[0][2] if sorted_files else None  # Default to first file if none match

        for dt, filename, full_path in sorted_files:
            if dt <= current_time:
                applicable_file = full_path
            else:
                break  # Since list is sorted, no later files will match
        
        # If no dated file matches, use the legacy emon_config.yml if it exists
        if applicable_file is None:
            legacy_path = os.path.join(self.settingsDirectory, "emon_config.yml")
            if os.path.isfile(legacy_path):
                applicable_file = legacy_path
        
        # If still no file, try the original settingsPath
        if applicable_file is None:
            if os.path.isfile(self.settingsPath):
                applicable_file = self.settingsPath
        
        return applicable_file
    
    def _load_settings_from_file(self, filepath):
        """
        Load and parse a settings YAML file.
        
        Args:
            filepath: Path to settings file
            
        Returns:
            Parsed settings dict on success, None on failure
        """
        try:
            with open(filepath, 'r') as settingsFile:
                settings = yaml.full_load(settingsFile)
                #keep track of current nodes; "temp", "disp", etc.
                self.currentNodes = []
                for key in settings:
                    self.currentNodes.append(key)
                self.currentNodes.append('base')

                return settings
        except Exception as e:
            print(f"Error loading settings file {filepath}: {e}")
            return None
    
    def _load_settings(self, current_time=None):
        """
        Load settings from the appropriate file based on current time.
        
        Scans for timestamped files and selects the appropriate one.
        Falls back to emon_config.yml if no timestamped files are found.
        
        Args:
            current_time: datetime object to determine applicable file (defaults to current system time if None)
        """
        self.availableSettingsFiles = self._scan_settings_files()
        applicable_file = self._get_applicable_settings_file(current_time)
        
        if applicable_file is None:
            print(f"Error: No settings file found in {self.settingsDirectory}")
            self.settings = {}
            self.currentSettingsFile = None
            return
        
        settings = self._load_settings_from_file(applicable_file)
        if settings is not None:
            self.settings = settings
            self.currentSettingsFile = applicable_file
            print(f"Loaded settings from: {os.path.basename(applicable_file)}")
        else:
            if self.settings is None:
                self.settings = {}
            print(f"Failed to load settings from {applicable_file}, using previous settings")
    
    def check_and_reload_settings(self):
        """
        Periodically check if new settings files have been created or if the current time
        requires switching to a different settings file (using system time).
        
        Should be called at appropriate intervals during message processing.
        
        Returns:
            True if settings were reloaded, False if no changes needed
        """
        current_time = time.time()
        
        # Only check at specified intervals
        if current_time - self.lastSettingsFileCheck < self.settingsCheckInterval:
            return False
        
        self.lastSettingsFileCheck = current_time
        
        # Scan for any new files
        new_files = self._scan_settings_files()
        
        # Check if the list of available files has changed
        if new_files != self.availableSettingsFiles:
            print("New settings files detected, rescanning...")
            self.availableSettingsFiles = new_files
        
        # Determine which file should be used now
        applicable_file = self._get_applicable_settings_file()
        
        # If the applicable file has changed, reload settings
        if applicable_file != self.currentSettingsFile:
            print(f"Switching settings from {self.currentSettingsFile} to {applicable_file}")
            self._load_settings()
            return True  # Settings were reloaded
        
        return False  # No changes needed
    
    def check_and_reload_settings_by_time(self, current_time=None):
        """
        Check if new settings files have been created and determine which settings file
        to use based on the provided time (useful for historical data).
        
        This is useful when processing historical log data with timestamps that may span
        different settings periods.
        
        Args:
            current_time: datetime object representing the time to check against.
                         If None, uses system time.
        
        Returns:
            True if settings were reloaded, False if no changes needed
        """
        # Periodically scan for new files
        current_epoch = time.time()
        if current_epoch - self.lastSettingsFileCheck >= self.settingsCheckInterval:
            self.lastSettingsFileCheck = current_epoch
            
            # Scan for any new files
            new_files = self._scan_settings_files()
            
            # Check if the list of available files has changed
            if new_files != self.availableSettingsFiles:
                print("New settings files detected, rescanning...")
                self.availableSettingsFiles = new_files
        
        # Determine which file should be used for the given time
        if current_time is None:
            current_time = datetime.datetime.now().astimezone()
        
        applicable_file = self._get_applicable_settings_file(current_time)
        
        # If the applicable file has changed, reload settings
        if applicable_file != self.currentSettingsFile:
            print(f"Switching settings from {os.path.basename(self.currentSettingsFile)} to {os.path.basename(applicable_file)} (for time {current_time})")
            #self.currentSettingsFile = applicable_file 
            self._load_settings(current_time)
            return True  # Settings were reloaded
        
        return False  # No changes needed
    
    def get_settings(self):
        """
        Get the currently loaded settings dictionary.
        
        Returns:
            Dictionary of settings loaded from the current settings file
        """
        return self.settings
    
    def get_current_settings_file(self):
        """
        Get the path to the currently loaded settings file.
        
        Returns:
            Full path to current settings file, or None if not loaded
        """
        return self.currentSettingsFile
    
    def get_available_settings_files(self):
        """
        Get all available settings files.
        
        Returns:
            Dictionary with filename as key and (datetime, filename, full_path) tuple as value
        """
        return self.availableSettingsFiles
    def get_current_nodes(self):
        """
        Get the list of current nodes from the loaded settings.
        
        Returns:
            List of node names
        """
        return self.currentNodes
    
    def reload_settings(self):
        """
        Force an immediate reload of settings from the appropriate file.
        """
        self._load_settings()
