/**
 * Upload Photo page - mobile-friendly JavaScript
 *
 * Supports pre-selection of a recording via ?recording_id=<id> URL parameter.
 */

// Pre-selected recording from URL param
const urlParams = new URLSearchParams(window.location.search);
const preselectedId = urlParams.get('recording_id') ? parseInt(urlParams.get('recording_id')) : null;

let selectedFile = null;
let recordingsCache = [];  // Cached list so we can populate title/description on select

// === Initialization ===
document.addEventListener('DOMContentLoaded', () => {
    loadRecordings();
    setupFileInput();
});

// === Load recordings into selector ===
async function loadRecordings() {
    const select = document.getElementById('recordingSelect');
    const noNote = document.getElementById('noRecordingsNote');

    try {
        const response = await fetch('api/recordings');
        const data = await response.json();

        if (!data.success || data.recordings.length === 0) {
            select.innerHTML = '<option value="">No recordings found</option>';
            noNote.style.display = 'block';
            return;
        }

        // Any recording not yet published can be edited, at whatever stage
        const usable = data.recordings.filter(r => r.status !== 'published');

        if (usable.length === 0) {
            select.innerHTML = '<option value="">No unpublished recordings</option>';
            noNote.style.display = 'block';
            return;
        }

        // Sort: active first, then most recent
        usable.sort((a, b) => {
            if (a.status === 'active' && b.status !== 'active') return -1;
            if (b.status === 'active' && a.status !== 'active') return 1;
            return new Date(b.start_time) - new Date(a.start_time);
        });

        recordingsCache = usable;

        select.innerHTML = usable.map(r => {
            const liveTag = r.status === 'active' ? '🔴 LIVE — ' : '';
            const dateStr = r.start_time
                ? new Date(r.start_time.replace(' ', 'T') + 'Z').toLocaleString()
                : '';
            const selected = r.id === preselectedId ? ' selected' : '';
            return `<option value="${r.id}"${selected}>${liveTag}${r.name} (${dateStr})</option>`;
        }).join('');

        // Auto-select the first active recording when no preselect in URL
        if (!preselectedId) {
            const active = usable.find(r => r.status === 'active');
            if (active) {
                select.value = active.id;
            }
        }

        // Populate title/description for the initially-selected recording
        onRecordingChange();

    } catch (err) {
        console.error('Failed to load recordings:', err);
        select.innerHTML = '<option value="">Error loading recordings</option>';
    }
}

// === Populate title and description when recording selection changes ===
function onRecordingChange() {
    const select = document.getElementById('recordingSelect');
    const id = parseInt(select.value);
    const recording = recordingsCache.find(r => r.id === id);

    document.getElementById('postTitle').value = recording ? (recording.name || '') : '';
    document.getElementById('postDescription').value = recording ? (recording.description || '') : '';
}

// === File input: show preview and enable upload button ===
function setupFileInput() {
    const input = document.getElementById('photoInput');
    input.addEventListener('change', (e) => {
        if (e.target.files && e.target.files[0]) {
            selectedFile = e.target.files[0];
            showPreview(selectedFile);
            document.getElementById('uploadBtn').disabled = false;
        }
    });
}

function showPreview(file) {
    const reader = new FileReader();
    reader.onload = (e) => {
        const img = document.getElementById('previewImg');
        const placeholder = document.getElementById('previewPlaceholder');
        img.src = e.target.result;
        img.style.display = 'block';
        placeholder.style.display = 'none';
    };
    reader.readAsDataURL(file);
}

// === Upload photo ===
async function uploadPhoto() {
    const recordingId = document.getElementById('recordingSelect').value;
    const title = document.getElementById('postTitle').value.trim();
    const description = document.getElementById('postDescription').value.trim();
    const byline = document.getElementById('photoByline').value.trim();

    if (!recordingId) {
        showResult('Please select a recording first.', 'error');
        return;
    }

    if (!selectedFile) {
        showResult('Please select a photo first.', 'error');
        return;
    }

    const uploadBtn = document.getElementById('uploadBtn');
    uploadBtn.disabled = true;
    uploadBtn.textContent = 'Uploading…';

    try {
        const saved = await saveDetails(recordingId, title, description);
        if (saved.error) {
            showResult(`Upload failed: ${saved.error}`, 'error');
            uploadBtn.disabled = false;
            restoreUploadBtn();
            return;
        }

        // Upload the photo
        const formData = new FormData();
        formData.append('file', selectedFile);
        if (byline) {
            formData.append('caption', byline);
        }

        const response = await fetch(`api/recordings/${recordingId}/images`, {
            method: 'POST',
            body: formData
        });

        const data = await response.json();

        if (data.success) {
            showResult('Photo uploaded successfully!', 'success');
            resetForm();
        } else {
            showResult(`Upload failed: ${data.error}`, 'error');
            uploadBtn.disabled = false;
            restoreUploadBtn();
        }

    } catch (err) {
        console.error('Upload failed:', err);
        showResult('Upload failed. Please check your connection and try again.', 'error');
        uploadBtn.disabled = false;
        restoreUploadBtn();
    }
}

// === Save title and description to the recording if either has changed ===
// Returns {changed} on success or {error} when the recorder refused it.
async function saveDetails(recordingId, title, description) {
    const cached = recordingsCache.find(r => r.id === parseInt(recordingId));
    const titleChanged = title && cached && title !== (cached.name || '');
    const descChanged = description !== (cached ? (cached.description || '') : '');

    if (!titleChanged && !descChanged) {
        return { changed: false };
    }

    const updateBody = {};
    if (titleChanged) updateBody.name = title;
    if (descChanged) updateBody.description = description;

    const response = await fetch(`api/recordings/${recordingId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updateBody)
    });
    const data = await response.json();
    if (!data.success) {
        return { error: data.error };
    }

    // Update cache so a second save reflects the saved values
    if (cached) {
        if (titleChanged) cached.name = title;
        if (descChanged) cached.description = description;
    }
    return { changed: true };
}

// === Save title and description without a photo ===
async function saveDetailsOnly() {
    const recordingId = document.getElementById('recordingSelect').value;
    if (!recordingId) {
        showResult('Please select a recording first.', 'error');
        return;
    }

    const btn = document.getElementById('saveDetailsBtn');
    btn.disabled = true;
    try {
        const saved = await saveDetails(
            recordingId,
            document.getElementById('postTitle').value.trim(),
            document.getElementById('postDescription').value.trim()
        );
        if (saved.error) {
            showResult(`Save failed: ${saved.error}`, 'error');
        } else if (saved.changed) {
            showResult('Title and description saved.', 'success');
        } else {
            showResult('Nothing has changed.', 'success');
        }
    } catch (err) {
        console.error('Save failed:', err);
        showResult('Save failed. Please check your connection and try again.', 'error');
    } finally {
        btn.disabled = false;
    }
}

function restoreUploadBtn() {
    const btn = document.getElementById('uploadBtn');
    btn.innerHTML = `<svg style="width:1em;height:1em;vertical-align:-0.125em;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round" viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg> Upload Photo`;
}

// === Reset form after successful upload ===
function resetForm() {
    selectedFile = null;
    document.getElementById('photoInput').value = '';
    document.getElementById('photoByline').value = '';
    document.getElementById('previewImg').style.display = 'none';
    document.getElementById('previewPlaceholder').style.display = 'block';
    const btn = document.getElementById('uploadBtn');
    btn.disabled = true;
    restoreUploadBtn();
}

// === Show result message ===
function showResult(message, type) {
    const el = document.getElementById('uploadResult');
    el.textContent = message;
    el.className = `upload-result ${type}`;

    // Auto-hide success message after 5 seconds
    if (type === 'success') {
        setTimeout(() => {
            el.className = 'upload-result';
        }, 5000);
    }
}
