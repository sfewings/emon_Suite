"""
Data processor for generating plots and statistics from recorded data.

Uses matplotlib for time-series plots and folium for GPS route maps.
Calculates statistics including distance, speed, energy consumption.
"""

import bisect
import logging
import math
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import json

# Matplotlib configuration (must be before pyplot import)
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend for Docker
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.ticker import MaxNLocator
import numpy as np

from .models import Database, RecordingStatus, ImageType

logger = logging.getLogger(__name__)


class DataProcessor:
    """
    Processes recorded data to generate plots and statistics.

    Handles:
    - Time-series line plots
    - Multi-metric comparison plots
    - GPS route maps (folium)
    - Statistics calculation
    - Statistics summary tables
    """

    def __init__(self, database: Database, plots_dir: str = "/data/plots"):
        """
        Initialize data processor.

        Args:
            database: Database instance
            plots_dir: Directory for plot output
        """
        self.database = database
        self.plots_dir = Path(plots_dir)
        self.plots_dir.mkdir(parents=True, exist_ok=True)

        # Plot defaults
        self.default_dpi = 150
        self.default_width = 12
        self.default_height = 6
        self.default_style = 'seaborn-v0_8'

        logger.info(f"DataProcessor initialized (plots_dir={plots_dir})")

    def _auto_generate_plot_config(self, recording_id: int) -> List[Dict]:
        """
        Auto-generate plot configurations from recorded topics.

        Queries the database for all topics in the recording and creates
        a line plot for each numeric topic. GPS latitude/longitude pairs
        are combined into a route map instead of individual line plots.

        Args:
            recording_id: Recording ID

        Returns:
            List of plot configuration dicts
        """
        topics = self.database.get_recording_topics(recording_id)
        if not topics:
            return []

        plot_config = []
        skip_topics = set()

        # Check for GPS lat/lon pair → route map
        lat_topics = [t for t in topics if 'latitude' in t.lower()]
        lon_topics = [t for t in topics if 'longitude' in t.lower()]

        for i, lat_topic in enumerate(lat_topics):
            # Find matching longitude topic: primary strategy is direct string replacement
            # e.g. "gps/latitude/0" → "gps/longitude/0"
            expected_lon = lat_topic.replace('latitude', 'longitude')
            matching_lon = [t for t in lon_topics if t == expected_lon]
            if not matching_lon:
                # Fallback: suffix matching for non-standard topic formats
                suffix = lat_topic.split('latitude')[-1]
                if suffix:
                    matching_lon = [t for t in lon_topics if t.endswith(suffix)]
            if matching_lon:
                # Use a unique title per GPS stream so each map gets its own filename.
                # With a single stream the title is plain "Route Map"; with multiple
                # streams it becomes "Route Map 0", "Route Map 1", etc.
                title = 'Route Map' if len(lat_topics) == 1 else f'Route Map {i}'
                plot_config.append({
                    'type': 'map',
                    'title': title,
                    'topics': [lat_topic, matching_lon[0]]
                })
                skip_topics.add(lat_topic)
                skip_topics.add(matching_lon[0])

        # Generate line plot for each remaining topic
        for topic in topics:
            if topic in skip_topics:
                continue

            # Build a readable title from topic path
            title = self._topic_to_title(topic)

            plot_config.append({
                'type': 'line',
                'title': title,
                'topics': [topic],
                'ylabel': 'Value',
                'color': '#667eea'
            })

        logger.info(f"Auto-generated {len(plot_config)} plot configs from {len(topics)} topics")
        return plot_config

    def _topic_to_title(self, topic: str) -> str:
        """Convert MQTT topic path to readable plot title."""
        # e.g. "gps/speed/0" → "GPS Speed 0"
        # e.g. "rssi/Breaksea location" → "RSSI Breaksea Location"
        # e.g. "scale/1" → "Scale 1"
        parts = topic.replace('/', ' ').split()
        titled = []
        for part in parts:
            if part.isnumeric():
                titled.append(part)
            elif len(part) <= 4 and part.isalpha():
                titled.append(part.upper())
            else:
                titled.append(part.capitalize())
        return ' '.join(titled)

    def process_recording(self, recording_id: int, plot_config: List[Dict] = None) -> Dict:
        """
        Process recording: generate plots and calculate statistics.

        If plot_config is empty or None, auto-generates plots for all
        recorded topics.

        Args:
            recording_id: Recording ID
            plot_config: List of plot configuration dicts (optional)

        Returns:
            Dict with processing results:
            {
                'plots': [list of image paths],
                'statistics': {stats dict},
                'status': 'success' or 'failed',
                'error': error message if failed
            }
        """
        logger.info(f"Processing recording {recording_id}")

        # Update status
        self.database.update_recording(recording_id, status=RecordingStatus.PROCESSING)

        try:
            # Create output directory for this recording
            output_dir = self.plots_dir / str(recording_id)
            output_dir.mkdir(parents=True, exist_ok=True)

            results = {
                'plots': [],
                'statistics': {},
                'status': 'success'
            }

            # Auto-generate plot config if none provided
            if not plot_config:
                plot_config = self._auto_generate_plot_config(recording_id)

            # Generate plots
            if plot_config:
                logger.info(f"Generating {len(plot_config)} plots")
                for plot_spec in plot_config:
                    try:
                        plot_path = self._generate_plot(recording_id, plot_spec, output_dir)
                        if plot_path:
                            results['plots'].append(str(plot_path))
                            # Add to database
                            self.database.add_image(
                                recording_id,
                                str(plot_path),
                                ImageType.PLOT,
                                caption=plot_spec.get('title', 'Plot')
                            )
                    except Exception as e:
                        logger.error(f"Failed to generate plot '{plot_spec.get('title')}': {e}")

            # Calculate statistics
            logger.info("Calculating statistics")
            results['statistics'] = self.calculate_statistics(recording_id)

            # Generate statistics table as image
            stats_table_path = self._generate_statistics_table(
                recording_id,
                results['statistics'],
                output_dir
            )
            if stats_table_path:
                results['plots'].append(str(stats_table_path))
                self.database.add_image(
                    recording_id,
                    str(stats_table_path),
                    ImageType.PLOT,
                    caption="Statistics Summary"
                )

            logger.info(f"Processing complete: {len(results['plots'])} plots generated")

            self.database.update_recording(recording_id, status=RecordingStatus.PROCESSED)
            return results

        except Exception as e:
            logger.error(f"Processing failed: {e}")
            self.database.update_recording(recording_id, status=RecordingStatus.FAILED)
            return {
                'plots': [],
                'statistics': {},
                'status': 'failed',
                'error': str(e)
            }

    def _generate_plot(self, recording_id: int, plot_spec: Dict, output_dir: Path) -> Optional[Path]:
        """
        Generate plot based on specification.

        Args:
            recording_id: Recording ID
            plot_spec: Plot specification dict
            output_dir: Output directory

        Returns:
            Path to generated plot or None
        """
        plot_type = plot_spec.get('type', 'line')

        if plot_type == 'line':
            return self._generate_line_plot(recording_id, plot_spec, output_dir)
        elif plot_type == 'multi_line':
            return self._generate_multi_line_plot(recording_id, plot_spec, output_dir)
        elif plot_type == 'map':
            return self._generate_route_map(recording_id, plot_spec, output_dir)
        elif plot_type == 'statistics_table':
            # Handled separately
            return None
        else:
            logger.warning(f"Unknown plot type: {plot_type}")
            return None

    def _generate_line_plot(self, recording_id: int, plot_spec: Dict, output_dir: Path) -> Path:
        """
        Generate single-line time-series plot.

        Args:
            recording_id: Recording ID
            plot_spec: Plot specification with 'topics', 'title', 'ylabel', etc.
            output_dir: Output directory

        Returns:
            Path to generated plot
        """
        title = plot_spec.get('title', 'Plot')
        topics = plot_spec.get('topics', [])
        ylabel = plot_spec.get('ylabel', 'Value')
        color = plot_spec.get('color', '#667eea')

        if not topics:
            raise ValueError("No topics specified for line plot")

        # Get data
        data = self._get_topic_data(recording_id, topics[0])
        if not data:
            raise ValueError(f"No data found for topic {topics[0]}")

        timestamps, values = data

        # Create plot
        fig, ax = plt.subplots(figsize=(self.default_width, self.default_height))

        ax.plot(timestamps, values, linewidth=2, color=color)
        ax.set_title(title, fontsize=16, fontweight='bold')
        ax.set_xlabel('Time', fontsize=12)
        ax.set_ylabel(ylabel, fontsize=12)
        ax.grid(True, alpha=0.3)

        # Format x-axis
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
        plt.xticks(rotation=45, ha='right')

        # Format y-axis
        ax.yaxis.set_major_locator(MaxNLocator(nbins=10))

        plt.tight_layout()

        # Save
        filename = f"{title.replace(' ', '_').lower()}.png"
        output_path = output_dir / filename
        plt.savefig(output_path, dpi=self.default_dpi, bbox_inches='tight')
        plt.close()

        logger.info(f"Generated line plot: {filename}")
        return output_path

    def _generate_multi_line_plot(self, recording_id: int, plot_spec: Dict, output_dir: Path) -> Path:
        """
        Generate multi-line comparison plot.

        Args:
            recording_id: Recording ID
            plot_spec: Plot specification with multiple topics
            output_dir: Output directory

        Returns:
            Path to generated plot
        """
        title = plot_spec.get('title', 'Comparison Plot')
        topics = plot_spec.get('topics', [])
        labels = plot_spec.get('labels', topics)
        ylabel = plot_spec.get('ylabel', 'Value')
        colors = plot_spec.get('colors', ['#667eea', '#764ba2', '#48cae4', '#f72585'])
        show_legend = plot_spec.get('legend', True)

        if not topics:
            raise ValueError("No topics specified for multi-line plot")

        # Create plot
        fig, ax = plt.subplots(figsize=(self.default_width, self.default_height))

        for i, topic in enumerate(topics):
            data = self._get_topic_data(recording_id, topic)
            if data:
                timestamps, values = data
                label = labels[i] if i < len(labels) else topic
                color = colors[i % len(colors)]
                ax.plot(timestamps, values, linewidth=2, label=label, color=color)

        ax.set_title(title, fontsize=16, fontweight='bold')
        ax.set_xlabel('Time', fontsize=12)
        ax.set_ylabel(ylabel, fontsize=12)
        ax.grid(True, alpha=0.3)

        if show_legend:
            ax.legend(fontsize=10, loc='best')

        # Format x-axis
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
        plt.xticks(rotation=45, ha='right')

        plt.tight_layout()

        # Save
        filename = f"{title.replace(' ', '_').lower()}.png"
        output_path = output_dir / filename
        plt.savefig(output_path, dpi=self.default_dpi, bbox_inches='tight')
        plt.close()

        logger.info(f"Generated multi-line plot: {filename}")
        return output_path

    def _generate_route_map(self, recording_id: int, plot_spec: Dict, output_dir: Path) -> Path:
        """
        Generate GPS route map using folium.

        Args:
            recording_id: Recording ID
            plot_spec: Plot specification
            output_dir: Output directory

        Returns:
            Path to generated map image
        """
        try:
            import folium
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
        except ImportError:
            logger.warning("folium or selenium not installed, skipping route map")
            # Fallback: generate matplotlib map
            return self._generate_matplotlib_route_map(recording_id, plot_spec, output_dir)

        title = plot_spec.get('title', 'Route Map')
        topics = plot_spec.get('topics', ['gps/latitude/0', 'gps/longitude/0'])

        # Get GPS coordinates
        coords = self._get_gps_coordinates(recording_id, topics)
        if not coords or len(coords) < 2:
            raise ValueError("Insufficient GPS data for route map")

        # Create folium map centered on route
        center_lat = sum(lat for lat, lon in coords) / len(coords)
        center_lon = sum(lon for lat, lon in coords) / len(coords)

        m = folium.Map(location=[center_lat, center_lon], zoom_start=14)

        # Add route polyline
        folium.PolyLine(
            coords,
            color='#667eea',
            weight=4,
            opacity=0.8
        ).add_to(m)

        # Add start marker (green)
        folium.Marker(
            coords[0],
            popup='Start',
            icon=folium.Icon(color='green', icon='play')
        ).add_to(m)

        # Add end marker (red)
        folium.Marker(
            coords[-1],
            popup='End',
            icon=folium.Icon(color='red', icon='stop')
        ).add_to(m)

        # Fit bounds to show entire route
        m.fit_bounds(coords)

        # Save as HTML
        html_path = output_dir / f"{title.replace(' ', '_').lower()}.html"
        m.save(str(html_path))

        # Convert to PNG using selenium + system Chromium
        png_path = output_dir / f"{title.replace(' ', '_').lower()}.png"
        try:
            chrome_options = Options()
            chrome_options.add_argument('--headless')
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')
            # Use the system-installed Chromium binary (installed via apt chromium/chromium-driver)
            # rather than the selenium-manager auto-downloaded Chrome which requires the
            # matching Chrome browser binary to also be present.
            chrome_options.binary_location = '/usr/bin/chromium'

            from selenium.webdriver.chrome.service import Service
            driver = webdriver.Chrome(options=chrome_options, service=Service('/usr/bin/chromedriver'))
            driver.set_window_size(1200, 800)
            driver.get(f"file://{html_path.absolute()}")
            time.sleep(2)  # Wait for map to render
            driver.save_screenshot(str(png_path))
            driver.quit()

            logger.info(f"Generated route map: {png_path.name}")
            return png_path

        except Exception as e:
            logger.warning(f"Failed to convert map to PNG (ChromeDriver unavailable): {e}, falling back to matplotlib")
            return self._generate_matplotlib_route_map(recording_id, plot_spec, output_dir)

    def _generate_matplotlib_route_map(self, recording_id: int, plot_spec: Dict, output_dir: Path) -> Path:
        """
        Generate simple GPS route map using matplotlib (fallback).

        Args:
            recording_id: Recording ID
            plot_spec: Plot specification
            output_dir: Output directory

        Returns:
            Path to generated plot
        """
        title = plot_spec.get('title', 'Route Map')
        topics = plot_spec.get('topics', ['gps/latitude/0', 'gps/longitude/0'])

        # Get GPS coordinates
        coords = self._get_gps_coordinates(recording_id, topics)
        if not coords or len(coords) < 2:
            raise ValueError("Insufficient GPS data for route map")

        lats = [lat for lat, lon in coords]
        lons = [lon for lat, lon in coords]

        # Create plot
        fig, ax = plt.subplots(figsize=(self.default_width, self.default_height))

        # Plot route
        ax.plot(lons, lats, linewidth=2, color='#667eea', marker='o', markersize=2)

        # Mark start (green) and end (red)
        ax.plot(lons[0], lats[0], 'go', markersize=12, label='Start')
        ax.plot(lons[-1], lats[-1], 'ro', markersize=12, label='End')

        ax.set_title(title, fontsize=16, fontweight='bold')
        ax.set_xlabel('Longitude', fontsize=12)
        ax.set_ylabel('Latitude', fontsize=12)
        ax.grid(True, alpha=0.3)
        ax.legend()

        # Equal aspect ratio for accurate map representation
        ax.set_aspect('equal', adjustable='box')

        plt.tight_layout()

        # Save
        filename = f"{title.replace(' ', '_').lower()}.png"
        output_path = output_dir / filename
        plt.savefig(output_path, dpi=self.default_dpi, bbox_inches='tight')
        plt.close()

        logger.info(f"Generated matplotlib route map: {filename}")
        return output_path

    def _generate_statistics_table(self, recording_id: int, statistics: Dict, output_dir: Path) -> Optional[Path]:
        """
        Generate statistics summary table as image.

        Args:
            recording_id: Recording ID
            statistics: Statistics dict
            output_dir: Output directory

        Returns:
            Path to generated table image
        """
        if not statistics:
            return None

        # Prepare table data
        table_data = [['Metric', 'Value']]

        # Add timing stats
        if 'start_time' in statistics:
            table_data.append(['Start Time', statistics['start_time']])
        if 'end_time' in statistics:
            table_data.append(['End Time', statistics['end_time']])
        if 'duration' in statistics:
            table_data.append(['Duration', statistics['duration']])
        if 'message_count' in statistics:
            table_data.append(['Messages Recorded', f"{statistics['message_count']:,}"])

        # Add GPS-derived stats
        if 'distance_km' in statistics:
            table_data.append(['Distance', f"{statistics['distance_km']:.2f} km"])
        if 'max_speed' in statistics:
            table_data.append(['Max Speed', f"{statistics['max_speed']:.1f} km/h"])
        if 'avg_speed' in statistics:
            table_data.append(['Avg Speed', f"{statistics['avg_speed']:.1f} km/h"])

        # Add energy stats
        if 'energy_used_wh' in statistics:
            table_data.append(['Energy Used', f"{statistics['energy_used_wh']:.1f} Wh"])
        if 'efficiency_wh_per_km' in statistics:
            table_data.append(['Efficiency', f"{statistics['efficiency_wh_per_km']:.1f} Wh/km"])

        # Create figure
        fig, ax = plt.subplots(figsize=(8, len(table_data) * 0.4 + 1))
        ax.axis('tight')
        ax.axis('off')

        # Create table
        table = ax.table(
            cellText=table_data,
            cellLoc='left',
            loc='center',
            colWidths=[0.5, 0.5]
        )

        table.auto_set_font_size(False)
        table.set_fontsize(11)
        table.scale(1, 2)

        # Style header row
        for i in range(2):
            cell = table[(0, i)]
            cell.set_facecolor('#667eea')
            cell.set_text_props(weight='bold', color='white')

        # Alternate row colors
        for i in range(1, len(table_data)):
            for j in range(2):
                cell = table[(i, j)]
                if i % 2 == 0:
                    cell.set_facecolor('#f0f0f0')

        plt.title('Track Statistics', fontsize=14, fontweight='bold', pad=20)

        # Save
        filename = "statistics_summary.png"
        output_path = output_dir / filename
        plt.savefig(output_path, dpi=self.default_dpi, bbox_inches='tight')
        plt.close()

        logger.info(f"Generated statistics table: {filename}")
        return output_path

    def _get_topic_data(self, recording_id: int, topic: str) -> Optional[Tuple[List[datetime], List[float]]]:
        """
        Get time-series data for a topic.

        Args:
            recording_id: Recording ID
            topic: MQTT topic

        Returns:
            Tuple of (timestamps, values) or None
        """
        # Get data from database
        data = self.database.get_recording_data(recording_id, topic_filter=topic)

        if not data:
            return None

        timestamps = []
        values = []

        for record in data:
            try:
                timestamp = record['timestamp']
                if isinstance(timestamp, str):
                    timestamp = datetime.fromisoformat(timestamp)

                value = float(record['payload'])

                timestamps.append(timestamp)
                values.append(value)
            except (ValueError, KeyError):
                continue

        if not timestamps:
            return None

        return (timestamps, values)

    def _get_gps_coordinates(self, recording_id: int, topics: List[str]) -> List[Tuple[float, float]]:
        """
        Get GPS coordinates from recording.

        Args:
            recording_id: Recording ID
            topics: List of [latitude_topic, longitude_topic]

        Returns:
            List of (latitude, longitude) tuples
        """
        if len(topics) < 2:
            return []

        lat_topic = topics[0]
        lon_topic = topics[1]

        # Get latitude and longitude data
        lat_data = self.database.get_recording_data(recording_id, topic_filter=lat_topic)
        lon_data = self.database.get_recording_data(recording_id, topic_filter=lon_topic)

        if not lat_data or not lon_data:
            return []

        # Build coordinate pairs by timestamp
        lat_dict = {}
        for record in lat_data:
            try:
                timestamp = record['timestamp']
                if isinstance(timestamp, str):
                    timestamp = datetime.fromisoformat(timestamp)
                lat_dict[timestamp] = float(record['payload'])
            except (ValueError, KeyError):
                continue

        lon_dict = {}
        for record in lon_data:
            try:
                timestamp = record['timestamp']
                if isinstance(timestamp, str):
                    timestamp = datetime.fromisoformat(timestamp)
                lon_dict[timestamp] = float(record['payload'])
            except (ValueError, KeyError):
                continue

        # Match timestamps using nearest-neighbour within a tolerance window.
        # Lat and lon arrive as separate MQTT topics so their timestamps differ
        # by milliseconds — exact equality almost never matches.
        TOLERANCE = timedelta(seconds=5)
        sorted_lon_times = sorted(lon_dict.keys())
        coords = []
        for lat_ts in sorted(lat_dict.keys()):
            # Binary-search for the closest lon timestamp
            idx = bisect.bisect_left(sorted_lon_times, lat_ts)
            best = None
            for candidate_idx in [idx - 1, idx]:
                if 0 <= candidate_idx < len(sorted_lon_times):
                    diff = abs(sorted_lon_times[candidate_idx] - lat_ts)
                    if diff <= TOLERANCE:
                        if best is None or diff < abs(sorted_lon_times[best] - lat_ts):
                            best = candidate_idx
            if best is not None:
                coords.append((lat_dict[lat_ts], lon_dict[sorted_lon_times[best]]))

        return coords

    def calculate_statistics(self, recording_id: int) -> Dict:
        """
        Calculate statistics for recording.

        Args:
            recording_id: Recording ID

        Returns:
            Dict with statistics
        """
        stats = {}

        # Get recording info
        recording = self.database.get_recording(recording_id)
        if not recording:
            return stats

        # Duration
        start_time = recording['start_time']
        end_time = recording['end_time']

        if isinstance(start_time, str):
            start_time = datetime.fromisoformat(start_time)
        if end_time and isinstance(end_time, str):
            end_time = datetime.fromisoformat(end_time)

        stats['start_time'] = start_time.strftime('%Y-%m-%d %H:%M:%S') if start_time else ''
        stats['end_time'] = end_time.strftime('%Y-%m-%d %H:%M:%S') if end_time else ''

        if end_time:
            duration = end_time - start_time
            stats['duration'] = str(duration).split('.')[0]  # Remove microseconds
            stats['duration_seconds'] = duration.total_seconds()

        # Message count
        stats['message_count'] = self.database.get_recording_data_count(recording_id)

        # GPS-based statistics
        gps_stats = self._calculate_gps_statistics(recording_id)
        stats.update(gps_stats)

        # Energy statistics
        energy_stats = self._calculate_energy_statistics(recording_id)
        stats.update(energy_stats)

        return stats

    def _calculate_gps_statistics(self, recording_id: int) -> Dict:
        """Calculate GPS-based statistics (distance, speed)."""
        stats = {}

        # Get GPS coordinates
        coords = self._get_gps_coordinates(recording_id, ['gps/latitude/0', 'gps/longitude/0'])

        if len(coords) < 2:
            return stats

        # Calculate total distance using Haversine
        total_distance = 0
        for i in range(1, len(coords)):
            lat1, lon1 = coords[i-1]
            lat2, lon2 = coords[i]
            distance = self._haversine_distance(lat1, lon1, lat2, lon2)
            total_distance += distance

        stats['distance_km'] = total_distance / 1000  # Convert to km

        # Get speed data
        speed_data = self._get_topic_data(recording_id, 'gps/speed/0')
        if speed_data:
            timestamps, speeds = speed_data
            stats['max_speed'] = max(speeds)
            stats['avg_speed'] = sum(speeds) / len(speeds)

        return stats

    def _calculate_energy_statistics(self, recording_id: int) -> Dict:
        """Calculate energy consumption statistics."""
        stats = {}

        # Get battery power data
        power_data = self._get_topic_data(recording_id, 'battery/power/0/0')
        if not power_data:
            return stats

        timestamps, powers = power_data

        # Calculate energy using trapezoidal integration
        total_energy = 0
        for i in range(1, len(timestamps)):
            dt = (timestamps[i] - timestamps[i-1]).total_seconds() / 3600  # hours
            avg_power = (powers[i] + powers[i-1]) / 2
            total_energy += avg_power * dt

        stats['energy_used_wh'] = abs(total_energy)

        # Calculate efficiency (Wh/km)
        if 'distance_km' in stats and stats['distance_km'] > 0:
            stats['efficiency_wh_per_km'] = stats['energy_used_wh'] / stats['distance_km']

        return stats

    def _haversine_distance(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Calculate distance between two GPS points (meters)."""
        R = 6371000  # Earth radius in meters

        lat1_rad = math.radians(lat1)
        lat2_rad = math.radians(lat2)
        delta_lat = math.radians(lat2 - lat1)
        delta_lon = math.radians(lon2 - lon1)

        a = (math.sin(delta_lat / 2) ** 2 +
             math.cos(lat1_rad) * math.cos(lat2_rad) *
             math.sin(delta_lon / 2) ** 2)
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

        return R * c


def main():
    """CLI for testing data processor."""
    import argparse

    parser = argparse.ArgumentParser(description="Data Processor Test")
    parser.add_argument('--db', default='/data/recordings.db', help="Database path")
    parser.add_argument('--recording-id', type=int, required=True, help="Recording ID to process")
    parser.add_argument('--plots-dir', default='/tmp/plots', help="Plots output directory")

    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(level=logging.INFO,
                       format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    from .models import Database
    db = Database(args.db)
    processor = DataProcessor(db, args.plots_dir)

    # Example plot config
    plot_config = [
        {'type': 'line', 'title': 'Speed', 'topics': ['gps/speed/0'], 'ylabel': 'Speed (km/h)'},
        {'type': 'multi_line', 'title': 'Battery Power', 'topics': ['battery/power/0/0', 'battery/power/0/1'],
         'labels': ['Bank 1', 'Bank 2'], 'ylabel': 'Power (W)'},
        {'type': 'map', 'title': 'Route Map', 'topics': ['gps/latitude/0', 'gps/longitude/0']}
    ]

    results = processor.process_recording(args.recording_id, plot_config)

    print("\nProcessing Results:")
    print(f"  Status: {results['status']}")
    print(f"  Plots generated: {len(results['plots'])}")
    for plot in results['plots']:
        print(f"    - {plot}")
    print(f"\nStatistics:")
    for key, value in results['statistics'].items():
        print(f"    {key}: {value}")


if __name__ == '__main__':
    main()
