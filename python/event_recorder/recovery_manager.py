"""
Power outage recovery manager.

Detects interrupted recordings on startup and decides whether to resume
or complete processing based on current GPS position and recording state.
"""

import logging
from datetime import datetime
from typing import List, Dict, Optional, Callable
from .models import Database, RecordingStatus

logger = logging.getLogger(__name__)


class RecoveryManager:
    """
    Manages recovery from power outages and service interruptions.

    On startup, checks for interrupted recordings and determines appropriate
    recovery action based on current conditions.
    """

    def __init__(self, database: Database):
        """
        Initialize recovery manager.

        Args:
            database: Database instance
        """
        self.database = database
        logger.info("RecoveryManager initialized")

    def check_interrupted_recordings(self) -> Dict[str, List[int]]:
        """
        Check for interrupted recordings that need recovery.

        Returns:
            Dict with recovery actions:
            {
                'resume': [recording_ids to resume],
                'process': [recording_ids to process],
                'failed': [recording_ids that failed]
            }
        """
        recovery_actions = {
            'resume': [],
            'process': [],
            'failed': []
        }

        # Get all 'active' recordings (interrupted during recording)
        active_recordings = self.database.get_recordings_by_status(RecordingStatus.ACTIVE)

        if active_recordings:
            logger.info(f"Found {len(active_recordings)} interrupted active recordings")

        for recording in active_recordings:
            recording_id = recording['id']
            start_time = recording['start_time']

            # Check how much data was recorded
            message_count = self.database.get_recording_data_count(recording_id)

            if message_count == 0:
                # No data recorded, mark as failed
                logger.warning(f"Recording {recording_id}: no data recorded, marking as failed")
                self.database.update_recording(
                    recording_id,
                    status=RecordingStatus.FAILED,
                    end_time=datetime.utcnow(),
                    error_message="No data recorded before interruption"
                )
                recovery_actions['failed'].append(recording_id)
            else:
                # Has data, move to processing
                logger.info(f"Recording {recording_id}: has {message_count} messages, marking for processing")
                self.database.update_recording(
                    recording_id,
                    status=RecordingStatus.STOPPED,
                    end_time=datetime.utcnow()
                )
                recovery_actions['process'].append(recording_id)

        # Get recordings stuck in 'stopped' state (stopped but not processed)
        stopped_recordings = self.database.get_recordings_by_status(RecordingStatus.STOPPED)

        if stopped_recordings:
            logger.info(f"Found {len(stopped_recordings)} stopped recordings awaiting processing")
            for recording in stopped_recordings:
                recovery_actions['process'].append(recording['id'])

        # Get recordings stuck in 'processing' state
        processing_recordings = self.database.get_recordings_by_status(RecordingStatus.PROCESSING)

        if processing_recordings:
            logger.info(f"Found {len(processing_recordings)} recordings interrupted during processing")
            for recording in processing_recordings:
                # Reset to stopped state for reprocessing
                self.database.update_recording(recording['id'], status=RecordingStatus.STOPPED)
                recovery_actions['process'].append(recording['id'])

        return recovery_actions

    def should_resume_recording(self, recording_id: int,
                               current_gps_position: Optional[tuple] = None,
                               movement_threshold: float = 1.0) -> bool:
        """
        Determine if an interrupted recording should be resumed.

        Args:
            recording_id: Recording ID
            current_gps_position: Current GPS (lat, lon) or None
            movement_threshold: Movement threshold in m/s

        Returns:
            bool: True if should resume, False if should stop/process
        """
        recording = self.database.get_recording(recording_id)
        if not recording:
            return False

        # If no GPS data available, can't determine movement
        if not current_gps_position:
            logger.info(f"Recording {recording_id}: no GPS data, cannot resume")
            return False

        # Get last GPS position from recording
        last_gps = self._get_last_gps_position(recording_id)
        if not last_gps:
            logger.info(f"Recording {recording_id}: no GPS history, cannot determine movement")
            return False

        # Calculate if vehicle has moved significantly
        from .trigger_monitor import GPSTriggerMonitor
        monitor = GPSTriggerMonitor()  # Just for haversine_distance method

        last_lat, last_lon, last_time = last_gps
        current_lat, current_lon = current_gps_position

        distance = monitor._haversine_distance(last_lat, last_lon, current_lat, current_lon)

        # Calculate time elapsed
        now = datetime.utcnow()
        if isinstance(last_time, str):
            last_time = datetime.fromisoformat(last_time)
        elapsed_seconds = (now - last_time).total_seconds()

        if elapsed_seconds > 0:
            movement_rate = distance / elapsed_seconds  # meters per second
        else:
            movement_rate = 0

        logger.info(f"Recording {recording_id}: moved {distance:.1f}m in {elapsed_seconds:.0f}s "
                   f"(rate={movement_rate:.2f} m/s)")

        # If moving faster than threshold, resume
        if movement_rate > movement_threshold:
            logger.info(f"Recording {recording_id}: vehicle still moving, should resume")
            return True
        else:
            logger.info(f"Recording {recording_id}: vehicle stationary, should process")
            return False

    def _get_last_gps_position(self, recording_id: int) -> Optional[tuple]:
        """
        Get last GPS position from recording data.

        Args:
            recording_id: Recording ID

        Returns:
            Tuple of (latitude, longitude, timestamp) or None
        """
        # Get last few GPS messages
        lat_data = self.database.get_recording_data(
            recording_id,
            topic_filter='%latitude%',
            limit=1
        )
        lon_data = self.database.get_recording_data(
            recording_id,
            topic_filter='%longitude%',
            limit=1
        )

        if not lat_data or not lon_data:
            return None

        try:
            # Extract latitude
            lat_msg = lat_data[0]
            latitude = float(lat_msg['payload'])
            lat_timestamp = lat_msg['timestamp']

            # Extract longitude
            lon_msg = lon_data[0]
            longitude = float(lon_msg['payload'])
            lon_timestamp = lon_msg['timestamp']

            # Use most recent timestamp
            timestamp = max(lat_timestamp, lon_timestamp)

            return (latitude, longitude, timestamp)
        except (ValueError, KeyError) as e:
            logger.warning(f"Failed to parse GPS data: {e}")
            return None

    def auto_recover(self, on_process_callback: Callable[[int], None] = None) -> Dict:
        """
        Automatically recover from interruptions.

        Args:
            on_process_callback: Callback for recordings that need processing
                                Called with recording_id

        Returns:
            Dict with recovery summary
        """
        logger.info("Starting automatic recovery")

        recovery_actions = self.check_interrupted_recordings()

        summary = {
            'resumed': 0,
            'processed': 0,
            'failed': len(recovery_actions['failed'])
        }

        # Process recordings that need it
        if on_process_callback:
            for recording_id in recovery_actions['process']:
                try:
                    logger.info(f"Triggering processing for recording {recording_id}")
                    on_process_callback(recording_id)
                    summary['processed'] += 1
                except Exception as e:
                    logger.error(f"Failed to process recording {recording_id}: {e}")
                    self.database.update_recording(
                        recording_id,
                        status=RecordingStatus.FAILED,
                        error_message=f"Recovery processing failed: {e}"
                    )
                    summary['failed'] += 1

        logger.info(f"Recovery complete: {summary}")
        return summary

    def get_recovery_summary(self) -> Dict:
        """
        Get summary of recordings in various states.

        Returns:
            Dict with counts per status
        """
        summary = {}
        for status in [RecordingStatus.ACTIVE, RecordingStatus.STOPPED,
                      RecordingStatus.PROCESSING, RecordingStatus.PUBLISHED,
                      RecordingStatus.FAILED]:
            recordings = self.database.get_recordings_by_status(status.value)
            summary[status.value] = len(recordings)

        return summary

    def cleanup_old_recordings(self, max_age_days: int = 30,
                              keep_published: bool = True) -> int:
        """
        Clean up old recordings to free space.

        Args:
            max_age_days: Maximum age in days
            keep_published: Don't delete published recordings

        Returns:
            int: Number of recordings deleted
        """
        from datetime import timedelta

        cutoff_date = datetime.utcnow() - timedelta(days=max_age_days)
        deleted_count = 0

        # Get all recordings
        all_recordings = self.database.get_all_recordings(limit=10000)

        for recording in all_recordings:
            recording_id = recording['id']
            created_at = recording['created_at']
            status = recording['status']

            # Parse timestamp
            if isinstance(created_at, str):
                created_at = datetime.fromisoformat(created_at)

            # Skip if too recent
            if created_at > cutoff_date:
                continue

            # Skip published recordings if requested
            if keep_published and status == RecordingStatus.PUBLISHED:
                continue

            # Delete old recording
            try:
                logger.info(f"Deleting old recording {recording_id} (created {created_at})")
                self.database.delete_recording(recording_id)
                deleted_count += 1
            except Exception as e:
                logger.error(f"Failed to delete recording {recording_id}: {e}")

        logger.info(f"Cleanup complete: deleted {deleted_count} old recordings")
        return deleted_count

    def mark_recording_as_failed(self, recording_id: int, error_message: str):
        """
        Mark recording as failed with error message.

        Args:
            recording_id: Recording ID
            error_message: Error description
        """
        self.database.update_recording(
            recording_id,
            status=RecordingStatus.FAILED,
            end_time=datetime.utcnow(),
            error_message=error_message
        )
        logger.warning(f"Recording {recording_id} marked as failed: {error_message}")

    def retry_failed_recording(self, recording_id: int) -> bool:
        """
        Retry processing a failed recording.

        Args:
            recording_id: Recording ID

        Returns:
            bool: True if eligible for retry
        """
        recording = self.database.get_recording(recording_id)
        if not recording:
            return False

        if recording['status'] != RecordingStatus.FAILED:
            logger.warning(f"Recording {recording_id} not in failed state")
            return False

        # Check if has data
        message_count = self.database.get_recording_data_count(recording_id)
        if message_count == 0:
            logger.warning(f"Recording {recording_id} has no data, cannot retry")
            return False

        # Reset to stopped state for reprocessing
        self.database.update_recording(
            recording_id,
            status=RecordingStatus.STOPPED,
            error_message=None
        )

        logger.info(f"Recording {recording_id} reset for retry ({message_count} messages)")
        return True


def main():
    """
    CLI for testing recovery manager.

    Usage:
        python recovery_manager.py [--db DB_PATH]
    """
    import argparse

    parser = argparse.ArgumentParser(description="Recovery Manager Test")
    parser.add_argument('--db', default='/data/recordings.db', help="Database path")
    parser.add_argument('--summary', action='store_true', help="Show recovery summary")
    parser.add_argument('--cleanup', type=int, help="Clean up recordings older than N days")

    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(level=logging.INFO,
                       format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    from .models import Database
    db = Database(args.db)
    recovery = RecoveryManager(db)

    if args.summary:
        summary = recovery.get_recovery_summary()
        print("\nRecording Status Summary:")
        for status, count in summary.items():
            print(f"  {status}: {count}")

    elif args.cleanup:
        count = recovery.cleanup_old_recordings(max_age_days=args.cleanup)
        print(f"\nDeleted {count} old recordings")

    else:
        # Run recovery check
        def process_callback(recording_id):
            logger.info(f"Would process recording {recording_id}")

        summary = recovery.auto_recover(on_process_callback=process_callback)
        print("\nRecovery Summary:")
        print(f"  Processed: {summary['processed']}")
        print(f"  Failed: {summary['failed']}")


if __name__ == '__main__':
    main()
