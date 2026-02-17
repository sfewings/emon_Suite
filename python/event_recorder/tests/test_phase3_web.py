#!/usr/bin/env python3
"""
Phase 3 Testing: Web Interface
Tests Flask REST API and web UI functionality
"""

import sys
import time
import requests
import webbrowser
from pathlib import Path

print("="*70)
print("PHASE 3 TESTING: Web Interface")
print("="*70)
print()

# Step 1: Check if test database exists
print("STEP 1: Check Test Database")
db_path = Path("test_recordings.db")
if not db_path.exists():
    print("⚠️  No test database found. Creating sample data...")
    print("   Run: python test_full_cycle.py")
    print()
    response = input("Do you want to run Phase 1-2 test first? (y/n): ")
    if response.lower() == 'y':
        import subprocess
        subprocess.run([sys.executable, "test_full_cycle.py"])
    else:
        print("Continuing with empty database...")
else:
    print("✓ Test database found")
print()

# Step 2: Install dependencies
print("STEP 2: Install Dependencies")
print("   pip install Flask gunicorn Werkzeug")
print()
response = input("Install dependencies now? (y/n): ")
if response.lower() == 'y':
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install", "Flask", "gunicorn", "Werkzeug"])
print()

# Step 3: Start web server
print("STEP 3: Start Web Server")
print("   The web interface will start on http://localhost:5000")
print()
print("   To start manually:")
print("   python -m event_recorder.web_interface --db test_recordings.db --port 5000")
print()
response = input("Start web server now? (y/n): ")

if response.lower() == 'y':
    print()
    print("Starting web server...")
    print("Press Ctrl+C to stop the server when done testing")
    print()

    # Wait a moment then open browser
    import subprocess
    import threading

    def open_browser():
        time.sleep(2)
        webbrowser.open('http://localhost:5000')

    threading.Thread(target=open_browser, daemon=True).start()

    # Start server (this will block)
    subprocess.run([
        sys.executable, "-m", "event_recorder.web_interface",
        "--db", "test_recordings.db",
        "--port", "5000"
    ])
else:
    print()
    print("="*70)
    print("MANUAL TESTING STEPS")
    print("="*70)
    print()
    print("1. Start the web server:")
    print("   python -m event_recorder.web_interface --db test_recordings.db")
    print()
    print("2. Open browser: http://localhost:5000")
    print()
    print("3. Test each view:")
    print("   ✓ Dashboard - Check status, active recordings")
    print("   ✓ Recordings - View all recordings, filter by status")
    print("   ✓ Manual Control - Start/stop recordings manually")
    print("   ✓ Settings - View configuration info")
    print()
    print("4. Test API endpoints:")
    print("   curl http://localhost:5000/api/status")
    print("   curl http://localhost:5000/api/recordings")
    print()
    print("5. Test real-time updates:")
    print("   - Status should poll every 2 seconds")
    print("   - Watch network tab in browser DevTools")
    print()
    print("6. Test recording operations:")
    print("   - Start a manual recording")
    print("   - Stop a recording")
    print("   - View recording details (click on recording)")
    print("   - Delete a test recording")
    print()
    print("="*70)
    print("EXPECTED BEHAVIOR")
    print("="*70)
    print()
    print("✓ Purple gradient header with status indicator")
    print("✓ Sidebar navigation (Dashboard, Recordings, Manual, Settings)")
    print("✓ Real-time status updates every 2 seconds")
    print("✓ Recordings displayed in grid/list format")
    print("✓ Manual recording start/stop functionality")
    print("✓ Recording details shown in modal dialog")
    print("✓ Toast notifications for actions")
    print("✓ Responsive design (works on mobile)")
    print()
