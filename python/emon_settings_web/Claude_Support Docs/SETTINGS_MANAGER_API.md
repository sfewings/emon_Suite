# Emon Settings Manager - API Reference

Complete REST API documentation for the Settings Manager web interface.

## Base URL

```
http://localhost:5000/api/settings
```

All responses are JSON format.

## Authentication

Currently no authentication is implemented. This web interface is intended for use in trusted networks only.

## Endpoints

### 1. List Available Files

**GET** `/api/settings/list`

Lists all available settings files in the configured directory.

**Response:**
```json
{
  "success": true,
  "files": [
    {
      "filename": "20250122-1430.yml",
      "path": "/full/path/to/20250122-1430.yml",
      "datetime": "2025-01-22T14:30:00",
      "isCurrent": true
    },
    {
      "filename": "20250101-0000.yml",
      "path": "/full/path/to/20250101-0000.yml",
      "datetime": "2025-01-01T00:00:00",
      "isCurrent": false
    },
    {
      "filename": "emon_config.yml",
      "path": "/full/path/to/emon_config.yml",
      "datetime": null,
      "isCurrent": false
    }
  ],
  "current": "20250122-1430.yml"
}
```

**Status Codes:**
- `200 OK` - Success
- `500 Internal Server Error` - Server error

---

### 2. Read File Contents

**GET** `/api/settings/read/<filename>`

Retrieves the full contents of a specific settings file.

**Parameters:**
- `filename` (string, required, path parameter) - Name of file to read
  - Examples: `20250122-1430.yml`, `emon_config.yml`

**Response:**
```json
{
  "success": true,
  "filename": "20250122-1430.yml",
  "content": "temp:\n  0:\n    name: House temperatures\n    t0: Under roof\n..."
}
```

**Status Codes:**
- `200 OK` - Success
- `400 Bad Request` - Invalid filename (path traversal attempt)
- `404 Not Found` - File not found
- `500 Internal Server Error` - Server error

**Example:**
```bash
curl http://localhost:5000/api/settings/read/20250122-1430.yml
```

---

### 3. Validate YAML Syntax

**POST** `/api/settings/validate`

Validates YAML syntax without saving to a file.

**Request Body:**
```json
{
  "content": "temp:\n  0:\n    name: House temp\n    t0: Room 1"
}
```

**Response (Valid YAML):**
```json
{
  "success": true,
  "valid": true,
  "message": "YAML syntax is valid"
}
```

**Response (Invalid YAML):**
```json
{
  "success": true,
  "valid": false,
  "message": "mapping values are not allowed here\n  in \"<unicode string>\", line 2, column 5"
}
```

**Status Codes:**
- `200 OK` - Validation completed (see `valid` field)
- `400 Bad Request` - Missing content field
- `500 Internal Server Error` - Server error

**Example:**
```bash
curl -X POST http://localhost:5000/api/settings/validate \
  -H "Content-Type: application/json" \
  -d '{"content":"temp:\n  0:\n    name: Test"}'
```

---

### 4. Save Settings File

**POST** `/api/settings/save`

Creates a new settings file or overwrites an existing one.

**Request Body:**
```json
{
  "filename": "20250122-1430.yml",
  "content": "temp:\n  0:\n    name: House temperatures"
}
```

**Response (Success):**
```json
{
  "success": true,
  "message": "Settings saved to 20250122-1430.yml",
  "filename": "20250122-1430.yml",
  "filepath": "/full/path/to/20250122-1430.yml"
}
```

**Response (Invalid Filename):**
```json
{
  "success": false,
  "error": "Invalid filename format. Use YYYYMMDD-hhmm.yml format (e.g., 20250122-1430.yml) or emon_config.yml"
}
```

**Response (Invalid YAML):**
```json
{
  "success": false,
  "error": "Invalid YAML syntax: mapping values are not allowed here..."
}
```

**Validation Rules:**
- Filename must match `YYYYMMDD-hhmm.yml` OR be `emon_config.yml`
- YAML syntax must be valid
- Directory will be created if it doesn't exist
- Files are overwritten if they already exist

**Status Codes:**
- `200 OK` - File saved successfully
- `400 Bad Request` - Invalid filename or YAML syntax
- `500 Internal Server Error` - Server error

**Example:**
```bash
curl -X POST http://localhost:5000/api/settings/save \
  -H "Content-Type: application/json" \
  -d '{
    "filename": "20250122-1430.yml",
    "content": "temp:\n  0:\n    name: Test"
  }'
```

---

### 5. Delete Settings File

**POST** `/api/settings/delete/<filename>`

Deletes a settings file.

**Parameters:**
- `filename` (string, required, path parameter) - Name of file to delete

**Response (Success):**
```json
{
  "success": true,
  "message": "20250122-1430.yml deleted successfully"
}
```

**Response (Protected File):**
```json
{
  "success": false,
  "error": "Cannot delete emon_config.yml"
}
```

**Response (Not Found):**
```json
{
  "success": false,
  "error": "File not found"
}
```

**Restrictions:**
- Cannot delete `emon_config.yml` (protected file)
- Directory traversal attempts are blocked

**Status Codes:**
- `200 OK` - File deleted successfully
- `400 Bad Request` - Invalid filename or protected file
- `404 Not Found` - File not found
- `500 Internal Server Error` - Server error

**Example:**
```bash
curl -X POST http://localhost:5000/api/settings/delete/20250122-1430.yml
```

---

### 6. Get Current Settings

**GET** `/api/settings/current`

Retrieves the currently active settings and filename.

**Response:**
```json
{
  "success": true,
  "currentFile": "20250122-1430.yml",
  "settings": {
    "temp": {
      "0": {
        "name": "House temperatures",
        "t0": "Under roof",
        "t1": "Living room"
      }
    }
  }
}
```

**Status Codes:**
- `200 OK` - Success
- `500 Internal Server Error` - Server error

**Example:**
```bash
curl http://localhost:5000/api/settings/current
```

---

## Error Handling

All endpoints return a standard error response format:

```json
{
  "success": false,
  "error": "Description of what went wrong"
}
```

Common error codes:
- `400 Bad Request` - Client error (invalid input)
- `404 Not Found` - Resource not found
- `500 Internal Server Error` - Server-side error

## File Naming Rules

### Valid Formats

**Timestamped Format (Recommended):**
- Format: `YYYYMMDD-hhmm.yml`
- Examples: 
  - `20250122-1430.yml`
  - `20250101-0000.yml`
  - `20251231-2359.yml`

**Legacy Format:**
- Format: `emon_config.yml`
- Only one allowed, used as fallback

### Invalid Formats
- `2025-01-22-14-30.yml` ❌
- `2025_01_22_14_30.yml` ❌
- `settings.yml` ❌
- `config.yaml` ❌ (must be .yml)
- `20250122.yml` ❌ (missing time)

## YAML Content Guidelines

Settings files use YAML format with the following structure:

```yaml
# Temperature sensors
temp:
  0:
    name: Device name
    t0: Sensor name
    t1: Sensor name
    # ... up to t3

# Hot water system
hws:
  0:
    name: Device name
    t0: Sensor name
    # ... up to t6
    p0: Pump name
    p1: Pump name
    # ... up to p2

# Water meters
wtr:
  0:
    name: Device name
    f0: Flow meter
    f0_litresPerPulse: 0.1
    h0: Level sensor

# Rain gauge
rain:
  0:
    name: Device name
    mmPerPulse: 0.2

# Power/pulse counters
pulse:
  0:
    name: Device name
    p0: Counter name
    p0_wPerPulse: 1.0

# Battery monitors
bat:
  0:
    name: Device name
    s0: Current sensor
    v0: Voltage sensor
    v0_reference: true
```

## Integration Examples

### Python Requests

```python
import requests
import json

# List files
response = requests.get('http://localhost:5000/api/settings/list')
files = response.json()

# Read file
response = requests.get(
    'http://localhost:5000/api/settings/read/20250122-1430.yml'
)
content = response.json()['content']

# Validate YAML
response = requests.post(
    'http://localhost:5000/api/settings/validate',
    json={'content': 'temp:\n  0:\n    name: Test'}
)

# Save file
response = requests.post(
    'http://localhost:5000/api/settings/save',
    json={
        'filename': '20250122-1430.yml',
        'content': 'temp:\n  0:\n    name: House'
    }
)

# Delete file
response = requests.post(
    'http://localhost:5000/api/settings/delete/20250122-1430.yml'
)
```

### JavaScript Fetch

```javascript
// List files
fetch('/api/settings/list')
  .then(r => r.json())
  .then(data => console.log(data.files));

// Read file
fetch('/api/settings/read/20250122-1430.yml')
  .then(r => r.json())
  .then(data => console.log(data.content));

// Save file
fetch('/api/settings/save', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    filename: '20250122-1430.yml',
    content: 'temp:\n  0:\n    name: Test'
  })
})
.then(r => r.json())
.then(data => console.log(data));
```

### cURL

```bash
# List files
curl http://localhost:5000/api/settings/list

# Read file
curl http://localhost:5000/api/settings/read/20250122-1430.yml

# Validate
curl -X POST http://localhost:5000/api/settings/validate \
  -H "Content-Type: application/json" \
  -d '{"content":"temp:\n  0:\n    name: Test"}'

# Save
curl -X POST http://localhost:5000/api/settings/save \
  -H "Content-Type: application/json" \
  -d '{"filename":"20250122-1430.yml","content":"temp:\n  0:\n    name: Test"}'

# Delete
curl -X POST http://localhost:5000/api/settings/delete/20250122-1430.yml
```

## Response Headers

All responses include:
- `Content-Type: application/json`
- Standard HTTP status codes

## Rate Limiting

No rate limiting is currently implemented. Heavy usage should be monitored.

## Caching

- Settings file list is refreshed on each request
- Individual file contents are not cached by the API
- Implement client-side caching as needed

## Version

- Current Version: 1.0
- Last Updated: January 2026
- API Stability: Stable

---

For more information, see [SETTINGS_MANAGER_README.md](SETTINGS_MANAGER_README.md)
