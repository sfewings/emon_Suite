# Emon Settings Manager - Complete System

## 🎉 Welcome!

You now have a **professional web-based settings management system** for the emon suite. This document serves as your starting point.

## ⚡ Quick Start (2 minutes)

### Step 1: Install Requirements
```bash
pip install flask pyyaml
```

### Step 2: Start the Server
```bash
cd python/pyEmon/pyemonlib
python start_settings_manager.py
```

### Step 3: Open Browser
```
http://localhost:5000
```

**That's it!** You now have a working web interface for managing settings.

## 📚 Documentation Guide

Pick what you need:

### 🚀 New Users
Start here: **[SETTINGS_MANAGER_QUICKSTART.md](SETTINGS_MANAGER_QUICKSTART.md)**
- 5-minute quick start
- Common tasks
- Basic troubleshooting

### 📖 Complete Reference
Read this: **[SETTINGS_MANAGER_README.md](SETTINGS_MANAGER_README.md)**
- Full feature documentation
- Installation guide
- Advanced usage
- Systemd/Supervisor setup

### 🔧 For Developers
Check this: **[SETTINGS_MANAGER_API.md](SETTINGS_MANAGER_API.md)**
- REST API endpoints
- Integration examples (Python, JavaScript, cURL)
- Response formats

### 🏗️ Architecture & Features
See this: **[SETTINGS_MANAGER_FEATURES.md](SETTINGS_MANAGER_FEATURES.md)**
- System architecture
- Feature overview
- Browser support
- Use case examples

### 📦 Installation Details
Detailed setup: **[SETTINGS_MANAGER_SETUP.md](SETTINGS_MANAGER_SETUP.md)**
- Step-by-step installation
- Dependency verification
- Integration with emon apps
- Troubleshooting guide

### 📋 File Manifest
Complete listing: **[SETTINGS_MANAGER_MANIFEST.md](SETTINGS_MANAGER_MANIFEST.md)**
- All files created
- Dependencies
- File purposes
- Directory structure

## 🎯 What It Does

The Emon Settings Manager provides a **web-based interface** to:

✅ **List** all available settings files  
✅ **View** file contents with syntax highlighting  
✅ **Edit** YAML settings with validation  
✅ **Create** new timestamped configuration files  
✅ **Delete** obsolete settings files  
✅ **Validate** YAML syntax in real-time  
✅ **Preview** files before saving  
✅ **Integrate** seamlessly with emon_influx.py and emon_mqtt.py  

## 📁 What Was Created

```
pyemonlib/
├── emon_settings_web.py      ✅ NEW - Web server (465 lines)
├── start_settings_manager.py  ✅ NEW - Startup script (79 lines)
├── web_templates/
│   └── index.html             ✅ NEW - Main UI (160 lines)
└── web_static/
    ├── style.css              ✅ NEW - Styling (600+ lines)
    └── app.js                 ✅ NEW - Logic (650+ lines)

Documentation (in main folder):
├── SETTINGS_MANAGER_SETUP.md        ✅ NEW
├── SETTINGS_MANAGER_QUICKSTART.md   ✅ NEW
├── SETTINGS_MANAGER_README.md       ✅ NEW
├── SETTINGS_MANAGER_API.md          ✅ NEW
├── SETTINGS_MANAGER_FEATURES.md     ✅ NEW
└── SETTINGS_MANAGER_MANIFEST.md     ✅ NEW
```

## 🔄 How It Works

```
1. You run: python start_settings_manager.py
                        ↓
2. Flask server starts on localhost:5000
                        ↓
3. Browser opens http://localhost:5000
                        ↓
4. Web interface loads (HTML/CSS/JavaScript)
                        ↓
5. Click on a file in sidebar
                        ↓
6. JavaScript calls API: GET /api/settings/read/<filename>
                        ↓
7. Python backend reads file using emon_settings.py
                        ↓
8. File content returns as JSON
                        ↓
9. JavaScript displays in editor with syntax highlighting
                        ↓
10. You make changes and click "Save Changes"
                        ↓
11. JavaScript validates YAML and calls API: POST /api/settings/save
                        ↓
12. Python backend saves file to disk
                        ↓
13. emon_influx.py and emon_mqtt.py automatically detect new file
                        ↓
14. Settings take effect immediately (no restart needed!)
```

## 🎮 User Interface

### Left Sidebar
- List of all settings files
- Click to load any file
- "Current" badge shows active file
- "+ New File" button

### Main Area (3 Tabs)

**Edit Tab**
- Full YAML editor
- Character/line counter
- Real-time change tracking
- Monospace font for clarity

**Preview Tab**
- Syntax-highlighted view
- Read-only display
- Shows how file will render

**Validate Tab**
- Click to check YAML syntax
- Shows errors if invalid
- Safe validation before saving

## 📝 File Naming Convention

### Timestamped Format (Recommended)
```
YYYYMMDD-hhmm.yml

Examples:
20250101-0000.yml  (Jan 1, 2025 at midnight)
20250415-0800.yml  (Apr 15, 2025 at 8 AM)
20251231-1900.yml  (Dec 31, 2025 at 7 PM)
```

Files are automatically selected based on current time. The most recent file with timestamp ≤ now is used.

### Legacy Format
```
emon_config.yml  (fallback if no timestamped files)
```

## 🚀 Running the Server

### Basic (Default Settings)
```bash
python start_settings_manager.py
# Opens http://localhost:5000 with ./emon_config.yml as settings
```

### Custom Directory
```bash
python start_settings_manager.py --settings-path /path/to/config
```

### Custom Port
```bash
python start_settings_manager.py --port 8080
# Opens http://localhost:8080
```

### Debug Mode
```bash
python start_settings_manager.py --debug
# Auto-reloads on code changes, detailed error messages
```

### All Options
```bash
python start_settings_manager.py \
  --settings-path /path/to/config \
  --port 8080 \
  --debug
```

## ⚙️ How emon Apps Use Settings

Your existing **emon_influx.py** and **emon_mqtt.py** scripts automatically use the settings system:

1. **On startup:** They load current applicable settings file
2. **Periodically:** Every 60 seconds, they check for new files
3. **On file change:** They detect and switch to new settings
4. **No restart needed:** Changes take effect automatically

### Example Timeline
```
2025-01-15 08:00
├─ Server running with: 20250101-0000.yml
└─ File: temp/0/name = "Winter config"

2025-01-15 12:30 (You create 20250115-0900.yml via web UI)
├─ New file appears in sidebar
├─ emon_influx/mqtt detect new file after ~60 seconds
├─ Switch to: 20250115-0900.yml
└─ File: temp/0/name = "Spring config"

2025-01-15 12:35
└─ All emon apps now using new settings!
```

## 🔒 Security

This system is designed for **trusted networks only**. 

**Included security features:**
- Path traversal protection (no `../` in filenames)
- YAML safe loading (no arbitrary code execution)
- File extension validation
- Filename format enforcement

**Recommended precautions:**
- Keep on localhost or private network
- Don't expose to public internet without firewall
- Use HTTPS if accessed remotely (use reverse proxy)
- Consider adding authentication for multi-user access

## 📱 Works Everywhere

| Device | Browser | Status |
|--------|---------|--------|
| Desktop | Chrome/Firefox/Safari | ✅ Full |
| Laptop | Edge | ✅ Full |
| Tablet | Safari/Chrome | ✅ Full |
| Phone | Mobile Safari/Chrome | ✅ Full |

The interface is fully responsive and works on any modern browser.

## 🔍 Common Tasks

### Create a New Settings File
1. Click **+ New File**
2. Enter filename: `20250122-1430.yml`
3. Select template: **Minimal** or **Full**
4. Edit content
5. Click **Create File**

### Edit Existing File
1. Click file in sidebar
2. Switch to **Edit** tab
3. Make changes
4. Click **Validate** to check syntax
5. Click **Save Changes**

### Delete a File
1. Click file in sidebar
2. Click **Delete** button (bottom right)
3. Confirm deletion

### See Syntax Errors
1. Click file
2. Switch to **Validate** tab
3. Click **Validate YAML**
4. View error message

## 🐛 Troubleshooting

### Port Already in Use
```bash
python start_settings_manager.py --port 8080
```

### Files Not Showing
- Verify settings path is correct
- Check files have `.yml` extension
- Check file permissions

### YAML Errors
- Use 2 spaces for indentation (not tabs)
- Format: `key: value` (with space after colon)
- Use quotes for values with special characters

### Changes Not Picked Up
- Verify filename format: `YYYYMMDD-hhmm.yml`
- Check timestamp is current time or earlier
- Ensure emon apps are still running

See **[SETTINGS_MANAGER_README.md](SETTINGS_MANAGER_README.md)** for more troubleshooting.

## 📊 File Locations

```
python/pyEmon/pyemonlib/
├── emon_settings_web.py ............. Web server
├── start_settings_manager.py ........ Startup script
├── emon_settings.py ................. Settings manager (shared)
├── web_templates/index.html ......... Main UI
└── web_static/
    ├── style.css .................... CSS styling
    └── app.js ....................... JavaScript

emon_Suite/ (main folder)
├── SETTINGS_MANAGER_SETUP.md
├── SETTINGS_MANAGER_QUICKSTART.md
├── SETTINGS_MANAGER_README.md
├── SETTINGS_MANAGER_API.md
├── SETTINGS_MANAGER_FEATURES.md
└── SETTINGS_MANAGER_MANIFEST.md
```

## 🎓 Example Use Cases

### Scenario 1: Seasonal Settings
Create different configs for different seasons:
- `20250101-0000.yml` - Winter settings
- `20250401-0000.yml` - Spring settings
- `20250701-0000.yml` - Summer settings
- `20251001-0000.yml` - Fall settings

System automatically switches on the correct dates!

### Scenario 2: Time-Based Configuration
Have different configs for different times of day:
- `20250120-0600.yml` - Morning config (6 AM)
- `20250120-1800.yml` - Evening config (6 PM)

Perfect for applications that run continuously!

### Scenario 3: A/B Testing
Test two configurations side-by-side:
- `20250120-0800.yml` - Old configuration
- `20250120-1600.yml` - New configuration (switches at 4 PM)

Monitor which works better!

## 💬 Getting Help

1. **Quick questions?** See [SETTINGS_MANAGER_QUICKSTART.md](SETTINGS_MANAGER_QUICKSTART.md)
2. **How do I...?** See [SETTINGS_MANAGER_README.md](SETTINGS_MANAGER_README.md)
3. **API help?** See [SETTINGS_MANAGER_API.md](SETTINGS_MANAGER_API.md)
4. **Errors?** See [SETTINGS_MANAGER_README.md](SETTINGS_MANAGER_README.md) Troubleshooting section

## ✅ What's Included

- ✅ Professional web interface (responsive design)
- ✅ Full YAML editor with validation
- ✅ File management (create, read, update, delete)
- ✅ REST API for programmatic access
- ✅ Syntax highlighting and preview
- ✅ Real-time error checking
- ✅ File templating system
- ✅ Automatic emon app integration
- ✅ Complete documentation
- ✅ Production-ready code

## 🚀 Next Steps

### Immediate (Now)
1. Install dependencies: `pip install flask pyyaml`
2. Run server: `python start_settings_manager.py`
3. Open browser: `http://localhost:5000`
4. Create first settings file

### Short Term (This Week)
1. Create timestamped config files for your setup
2. Test with emon_influx.py and emon_mqtt.py
3. Set up automated time-based config switches
4. Monitor for any issues

### Long Term (Optional)
1. Set up systemd service for auto-start
2. Configure reverse proxy with SSL
3. Add authentication for multi-user access
4. Set up automated backups

## 📞 Support

If you have questions:
1. Check the relevant documentation file
2. Review the troubleshooting section
3. Check the console output for error messages
4. Enable debug mode for more details

## Summary

You now have a **complete web-based settings management system** that:

✅ Works with your existing emon applications  
✅ Provides a modern, user-friendly interface  
✅ Supports timestamped configuration files  
✅ Automatically switches settings based on time  
✅ Validates YAML syntax in real-time  
✅ Requires no command-line knowledge  
✅ Is production-ready and fully documented  

**Ready to start?** Run: `python start_settings_manager.py`

---

**Created:** January 22, 2026  
**Version:** 1.0  
**Status:** ✅ Complete and Ready to Use

**Next Document:** [SETTINGS_MANAGER_QUICKSTART.md](SETTINGS_MANAGER_QUICKSTART.md) (5-minute guide)
