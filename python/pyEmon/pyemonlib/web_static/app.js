/**
 * Emon Settings Manager - Frontend Application
 * 
 * Provides UI for managing timestamped settings files
 */

// Global state
let currentFile = null;
let settings = {};
let hasChanges = false;

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    loadSettingsFiles();
    
    // Update character and line count when editing
    const editor = document.getElementById('yamlEditor');
    if (editor) {
        editor.addEventListener('input', () => {
            updateEditorStatus();
            hasChanges = true;
        });
    }
    
    // Handle beforeunload to warn about unsaved changes
    window.addEventListener('beforeunload', (e) => {
        if (hasChanges) {
            e.preventDefault();
            e.returnValue = '';
        }
    });
});

/**
 * Load and display list of available settings files
 */
async function loadSettingsFiles() {
    try {
        const response = await fetch('/api/settings/list');
        const data = await response.json();
        
        if (!data.success) {
            showError('Failed to load settings files: ' + data.error);
            return;
        }
        
        const fileList = document.getElementById('fileList');
        
        if (data.files.length === 0) {
            fileList.innerHTML = '<p class="loading">No settings files found</p>';
            return;
        }
        
        // Sort files chronologically (newest first)
        const files = data.files.sort((a, b) => {
            if (!a.datetime || !b.datetime) return 0;
            return new Date(b.datetime) - new Date(a.datetime);
        });
        
        fileList.innerHTML = files.map(file => {
            const dateStr = file.datetime ? new Date(file.datetime).toLocaleString() : 'N/A';
            const activeClass = file.isCurrent ? 'active' : '';
            return `
                <div class="file-item ${activeClass}" onclick="loadFile('${file.filename}')">
                    <div class="file-item-name">${escapeHtml(file.filename)}</div>
                    <div class="file-item-date">${dateStr}</div>
                    ${file.isCurrent ? '<div class="file-item-badge">Current</div>' : ''}
                </div>
            `;
        }).join('');
        
    } catch (error) {
        console.error('Error loading settings files:', error);
        showError('Error loading settings files: ' + error.message);
    }
}

/**
 * Load and display contents of a specific settings file
 */
async function loadFile(filename) {
    try {
        const response = await fetch(`/api/settings/read/${encodeURIComponent(filename)}`);
        const data = await response.json();
        
        if (!data.success) {
            showError('Failed to load file: ' + data.error);
            return;
        }
        
        currentFile = filename;
        hasChanges = false;
        
        // Show editor screen
        document.getElementById('welcome-screen').style.display = 'none';
        document.getElementById('editor-screen').style.display = 'flex';
        
        // Update header
        document.getElementById('editorFileName').textContent = escapeHtml(filename);
        
        const isLegacy = filename === 'emon_config.yml';
        const status = isLegacy ? '(Legacy configuration file)' : '(Timestamped configuration)';
        document.getElementById('editorFileStatus').textContent = status;
        
        // Populate editor
        const editor = document.getElementById('yamlEditor');
        editor.value = data.content;
        
        // Update delete button visibility
        const deleteBtn = document.getElementById('deleteBtn');
        deleteBtn.style.display = isLegacy ? 'none' : 'block';
        
        // Update editor status
        updateEditorStatus();
        
        // Update file list to show current selection
        document.querySelectorAll('.file-item').forEach(item => {
            const name = item.querySelector('.file-item-name').textContent;
            item.classList.toggle('active', name === filename);
        });
        
        // Clear validation result
        document.getElementById('validationResult').innerHTML = '';
        
        // Load preview
        updatePreview();
        
    } catch (error) {
        console.error('Error loading file:', error);
        showError('Error loading file: ' + error.message);
    }
}

/**
 * Update editor status (character count, line count)
 */
function updateEditorStatus() {
    const editor = document.getElementById('yamlEditor');
    const text = editor.value;
    const lines = text.split('\n').length;
    
    document.getElementById('editorCharCount').textContent = `${text.length} characters`;
    document.getElementById('editorLineCount').textContent = `${lines} lines`;
}

/**
 * Switch between editor tabs
 */
function switchTab(tabName) {
    // Hide all tabs
    document.querySelectorAll('.tab-content').forEach(tab => {
        tab.classList.remove('active');
    });
    
    // Remove active from all buttons
    document.querySelectorAll('.tab-button').forEach(btn => {
        btn.classList.remove('active');
    });
    
    // Show selected tab
    const tabId = tabName + 'Tab';
    const tab = document.getElementById(tabId);
    if (tab) {
        tab.classList.add('active');
    }
    
    // Mark button as active
    event.target.classList.add('active');
    
    // Update preview when switching to preview tab
    if (tabName === 'preview') {
        updatePreview();
    }
}

/**
 * Update YAML preview
 */
function updatePreview() {
    try {
        const editor = document.getElementById('yamlEditor');
        const content = editor.value;
        
        // Try to parse YAML to validate
        const lines = content.split('\n').map(line => escapeHtml(line)).join('\n');
        
        document.getElementById('previewContent').innerHTML = `
            <pre><code>${lines}</code></pre>
        `;
        
        // Highlight syntax if available
        document.querySelectorAll('pre code').forEach(block => {
            if (window.hljs) {
                block.classList.add('language-yaml');
                window.hljs.highlightElement(block);
            }
        });
        
    } catch (error) {
        console.error('Error updating preview:', error);
    }
}

/**
 * Validate YAML syntax
 */
async function validateYAML() {
    try {
        const editor = document.getElementById('yamlEditor');
        const content = editor.value;
        
        const response = await fetch('/api/settings/validate', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ content })
        });
        
        const data = await response.json();
        
        if (!data.success) {
            showValidationError(data.error);
            return;
        }
        
        const resultDiv = document.getElementById('validationResult');
        if (data.valid) {
            resultDiv.className = 'validation-result success';
            resultDiv.innerHTML = '<strong>✓ Valid YAML</strong><br>Your configuration file has valid YAML syntax.';
        } else {
            resultDiv.className = 'validation-result error';
            resultDiv.innerHTML = `<strong>✗ Invalid YAML</strong><br>${escapeHtml(data.message)}`;
        }
        
    } catch (error) {
        console.error('Error validating YAML:', error);
        showError('Error validating YAML: ' + error.message);
    }
}

/**
 * Save current file
 */
async function saveFile() {
    try {
        if (!currentFile) {
            showError('No file selected');
            return;
        }
        
        const editor = document.getElementById('yamlEditor');
        const content = editor.value;
        
        // Validate YAML first
        const validateResponse = await fetch('/api/settings/validate', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ content })
        });
        
        const validateData = await validateResponse.json();
        
        if (!validateData.valid) {
            showError('Cannot save: Invalid YAML syntax\n' + validateData.message);
            return;
        }
        
        // Save file
        const response = await fetch('/api/settings/save', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                filename: currentFile,
                content: content
            })
        });
        
        const data = await response.json();
        
        if (!data.success) {
            showError('Failed to save file: ' + data.error);
            return;
        }
        
        hasChanges = false;
        showSuccess('File saved successfully!');
        loadSettingsFiles(); // Reload file list
        
    } catch (error) {
        console.error('Error saving file:', error);
        showError('Error saving file: ' + error.message);
    }
}

/**
 * Delete current file
 */
async function deleteFile() {
    if (!currentFile || currentFile === 'emon_config.yml') {
        showError('Cannot delete this file');
        return;
    }
    
    const confirmed = confirm(`Are you sure you want to delete "${currentFile}"? This cannot be undone.`);
    if (!confirmed) return;
    
    try {
        const response = await fetch(`/api/settings/delete/${encodeURIComponent(currentFile)}`, {
            method: 'POST'
        });
        
        const data = await response.json();
        
        if (!data.success) {
            showError('Failed to delete file: ' + data.error);
            return;
        }
        
        showSuccess('File deleted successfully!');
        goBackToList();
        loadSettingsFiles();
        
    } catch (error) {
        console.error('Error deleting file:', error);
        showError('Error deleting file: ' + error.message);
    }
}

/**
 * Go back to file list
 */
function goBackToList() {
    if (hasChanges) {
        const confirmed = confirm('You have unsaved changes. Are you sure you want to go back?');
        if (!confirmed) return;
    }
    
    currentFile = null;
    hasChanges = false;
    document.getElementById('welcome-screen').style.display = 'flex';
    document.getElementById('editor-screen').style.display = 'none';
}

/**
 * Show new file dialog
 */
function showNewFileDialog() {
    document.getElementById('newFileDialog').style.display = 'block';
    document.getElementById('modalOverlay').style.display = 'block';
    
    // Auto-populate filename with current date/time
    const now = new Date();
    const year = now.getFullYear();
    const month = String(now.getMonth() + 1).padStart(2, '0');
    const day = String(now.getDate()).padStart(2, '0');
    const hours = String(now.getHours()).padStart(2, '0');
    const minutes = String(now.getMinutes()).padStart(2, '0');
    const filename = `${year}${month}${day}-${hours}${minutes}.yml`;
    
    document.getElementById('newFilename').value = filename;
    
    // Populate existing files dropdown
    populateExistingFilesDropdown();
    
    // Reset template to empty
    document.getElementById('templateSelect').value = 'empty';
    updateNewFileTemplate();
    
    document.getElementById('newFilename').focus();
}

/**
 * Populate the existing files dropdown
 */
async function populateExistingFilesDropdown() {
    try {
        const response = await fetch('/api/settings/list');
        const data = await response.json();
        
        if (!data.success || !data.files || data.files.length === 0) {
            // Hide existing files group if no files available
            document.getElementById('existingFilesGroup').style.display = 'none';
            return;
        }
        
        const group = document.getElementById('existingFilesGroup');
        group.innerHTML = '';
        
        // Add each existing file as an option
        data.files.forEach(file => {
            const option = document.createElement('option');
            option.value = `file:${file.filename}`;
            option.textContent = file.filename;
            group.appendChild(option);
        });
        
        // Show the group if we have files
        group.style.display = 'block';
        
    } catch (error) {
        console.error('Error loading existing files:', error);
    }
}

/**
 * Close new file dialog
 */
function closeNewFileDialog() {
    document.getElementById('newFileDialog').style.display = 'none';
    document.getElementById('modalOverlay').style.display = 'none';
    document.getElementById('newFileError').style.display = 'none';
    document.getElementById('newFileError').textContent = '';
}

/**
 * Update template content in new file dialog
 */
function updateNewFileTemplate() {
    const template = document.getElementById('templateSelect').value;
    const textarea = document.getElementById('newFileContent');
    
    let content = '';
    
    // Handle existing file templates
    if (template.startsWith('file:')) {
        const filename = template.substring(5);
        loadExistingFileAsTemplate(filename);
        return;
    }
    
    switch (template) {
        case 'empty':
            content = '';
            break;
        case 'minimal':
            content = `# Emon Settings Configuration
# Created: ${new Date().toISOString()}

temp:
  0:
    name: Temperature Sensors
hws:
  0:
    name: Hot Water System
wtr:
  0:
    name: Water Meters
`;
            break;
        case 'full':
            content = `# Emon Settings Configuration
# Created: ${new Date().toISOString()}

temp:
  0:
    name: House temperatures
    t0: Sensor 1
    t1: Sensor 2
    t2: Sensor 3
    t3: Sensor 4
  1:
    name: Outdoor temperatures
    t0: North side
    t1: South side

hws:
  0:
    name: Hot water system
    t0: Top of Panel
    t1: Water
    t2: Inlet
    t3: Water 2
    t4: Water 3
    t5: Return
    t6: PCB
    p0: Solar pump
    p1: Heat Exchange pump

wtr:
  0:
    name: Water usage
    f0: Hot water
    f0_litresPerPulse: 0.1
    h0: Rain tank
  1:
    name: Garden
    f0: Mains
    f0_litresPerPulse: 0.1
    f1: Bore
    f1_litresPerPulse: 0.1

rain:
  0:
    name: Rain gauge
    mmPerPulse: 0.2

pulse:
  0:
    name: Power monitoring
    p0: Solar production
    p1: Consumption
    p2: Battery
    p0_wPerPulse: 0.25
    p1_wPerPulse: 1
    p2_wPerPulse: 1

bat:
  0:
    name: Battery monitor
    s0: Main bank
    v0: Battery voltage
    v0_reference: true
`;
            break;
    }
    
    textarea.value = content;
}

/**
 * Load an existing file as template
 */
async function loadExistingFileAsTemplate(filename) {
    try {
        const response = await fetch(`/api/settings/read/${encodeURIComponent(filename)}`);
        const data = await response.json();
        
        if (!data.success) {
            showNewFileError('Failed to load template file: ' + data.error);
            return;
        }
        
        document.getElementById('newFileContent').value = data.content;
        
    } catch (error) {
        console.error('Error loading template file:', error);
        showNewFileError('Error loading template file: ' + error.message);
    }
}

/**
 * Create new settings file
 */
async function createNewFile() {
    try {
        const filename = document.getElementById('newFilename').value.trim();
        const content = document.getElementById('newFileContent').value;
        const errorDiv = document.getElementById('newFileError');
        
        // Validate filename
        if (!filename) {
            showNewFileError('Filename is required');
            return;
        }
        
        // Validate format
        if (filename !== 'emon_config.yml' && !/^\d{8}-\d{4}\.yml$/.test(filename)) {
            showNewFileError('Invalid filename format. Use YYYYMMDD-hhmm.yml (e.g., 20250122-1430.yml) or emon_config.yml');
            return;
        }
        
        // Validate YAML
        const validateResponse = await fetch('/api/settings/validate', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ content })
        });
        
        const validateData = await validateResponse.json();
        
        if (!validateData.valid) {
            showNewFileError('Invalid YAML syntax: ' + validateData.message);
            return;
        }
        
        // Create file
        const response = await fetch('/api/settings/save', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ filename, content })
        });
        
        const data = await response.json();
        
        if (!data.success) {
            showNewFileError(data.error);
            return;
        }
        
        closeNewFileDialog();
        showSuccess('Settings file created successfully!');
        loadSettingsFiles();
        
        // Load the newly created file
        setTimeout(() => {
            loadFile(filename);
        }, 500);
        
    } catch (error) {
        console.error('Error creating file:', error);
        showNewFileError('Error creating file: ' + error.message);
    }
}

/**
 * Show error message in new file dialog
 */
function showNewFileError(message) {
    const errorDiv = document.getElementById('newFileError');
    errorDiv.textContent = message;
    errorDiv.style.display = 'block';
}

/**
 * Show success notification
 */
function showSuccess(message) {
    // Create and show temporary notification
    const notification = document.createElement('div');
    notification.className = 'notification success';
    notification.textContent = '✓ ' + message;
    notification.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        background: #4caf50;
        color: white;
        padding: 1rem 1.5rem;
        border-radius: 4px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.2);
        z-index: 10000;
        animation: slideIn 0.3s ease;
    `;
    
    document.body.appendChild(notification);
    
    setTimeout(() => {
        notification.remove();
    }, 3000);
}

/**
 * Show error notification
 */
function showError(message) {
    // Create and show temporary notification
    const notification = document.createElement('div');
    notification.className = 'notification error';
    notification.textContent = '✗ ' + message;
    notification.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        background: #f44336;
        color: white;
        padding: 1rem 1.5rem;
        border-radius: 4px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.2);
        z-index: 10000;
        animation: slideIn 0.3s ease;
        max-width: 500px;
    `;
    
    document.body.appendChild(notification);
    
    setTimeout(() => {
        notification.remove();
    }, 5000);
}

/**
 * Show validation error
 */
function showValidationError(message) {
    const resultDiv = document.getElementById('validationResult');
    resultDiv.className = 'validation-result error';
    resultDiv.innerHTML = `<strong>✗ Error</strong><br>${escapeHtml(message)}`;
}

/**
 * Escape HTML special characters
 */
function escapeHtml(text) {
    const map = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#039;'
    };
    return text.replace(/[&<>"']/g, m => map[m]);
}

// Refresh file list periodically (every 10 seconds)
setInterval(() => {
    if (!currentFile) {
        loadSettingsFiles();
    }
}, 10000);
