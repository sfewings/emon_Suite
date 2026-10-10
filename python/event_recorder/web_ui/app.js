/**
 * Event Recorder - Frontend JavaScript SPA
 *
 * Handles all frontend interactions, API calls, and view management.
 * Follows vanilla JavaScript pattern from emon_settings_web.
 */

// === SVG Icons (inline for dynamically generated HTML) ===
// Feather Icons style: stroke-based, currentColor, no external dependency.
const Icons = {
    stop:    `<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/></svg>`,
    view:    `<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>`,
    camera:  `<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg>`,
    process: `<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>`,
    publish: `<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="16 16 12 12 8 16"/><line x1="12" y1="12" x2="12" y2="21"/><path d="M20.39 18.39A5 5 0 0 0 18 9h-1.26A8 8 0 1 0 3 16.3"/></svg>`,
    delete:  `<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/></svg>`,
    upload:  `<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>`,
};

// === Global State ===
let currentView = 'dashboard';
let statusPollInterval = null;
let recordings = [];
let serviceStatus = null;
let pollInProgress = false;

// === Initialization ===
document.addEventListener('DOMContentLoaded', () => {
    console.log('Event Recorder UI loaded');

    // Setup navigation
    setupNavigation();

    // Setup forms
    setupForms();

    // Initial load
    loadDashboard();

    // Start status polling (every 2 seconds)
    startStatusPolling();
});

// === Navigation ===
function setupNavigation() {
    const navItems = document.querySelectorAll('.nav-item');

    navItems.forEach(item => {
        item.addEventListener('click', () => {
            const view = item.dataset.view;
            switchView(view);

            // Update active state
            navItems.forEach(i => i.classList.remove('active'));
            item.classList.add('active');
        });
    });
}

function switchView(viewName) {
    currentView = viewName;

    // Hide all views
    document.querySelectorAll('.view').forEach(view => {
        view.classList.remove('active');
    });

    // Show selected view
    const viewId = `${viewName}View`;
    const viewElement = document.getElementById(viewId);
    if (viewElement) {
        viewElement.classList.add('active');
    }

    // Load view-specific data
    switch(viewName) {
        case 'dashboard':
            loadDashboard();
            break;
        case 'recordings':
            loadRecordings();
            break;
        case 'manual':
            loadManualControl();
            break;
        case 'settings':
            loadWordPressSettings();
            loadSettings();
            break;
    }
}

// === Status Polling ===
function startStatusPolling() {
    // Poll immediately
    pollStatus();

    // Then poll every 1 second
    statusPollInterval = setInterval(pollStatus, 1000);
}

function stopStatusPolling() {
    if (statusPollInterval) {
        clearInterval(statusPollInterval);
        statusPollInterval = null;
    }
}

async function pollStatus() {
    // Skip if previous poll still running
    if (pollInProgress) return;
    pollInProgress = true;

    try {
        const response = await fetch('api/status');
        const data = await response.json();

        if (data.success) {
            serviceStatus = data.status;
            updateStatusDisplay(data.status);
        } else {
            updateStatusDisplay(null, data.error);
        }

        // Refresh current view data
        await refreshCurrentView();

    } catch (error) {
        console.error('Status poll failed:', error);
        updateStatusDisplay(null, 'Connection failed');
    } finally {
        pollInProgress = false;
    }
}

async function refreshCurrentView() {
    switch(currentView) {
        case 'dashboard':
            await Promise.all([
                loadActiveRecordings(),
                loadServiceStatus(),
                loadRecentRecordings()
            ]);
            break;
        case 'recordings':
            await loadRecordings();
            break;
        case 'manual':
            await loadActiveRecordingsForStop();
            break;
        // settings view doesn't need frequent refresh
    }
}

function updateStatusDisplay(status, error = null) {
    const statusDot = document.getElementById('statusDot');
    const statusText = document.getElementById('statusText');

    if (error) {
        statusDot.className = 'status-dot offline';
        statusText.textContent = error;
        return;
    }

    statusDot.className = 'status-dot online';
    statusText.textContent = 'Service Running';

    // Update sidebar stats
    if (status.database) {
        document.getElementById('totalRecordings').textContent =
            status.database.recordings_count || 0;
        document.getElementById('totalMessages').textContent =
            (status.database.recording_data_count || 0).toLocaleString();
        document.getElementById('dbSize').textContent =
            status.database.database_size_mb
                ? `${status.database.database_size_mb.toFixed(1)} MB`
                : '-';
    }
}

// === Dashboard View ===
async function loadDashboard() {
    await loadActiveRecordings();
    await loadServiceStatus();
    await loadRecentRecordings();
}

function refreshDashboard() {
    loadDashboard();
}

async function loadActiveRecordings() {
    try {
        const response = await fetch('api/recordings?status=active');
        const data = await response.json();

        const container = document.getElementById('activeRecordings');

        if (data.success && data.recordings.length > 0) {
            container.innerHTML = data.recordings.map(rec => `
                <div class="recording-card active">
                    <div class="recording-header">
                        <h4>${escapeHtml(rec.name)}</h4>
                        <span class="badge badge-success">Active</span>
                    </div>
                    <div class="recording-body">
                        <p><strong>Started:</strong> ${formatDateTime(rec.start_time)}</p>
                        <p><strong>Duration:</strong> ${formatDuration(rec.start_time)}</p>
                        <p><strong>Messages:</strong> ${(rec.message_count || 0).toLocaleString()}</p>
                    </div>
                    <div class="recording-actions">
                        <button class="btn btn-sm btn-danger"
                                onclick="stopRecording(${rec.id})">
                            ${Icons.stop} Stop
                        </button>
                        <button class="btn btn-sm btn-secondary"
                                onclick="viewRecording(${rec.id})">
                            ${Icons.view} View
                        </button>
                    </div>
                </div>
            `).join('');
        } else {
            container.innerHTML = '<p class="empty-state">No active recordings</p>';
        }
    } catch (error) {
        console.error('Failed to load active recordings:', error);
        showToast('Failed to load active recordings', 'error');
    }
}

async function loadServiceStatus() {
    if (!serviceStatus) return;

    // No optional chaining here or anywhere in this file: the boat's iPad is on
    // iOS 12, where it is a syntax error that stops the whole script (TR-13).
    const buffer = serviceStatus.buffer_status || {};

    // MQTT Status
    const mqttConnected = buffer.connected || false;
    document.getElementById('mqttStatus').innerHTML = mqttConnected
        ? '<span class="status-online">✓ Connected</span>'
        : '<span class="status-offline">✗ Disconnected</span>';

    // Buffer Size
    const bufferSize = buffer.buffer_size || 0;
    const maxBuffer = buffer.max_buffer_size || 1000;
    document.getElementById('bufferSize').textContent = `${bufferSize} / ${maxBuffer}`;

    // Subscribed Topics
    const topics = buffer.subscribed_topics || [];
    document.getElementById('subscribedTopics').textContent = topics.length;

    // Active Monitors
    const monitors = serviceStatus.monitor_status || {};
    const activeCount = Object.keys(monitors).filter(
        key => monitors[key].enabled
    ).length;
    document.getElementById('activeMonitors').textContent = activeCount;

    // WordPress Status
    const wp = serviceStatus.wordpress;
    if (wp) {
        const wpEl = document.getElementById('wpStatus');
        if (wp.configured) {
            wpEl.innerHTML = `<span class="status-online">Configured</span>`;
        } else {
            wpEl.innerHTML = `<span class="status-offline">Not Configured</span>`;
        }
    }
}

async function loadRecentRecordings() {
    try {
        const response = await fetch('api/recordings?limit=5');
        const data = await response.json();

        const container = document.getElementById('recentRecordings');

        if (data.success && data.recordings.length > 0) {
            container.innerHTML = data.recordings.map(rec => `
                <div class="recording-item" onclick="viewRecording(${rec.id})">
                    <div class="recording-info">
                        <strong>${escapeHtml(rec.name)}</strong>
                        <span class="recording-meta">
                            ${formatDateTime(rec.start_time)} •
                            ${(rec.message_count || 0).toLocaleString()} messages
                        </span>
                    </div>
                    <span class="badge badge-${getStatusColor(rec.stage)}">
                        ${rec.stage}
                    </span>
                </div>
            `).join('');
        } else {
            container.innerHTML = '<p class="empty-state">No recent recordings</p>';
        }
    } catch (error) {
        console.error('Failed to load recent recordings:', error);
    }
}

// === Recordings View ===
async function loadRecordings() {
    try {
        const filterSelect = document.getElementById('statusFilter');
        const statusFilter = (filterSelect && filterSelect.value) || '';
        const url = statusFilter
            ? `api/recordings?status=${statusFilter}`
            : 'api/recordings';

        const response = await fetch(url);
        const data = await response.json();

        const container = document.getElementById('recordingsList');

        if (data.success && data.recordings.length > 0) {
            recordings = data.recordings;

            container.innerHTML = `
                <table class="table">
                    <thead>
                        <tr>
                            <th>ID</th>
                            <th>Name</th>
                            <th>Status</th>
                            <th>Started</th>
                            <th>Messages</th>
                            <th>Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${recordings.map(rec => `
                            <tr>
                                <td>${rec.id}</td>
                                <td>${escapeHtml(rec.name)}</td>
                                <td>
                                    <span class="badge badge-${getStatusColor(rec.stage)}">
                                        ${rec.stage}${rec.artefacts === 'stale' ? ' (out of date)' : ''}
                                    </span>
                                </td>
                                <td>${formatDateTime(rec.start_time)}</td>
                                <td>${(rec.message_count || 0).toLocaleString()}</td>
                                <td>
                                    <button class="btn btn-sm btn-primary"
                                            onclick="viewRecording(${rec.id})">
                                        ${Icons.view} View
                                    </button>
                                    ${rec.stage === 'stopped' ? `
                                        <button class="btn btn-sm btn-success"
                                                onclick="processRecording(${rec.id})">
                                            ${Icons.process} Process
                                        </button>
                                    ` : ''}
                                    ${['stopped', 'processing', 'processed'].includes(rec.stage) ? `
                                        <button class="btn btn-sm btn-wp"
                                                onclick="publishRecording(${rec.id})">
                                            ${Icons.publish} Publish
                                        </button>
                                    ` : ''}
                                    ${rec.status !== 'active' ? `
                                        <button class="btn btn-sm btn-danger"
                                                onclick="deleteRecording(${rec.id})">
                                            ${Icons.delete} Delete
                                        </button>
                                    ` : ''}
                                </td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            `;
        } else {
            container.innerHTML = '<p class="empty-state">No recordings found</p>';
        }
    } catch (error) {
        console.error('Failed to load recordings:', error);
        showToast('Failed to load recordings', 'error');
    }
}

function filterRecordings() {
    loadRecordings();
}

// === Manual Control View ===
function loadManualControl() {
    loadActiveRecordingsForStop();
}

async function loadActiveRecordingsForStop() {
    try {
        const response = await fetch('api/recordings?status=active');
        const data = await response.json();

        const container = document.getElementById('stopRecordingSection');

        if (data.success && data.recordings.length > 0) {
            container.innerHTML = data.recordings.map(rec => `
                <div class="recording-item">
                    <div class="recording-info">
                        <strong>${escapeHtml(rec.name)}</strong>
                        <span class="recording-meta">
                            Started: ${formatDateTime(rec.start_time)} •
                            Duration: ${formatDuration(rec.start_time)} •
                            ${(rec.message_count || 0).toLocaleString()} messages
                        </span>
                    </div>
                    <button class="btn btn-danger" onclick="stopRecording(${rec.id})">
                        ${Icons.stop} Stop Recording
                    </button>
                </div>
            `).join('');
        } else {
            container.innerHTML = '<p class="empty-state">No active recordings to stop</p>';
        }
    } catch (error) {
        console.error('Failed to load active recordings:', error);
    }
}

// === Forms ===
function setupForms() {
    const startForm = document.getElementById('startRecordingForm');
    if (startForm) {
        startForm.addEventListener('submit', handleStartRecording);
    }
}

async function handleStartRecording(event) {
    event.preventDefault();

    const name = document.getElementById('recordingName').value.trim();
    const description = document.getElementById('recordingDescription').value.trim();
    const topicsText = document.getElementById('recordingTopics').value.trim();

    // Parse topics (one per line)
    const topics = topicsText
        .split('\n')
        .map(t => t.trim())
        .filter(t => t.length > 0);

    if (topics.length === 0) {
        showToast('Please specify at least one topic', 'error');
        return;
    }

    try {
        const response = await fetch('api/recordings', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ name, description, topics })
        });

        const data = await response.json();

        if (data.success) {
            showToast(`Recording ${data.recording_id} started`, 'success');

            // Clear form
            document.getElementById('startRecordingForm').reset();

            // Switch to dashboard
            switchView('dashboard');
        } else {
            showToast(`Failed to start recording: ${data.error}`, 'error');
        }
    } catch (error) {
        console.error('Failed to start recording:', error);
        showToast('Failed to start recording', 'error');
    }
}

// === Recording Actions ===
async function stopRecording(recordingId) {
    if (!confirm(`Stop recording ${recordingId}?`)) {
        return;
    }

    try {
        const response = await fetch(`api/recordings/${recordingId}/stop`, {
            method: 'POST'
        });

        const data = await response.json();

        if (data.success) {
            showToast(data.message, 'success');

            // Refresh current view
            if (currentView === 'dashboard') {
                loadDashboard();
            } else if (currentView === 'manual') {
                loadManualControl();
            }
        } else {
            showToast(`Failed to stop recording: ${data.error}`, 'error');
        }
    } catch (error) {
        console.error('Failed to stop recording:', error);
        showToast('Failed to stop recording', 'error');
    }
}

async function processRecording(recordingId) {
    if (!confirm(`Process recording ${recordingId}? This will generate plots and statistics.`)) {
        return;
    }

    showToast('Processing recording... This may take a minute', 'info');

    try {
        const response = await fetch(`api/recordings/${recordingId}/process`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({})
        });

        const data = await response.json();

        if (data.success) {
            showToast(`Recording processed: ${data.results.plots.length} plots generated`, 'success');
            loadRecordings();
        } else {
            showToast(`Processing failed: ${data.error}`, 'error');
        }
    } catch (error) {
        console.error('Failed to process recording:', error);
        showToast('Failed to process recording', 'error');
    }
}

async function reprocessRecording(recordingId) {
    if (!confirm(`Reprocess recording ${recordingId}? Plots, statistics and exports will be regenerated from the raw data, replacing the current ones. Uploaded photos are kept.`)) {
        return;
    }

    showToast('Reprocessing recording... This may take a minute', 'info');

    try {
        const response = await fetch(`api/recordings/${recordingId}/process`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({})
        });

        const data = await response.json();

        if (data.success) {
            showToast(`Recording reprocessed: ${data.results.plots.length} plots generated`, 'success');
            loadRecordings();
        } else {
            showToast(`Reprocessing failed: ${data.error}`, 'error');
        }
    } catch (error) {
        console.error('Failed to reprocess recording:', error);
        showToast('Failed to reprocess recording', 'error');
    }
}

async function deleteRecording(recordingId) {
    if (!confirm(`Delete recording ${recordingId}? This cannot be undone.`)) {
        return;
    }

    try {
        const response = await fetch(`api/recordings/${recordingId}`, {
            method: 'DELETE'
        });

        const data = await response.json();

        if (data.success) {
            showToast(data.message, 'success');
            loadRecordings();
        } else {
            showToast(`Failed to delete recording: ${data.error}`, 'error');
        }
    } catch (error) {
        console.error('Failed to delete recording:', error);
        showToast('Failed to delete recording', 'error');
    }
}

// === WordPress Functions ===
async function publishRecording(recordingId) {
    if (!confirm(`Publish recording ${recordingId} to WordPress?`)) {
        return;
    }

    showToast('Publishing to WordPress...', 'info');

    try {
        // Publishing runs in the background on the recorder (TR-11): this
        // starts it, then follows it until it is done or failed
        const response = await fetch(`api/recordings/${recordingId}/publish`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                category: 'Track Logs'
            })
        });

        const data = await response.json();
        if (!data.success) {
            showToast(`Publish failed: ${data.error}`, 'error');
            return;
        }
        followPublish(recordingId, data.job.step);
    } catch (error) {
        console.error('Failed to publish recording:', error);
        showToast('Failed to publish to WordPress', 'error');
    }
}

async function followPublish(recordingId, lastStep) {
    let job;
    try {
        const response = await fetch(`api/recordings/${recordingId}/publish`);
        job = (await response.json()).job;
    } catch (error) {
        // The recorder carries on publishing whether or not this page can
        // see it, so a missed poll is retried rather than reported as failure
        setTimeout(() => followPublish(recordingId, lastStep), 2000);
        return;
    }
    if (!job) {
        showToast('Lost track of the publish: the recorder may have restarted', 'error');
        return;
    }

    if (job.state === 'running') {
        if (job.step !== lastStep) {
            showToast(job.step, 'info');
        }
        setTimeout(() => followPublish(recordingId, job.step), 2000);
        return;
    }

    if (job.state === 'done') {
        const failed = job.post.failed_uploads || [];
        if (failed.length) {
            showToast(`Published, but ${failed.length} file(s) did not upload: ${failed.join(', ')}`, 'error');
        } else {
            showToast('Published to WordPress successfully', 'success');
        }
        if (job.post.link) {
            showToast(`Post URL: ${job.post.link}`, 'info');
        }
    } else {
        showToast(`Publish failed: ${job.error}`, 'error');
    }
    loadRecordings();
}

async function resetRecordingToProcessed(recordingId) {
    if (!confirm(`Reset recording ${recordingId} to "processed" status?`)) {
        return;
    }

    try {
        const response = await fetch(`api/recordings/${recordingId}/reset`, {
            method: 'POST'
        });
        const data = await response.json();

        if (data.success) {
            showToast('Recording reset to processed', 'success');
            loadRecordings();
        } else {
            showToast(`Reset failed: ${data.error}`, 'error');
        }
    } catch (error) {
        console.error('Failed to reset recording:', error);
        showToast('Failed to reset recording status', 'error');
    }
}

async function testWordPressConnection() {
    const resultEl = document.getElementById('wpTestResult');
    resultEl.innerHTML = '<span class="badge badge-info">Testing...</span>';

    try {
        const response = await fetch('api/wordpress/test');
        const data = await response.json();

        if (data.success) {
            resultEl.innerHTML = `<span class="badge badge-success">Connected</span> ${escapeHtml(data.message)}`;
        } else {
            resultEl.innerHTML = `<span class="badge badge-danger">Failed</span> ${escapeHtml(data.error)}`;
        }
    } catch (error) {
        resultEl.innerHTML = '<span class="badge badge-danger">Error</span> Could not reach server';
    }
}

async function loadWordPressSettings() {
    const container = document.getElementById('wpSettingsStatus');
    if (!container) return;

    // Use cached serviceStatus if available
    const wp = serviceStatus && serviceStatus.wordpress;

    if (wp && wp.configured) {
        container.innerHTML = `
            <div class="status-grid">
                <div class="status-item">
                    <span class="status-label">Status:</span>
                    <span class="status-value"><span class="status-online">Configured</span></span>
                </div>
                <div class="status-item">
                    <span class="status-label">Site URL:</span>
                    <span class="status-value">${escapeHtml(wp.site_url)}</span>
                </div>
            </div>
            <div style="margin-top: 1rem;">
                <button class="btn btn-primary" onclick="testWordPressConnection()">
                    Test Connection
                </button>
                <span id="wpTestResult" style="margin-left: 1rem;"></span>
            </div>
            <p style="margin-top: 1rem; font-size: 0.85rem; color: var(--text-light);">
                WordPress credentials are configured via environment variables or
                <code>event_recorder_config.yml</code>.
            </p>
        `;
    } else {
        container.innerHTML = `
            <div class="status-grid">
                <div class="status-item">
                    <span class="status-label">Status:</span>
                    <span class="status-value"><span class="status-offline">Not Configured</span></span>
                </div>
            </div>
            <p style="margin-top: 1rem;">
                WordPress publishing requires configuration. Add the following to your
                environment or <code>event_recorder_config.yml</code>:
            </p>
            <ul style="margin-top: 0.5rem; padding-left: 1.5rem; font-size: 0.9rem;">
                <li><code>WP_SITE_URL</code> - WordPress site URL</li>
                <li><code>WP_USERNAME</code> - WordPress username</li>
                <li><code>WP_APP_PASSWORD</code> - Application password</li>
            </ul>
            <p style="margin-top: 0.75rem; font-size: 0.85rem; color: var(--text-light);">
                Generate an Application Password in WordPress: Users &rarr; Profile &rarr; Application Passwords
            </p>
        `;
    }
}

async function loadSettings() {
    try {
        const response = await fetch('api/settings');
        const data = await response.json();
        if (data.success) {
            const toggle = document.getElementById('autoProcessOnStop');
            if (toggle) toggle.checked = data.settings.auto_process_on_stop;
        }
    } catch (error) {
        console.error('Failed to load settings:', error);
    }
}

async function saveAutoProcessSetting(enabled) {
    try {
        const response = await fetch('api/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ auto_process_on_stop: enabled })
        });
        const data = await response.json();
        if (data.success) {
            showToast(enabled ? 'Auto-process enabled' : 'Auto-process disabled', 'success');
        } else {
            showToast('Failed to save setting', 'error');
        }
    } catch (error) {
        showToast('Failed to save setting', 'error');
    }
}

// A recording opens on the Log page, the same page the crew use from the racing app:
// title, crew, time, wind, categories, description, photos and notes, editable until
// it is published, with this dashboard's own tools at the bottom (from=events). One
// page to edit a recording on, rather than this modal and that page drifting apart.
function viewRecording(recordingId) {
    location.assign(`log/?id=${recordingId}&from=events`);
}

function showModal() {
    document.getElementById('recordingModal').classList.add('active');
}

function closeModal() {
    document.getElementById('recordingModal').classList.remove('active');
}

// Close modal on background click
var recordingModal = document.getElementById('recordingModal');
if (recordingModal) recordingModal.addEventListener('click', (e) => {
    if (e.target.id === 'recordingModal') {
        closeModal();
    }
});

// === Toast Notifications ===
function showToast(message, type = 'info') {
    const container = document.getElementById('toastContainer');
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;

    container.appendChild(toast);

    // Trigger animation
    setTimeout(() => toast.classList.add('show'), 10);

    // Remove after 3 seconds
    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

// === Utility Functions ===
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Database stores UTC timestamps without a timezone marker (e.g. "2026-02-26 06:27:07").
// Without 'Z', JavaScript treats them as local time, causing an offset equal to the
// local UTC offset. This helper forces UTC parsing so times display correctly.
function parseUtcTimestamp(timestamp) {
    if (!timestamp) return null;
    // Replace space separator with T for ISO 8601, then append Z to mark as UTC.
    const iso = timestamp.includes('T') ? timestamp : timestamp.replace(' ', 'T');
    const utc = (iso.endsWith('Z') || iso.includes('+')) ? iso : iso + 'Z';
    return new Date(utc);
}

function formatDateTime(timestamp) {
    if (!timestamp) return '-';
    const date = parseUtcTimestamp(timestamp);
    return date.toLocaleString();
}

function formatDuration(startTime) {
    if (!startTime) return '-';

    const start = parseUtcTimestamp(startTime);
    const now = new Date();
    const diff = now - start;

    const seconds = Math.floor(diff / 1000);
    const minutes = Math.floor(seconds / 60);
    const hours = Math.floor(minutes / 60);

    if (hours > 0) {
        return `${hours}h ${minutes % 60}m`;
    } else if (minutes > 0) {
        return `${minutes}m ${seconds % 60}s`;
    } else {
        return `${seconds}s`;
    }
}

function getStatusColor(status) {
    const colors = {
        'active': 'success',
        'stopped': 'info',
        'processing': 'warning',
        'processed': 'info',
        'publishing': 'warning',
        'published': 'success',
        'failed': 'danger'
    };
    return colors[status] || 'secondary';
}

// === Cleanup on page unload ===
window.addEventListener('beforeunload', () => {
    stopStatusPolling();
});
