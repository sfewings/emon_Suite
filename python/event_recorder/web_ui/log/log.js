// Event page (FR-27). Plain script, no build step, and nothing newer than Safari 12:
// no optional chaining, no nullish coalescing (tests/test_ios12_floor.py).
//
// Every field saves itself: on leaving it, and 1.5 s after typing stops. Saves are per
// field, so the phone and the iPad can edit different fields at once. When both edit the
// same field the later save stands, and the device that was overtaken is told, with its
// own text, so nothing typed is lost without a word.

(function () {
    'use strict';

    var TEXT_FIELDS = ['title', 'time_line', 'wind', 'excerpt', 'story'];

    // FR-26: worked out from the recording until the crew type over them. The draft
    // holds the crew's text, empty meaning "the recording's"; draft.computed holds
    // the recording's.
    var COMPUTED = { time_line: 'from the recording', wind: 'from the anemometer' };

    function isComputed(field) { return COMPUTED.hasOwnProperty(field); }

    function computedValue(field) {
        var computed = (state && state.draft.computed) || {};
        return isComputed(field) ? (computed[field] || '') : '';
    }

    function showSource(field) {
        if (!isComputed(field)) return;
        var typed = !!state.draft[field];
        var source = document.querySelector('[data-source="' + field + '"]');
        var reset = document.querySelector('[data-reset="' + field + '"]');
        source.textContent = typed ? '' :
            (computedValue(field) ? COMPUTED[field] : 'Not enough data to tell yet');
        reset.hidden = !typed || locked();
    }
    var SAVE_AFTER_MS = 1500;
    var POLL_MS = 5000;
    var PUBLISH_POLL_MS = 2000;

    var params = new URLSearchParams(location.search);
    var recordingId = params.get('id') ? parseInt(params.get('id'), 10) : null;
    var state = null;              // the last answer from api/state
    var known = {};                // field -> revision this page last saw or saved
    var dirty = {};                // field -> true while an edit is not yet saved
    var timers = {};
    var publishTimer = null;

    function $(id) { return document.getElementById(id); }

    function api(path, options) {
        return fetch(path, options).then(function (response) {
            return response.json().then(function (body) {
                body.httpStatus = response.status;
                return body;
            });
        });
    }

    // === The way back to the racing app ===

    var SCREENS = { gar: ['../gar', 'GAR'], map: ['../map', 'Map'],
                    race: ['../', 'Race'], hud: ['../hud', 'HUD'] };

    function setUpBack() {
        // Only inside the racing app's /race/ scope: at /events/log/ or on the
        // recorder's own port these relative links would land somewhere else
        if (location.pathname.indexOf('/race/log/') === -1) return;
        var screen = SCREENS[params.get('from')] || SCREENS.gar;
        var back = $('back');
        back.href = screen[0];
        back.innerHTML = '&lsaquo; ' + screen[1];
        back.hidden = false;
        // Script navigation as well as the anchor, as the racing app does: iOS 12
        // in a Home Screen app needs it (racing DESIGN 9.8.1)
        back.addEventListener('click', function (e) {
            e.preventDefault();
            location.assign(back.href);
        });
    }

    // === Showing the state ===

    function clock(seconds) {
        var h = Math.floor(seconds / 3600);
        var m = Math.floor((seconds % 3600) / 60);
        return h + ':' + (m < 10 ? '0' : '') + m;
    }

    function locked() {
        var post = state.recording.post_state;
        return post === 'published' || post === 'wp_draft';
    }

    function showHeader() {
        var rec = state.recording;
        var text;
        var live = state.live || {};
        if (rec.status === 'active') {
            text = '<span class="rec">&#9679; REC</span> ' + clock(state.elapsed_seconds) +
                (live.distance_nm ? ' &middot; ' + live.distance_nm.toFixed(1) + ' nm' : '');
        } else if (rec.stage === 'published') {
            text = 'Published';
        } else if (rec.stage === 'publishing') {
            text = 'Publishing';
        } else {
            text = 'Stopped';
        }
        $('state').innerHTML = text;

        var switcher = $('switcher');
        var candidates = state.candidates;
        switcher.hidden = candidates.length < 2;
        if (candidates.length > 1) {
            var html = '';
            for (var i = 0; i < candidates.length; i++) {
                var c = candidates[i];
                var when = (c.start_time || '').slice(11, 16);
                var label = (i + 1) + ' of ' + candidates.length + ': ' +
                    (c.event_key || 'recording').replace(/_/g, ' ') + ' ' + when;
                html += '<option value="' + c.id + '"' + (c.id === rec.id ? ' selected' : '') +
                    '>' + escapeHtml(label) + '</option>';
            }
            switcher.innerHTML = html;
        }
    }

    function escapeHtml(text) {
        var div = document.createElement('div');
        div.textContent = text == null ? '' : String(text);
        return div.innerHTML;
    }

    function showFields(first) {
        var draft = state.draft;
        var revisions = draft.field_revisions || {};
        for (var i = 0; i < TEXT_FIELDS.length; i++) {
            var field = TEXT_FIELDS[i];
            var input = $(field);
            // Time and wind: the crew's where they typed one, else the recording's
            var theirs = draft[field] || computedValue(field);
            var revision = revisions[field] || 0;
            if (first) {
                input.value = theirs;
                known[field] = revision;
            } else if (revision > (known[field] || 0)) {
                if (theirs !== input.value) overtaken(field, input, theirs);
                known[field] = revision;
            } else if (isComputed(field) && !draft[field] && !dirty[field] &&
                       document.activeElement !== input) {
                // Still the recording's, which moves on while it records
                input.value = theirs;
            }
            input.disabled = locked();
            showSource(field);
        }
        showCrew();
        showCategories();
        showPhotos();
        showNotes();
        showTrack();
        $('capture').hidden = locked();
    }

    // Another device saved this field after this one did. Its text stands, as the later
    // save; what was here is offered back rather than silently dropped.
    function overtaken(field, input, theirs) {
        var other = document.querySelector('[data-other="' + field + '"]');
        if (dirty[field] || document.activeElement === input) {
            // Mid-edit here: this page's save will be the later one, so say what the
            // other device wrote, and let this edit carry on
            other.innerHTML = 'Changed on another device to: <em>' + escapeHtml(theirs) +
                '</em><br><button type="button" class="link">Use that instead</button>';
            other.querySelector('button').onclick = function () {
                input.value = theirs;
                other.innerHTML = '';
                dirty[field] = false;
                clearTimeout(timers[field]);
            };
            return;
        }
        var mine = input.value;
        input.value = theirs;
        if (!mine) return;
        other.innerHTML = 'Changed on another device. This page had: <em>' + escapeHtml(mine) +
            '</em><br><button type="button" class="link">Put that back</button>';
        other.querySelector('button').onclick = function () {
            input.value = mine;
            other.innerHTML = '';
            save(field);
        };
    }

    function showCrew() {
        var crew = state.draft.crew || [];
        var html = '';
        for (var i = 0; i < crew.length; i++) {
            html += '<button type="button" class="chip" data-name="' + escapeHtml(crew[i]) + '"' +
                (locked() ? ' disabled' : '') + '>' + escapeHtml(crew[i]) +
                '<span class="x" aria-label="remove">&times;</span></button>';
        }
        $('crew').innerHTML = html;
        $('crew-add').disabled = locked();

        var names = '';
        var suggestions = state.crew_suggestions || [];
        for (var j = 0; j < suggestions.length; j++) {
            if (crew.indexOf(suggestions[j]) === -1) {
                names += '<option value="' + escapeHtml(suggestions[j]) + '">';
            }
        }
        $('crew-names').innerHTML = names;
    }

    function showCategories() {
        var chosen = state.draft.categories || [];
        var all = state.categories_available.slice();
        for (var i = 0; i < chosen.length; i++) {
            if (all.indexOf(chosen[i]) === -1) all.push(chosen[i]);
        }
        var html = '';
        for (var j = 0; j < all.length; j++) {
            html += '<button type="button" class="chip" aria-pressed="' +
                (chosen.indexOf(all[j]) !== -1) + '" data-category="' + escapeHtml(all[j]) + '"' +
                (locked() ? ' disabled' : '') + '>' + escapeHtml(all[j]) + '</button>';
        }
        $('categories').innerHTML = html;
    }

    function showPhotos() {
        var photos = state.photos || [];
        var html = '';
        for (var i = 0; i < photos.length; i++) {
            html += '<figure data-image="' + photos[i].image_id + '"><img src="' +
                escapeHtml(photos[i].thumb_url) + '" alt="">' +
                (photos[i].caption ? '<span class="caption">' + escapeHtml(photos[i].caption) +
                 '</span>' : '') + '</figure>';
        }
        $('photos').innerHTML = html || '<span class="hint">None yet</span>';
    }

    // FR-31: the track so far, drawn flat. At the boat's latitude a degree of
    // longitude is shorter than one of latitude, so it is scaled by cos(latitude)
    // or the river comes out half again as wide as it is.
    function showTrack() {
        var live = state.live || {};
        var track = live.track || [];
        $('track-field').hidden = track.length < 2;
        if (track.length < 2) return;

        var numbers = [live.distance_nm.toFixed(1) + ' nm'];
        if (live.max_sog != null) numbers.push('top ' + live.max_sog.toFixed(1) + ' kt');
        $('track-numbers').textContent = numbers.join(' · ');

        var south = 90, north = -90, west = 180, east = -180;
        for (var i = 0; i < track.length; i++) {
            south = Math.min(south, track[i][0]); north = Math.max(north, track[i][0]);
            west = Math.min(west, track[i][1]); east = Math.max(east, track[i][1]);
        }
        var squeeze = Math.cos((north + south) / 2 * Math.PI / 180);
        var width = Math.max((east - west) * squeeze, 1e-6);
        var height = Math.max(north - south, 1e-6);
        var pad = 12, boxW = 400 - 2 * pad, boxH = 220 - 2 * pad;
        var scale = Math.min(boxW / width, boxH / height);
        var offX = pad + (boxW - width * scale) / 2, offY = pad + (boxH - height * scale) / 2;

        function x(p) { return (offX + (p[1] - west) * squeeze * scale).toFixed(1); }
        function y(p) { return (offY + (north - p[0]) * scale).toFixed(1); }

        // Built with createElementNS rather than innerHTML, which older Safari does
        // not honour on SVG elements
        var svg = $('track');
        while (svg.firstChild) svg.removeChild(svg.firstChild);
        function shape(name, attrs) {
            var el = document.createElementNS('http://www.w3.org/2000/svg', name);
            for (var key in attrs) el.setAttribute(key, attrs[key]);
            svg.appendChild(el);
        }
        var first = track[0], last = track[track.length - 1];
        shape('polyline', { 'class': 'line',
                            points: track.map(function (p) { return x(p) + ',' + y(p); }).join(' ') });
        shape('circle', { 'class': 'start', r: 5, cx: x(first), cy: y(first) });
        shape('circle', { 'class': 'now', r: 6, cx: x(last), cy: y(last) });
    }

    function noteTime(ts) {
        var d = new Date(ts);
        if (isNaN(d.getTime())) return '';
        var m = d.getMinutes();
        return d.getHours() + ':' + (m < 10 ? '0' : '') + m;
    }

    function showNotes() {
        // Not while one is being edited here: the poll would replace the text under
        // the crew's fingers
        if ($('notes').contains(document.activeElement)) return;
        var notes = state.draft.notes || [];
        var html = '';
        for (var i = 0; i < notes.length; i++) {
            html += '<div class="note" data-index="' + i + '">' +
                '<span class="when">' + noteTime(notes[i].ts) + '</span>' +
                '<input type="text" value="' + escapeHtml(notes[i].text) + '"' +
                (locked() ? ' disabled' : '') + ' aria-label="Note">' +
                (locked() ? '' : '<button type="button" class="link" data-act="story">Move into story</button>' +
                 '<button type="button" class="link" data-act="remove">Remove</button>') +
                '</div>';
        }
        $('notes').innerHTML = html || '<span class="hint">None yet</span>';
    }

    function showActions() {
        var rec = state.recording;
        var job = state.publish_job;
        var publish = $('publish');
        var why = '';
        var running = job && job.state === 'running';

        if (running) {
            why = job.step + (job.total ? ' (' + job.done + ' of ' + job.total + ')' : '');
        } else if (rec.status === 'active') {
            why = 'Publish when the recording has stopped.';
        } else if (locked()) {
            why = 'Published. Change it in WordPress now.';
        } else if (job && job.state === 'failed') {
            why = 'Publishing failed: ' + job.error;
        } else if (rec.post_error) {
            why = rec.post_error;
        }
        publish.disabled = !state.can_publish || running;
        $('publish-draft').disabled = publish.disabled;
        $('publish-why').textContent = why;
        $('locked').hidden = !locked();
        $('locked').textContent = locked()
            ? 'This post is on enchantee.org now, so it is changed there rather than here.' : '';
        $('preview').href = 'preview?id=' + rec.id;

        var link = rec.wordpress_url;
        $('post').innerHTML = link
            ? 'Post: <a href="' + escapeHtml(link) + '">' + escapeHtml(link) + '</a>' : '';

        clearTimeout(publishTimer);
        if (running) publishTimer = setTimeout(refresh, PUBLISH_POLL_MS);
    }

    function show(first) {
        $('empty').hidden = true;
        $('page').hidden = false;
        showHeader();
        showFields(first);
        showActions();
    }

    // === Loading ===

    function load(first) {
        var query = recordingId ? '?id=' + recordingId : '';
        return api('api/state' + query).then(function (body) {
            if (!body.success) {
                $('state').textContent = body.error || 'Could not load';
                return;
            }
            if (!body.recording) {
                $('page').hidden = true;
                $('empty').hidden = false;
                $('state').textContent = 'No recording';
                return;
            }
            var changed = !state || state.recording.id !== body.recording.id;
            state = body;
            if (!recordingId || changed) {
                // Stay on this recording from now on, and keep it on a reload, rather
                // than letting FR-28's choice move under the crew as recordings start
                recordingId = body.recording.id;
                params.set('id', recordingId);
                history.replaceState(null, '', '?' + params.toString());
            }
            show(first || changed);
        }).catch(function () {
            $('state').textContent = 'Offline: retrying';
        });
    }

    function refresh() { return load(false); }

    // === Saving ===

    function mark(field, text, isError) {
        var el = document.querySelector('[data-saved="' + field + '"]');
        if (!el) return;
        el.textContent = text;
        el.className = 'saved' + (isError ? ' error' : '');
    }

    function save(field, value) {
        if (value === undefined) value = $(field).value;
        // The recording's own value, or nothing, saves as no text of the crew's,
        // so the line goes on following the data (FR-26)
        if (isComputed(field) && (!value.trim() || value.trim() === computedValue(field))) {
            value = '';
        }
        clearTimeout(timers[field]);
        var changes = {};
        changes[field] = value;
        mark(field, 'Saving…');
        return api('api/draft/' + recordingId, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ changes: changes })
        }).then(function (body) {
            if (!body.success) {
                mark(field, body.error || 'Not saved', true);
                return;
            }
            dirty[field] = false;
            state.draft = body.draft;
            known[field] = (body.draft.field_revisions || {})[field] || 0;
            mark(field, 'Saved');
            if (isComputed(field)) {
                if (!value) $(field).value = computedValue(field);
                showSource(field);
            }
            var other = document.querySelector('[data-other="' + field + '"]');
            if (other) other.innerHTML = '';
        }).catch(function () {
            // Kept dirty, so leaving the field or the next keystroke tries again
            mark(field, 'Not saved: no connection', true);
        });
    }

    // Fields whose starting text is the recorder's guess ("anchor_track_recording -
    // 2026-10-09 ..."), there to be replaced rather than edited
    var REPLACEABLE = ['title', 'excerpt'];

    // Still the recorder's text: nobody has saved this field, so it has no revision
    function untouched(field) {
        var revisions = (state && state.draft.field_revisions) || {};
        return !revisions[field] && !dirty[field];
    }

    function selectAllOnFocus(field) {
        var input = $(field);
        var selecting = false;
        input.addEventListener('focus', function () {
            if (!untouched(field) || !input.value) return;
            selecting = true;
            // After the focus has settled: iOS Safari places the caret itself once
            // focus completes, undoing a select() made in this handler
            setTimeout(function () {
                if (document.activeElement === input) input.setSelectionRange(0, input.value.length);
            }, 0);
        });
        // The tap that focused the field ends in a mouseup that would put the caret
        // where the finger was, over the selection just made. Only that one is stopped.
        input.addEventListener('mouseup', function (e) {
            if (selecting) {
                e.preventDefault();
                selecting = false;
            }
        });
        input.addEventListener('blur', function () { selecting = false; });
    }

    function bindTextFields() {
        REPLACEABLE.forEach(selectAllOnFocus);
        // Back to the recording's line (FR-26)
        Object.keys(COMPUTED).forEach(function (field) {
            document.querySelector('[data-reset="' + field + '"]')
                .addEventListener('click', function () { save(field, ''); });
        });
        TEXT_FIELDS.forEach(function (field) {
            var input = $(field);
            input.addEventListener('input', function () {
                dirty[field] = true;
                mark(field, '');
                clearTimeout(timers[field]);
                timers[field] = setTimeout(function () { save(field); }, SAVE_AFTER_MS);
            });
            input.addEventListener('blur', function () {
                if (dirty[field]) save(field);
            });
        });
    }

    function bindCrew() {
        var add = $('crew-add');
        function addName() {
            var name = add.value.replace(/,/g, ' ').trim();
            if (!name) return;
            var crew = (state.draft.crew || []).slice();
            if (crew.indexOf(name) === -1) crew.push(name);
            add.value = '';
            state.draft.crew = crew;
            showCrew();
            save('crew', crew);
        }
        add.addEventListener('keydown', function (e) {
            if (e.key === 'Enter' || e.key === ',') {
                e.preventDefault();
                addName();
            }
        });
        // Choosing a suggestion from the list fills the field without a key press
        add.addEventListener('change', addName);

        $('crew').addEventListener('click', function (e) {
            var chip = e.target.closest ? e.target.closest('.chip') : null;
            if (!chip || chip.disabled) return;
            var crew = (state.draft.crew || []).filter(function (n) {
                return n !== chip.getAttribute('data-name');
            });
            state.draft.crew = crew;
            showCrew();
            save('crew', crew);
        });
    }

    function bindCategories() {
        $('categories').addEventListener('click', function (e) {
            var chip = e.target.closest ? e.target.closest('.chip') : null;
            if (!chip || chip.disabled) return;
            var name = chip.getAttribute('data-category');
            var chosen = (state.draft.categories || []).slice();
            var at = chosen.indexOf(name);
            if (at === -1) chosen.push(name); else chosen.splice(at, 1);
            state.draft.categories = chosen;
            showCategories();
            save('categories', chosen);
        });
    }

    // === Photos and notes (FR-29) ===

    function status(text) { $('capture-status').textContent = text; }

    function bindPhotos() {
        var input = $('photo-input');
        input.addEventListener('change', function () {
            var files = Array.prototype.slice.call(input.files || []);
            var done = 0;
            function next() {
                if (done === files.length) {
                    input.value = '';
                    status(files.length ? 'Photo added' + (files.length > 1 ? 's' : '') : '');
                    refresh();
                    return;
                }
                status('Uploading ' + (files.length > 1 ? (done + 1) + ' of ' + files.length : 'photo') + '…');
                var form = new FormData();
                form.append('file', files[done]);
                api('api/photos/' + recordingId, { method: 'POST', body: form }).then(function (body) {
                    if (!body.success) {
                        status('Not added: ' + body.error);
                        input.value = '';
                        return;
                    }
                    done += 1;
                    next();
                }).catch(function () {
                    status('Not added: no connection');
                    input.value = '';
                });
            }
            next();
        });

        var editing = null;
        $('photos').addEventListener('click', function (e) {
            var figure = e.target.closest ? e.target.closest('figure') : null;
            if (!figure || locked()) return;
            var id = parseInt(figure.getAttribute('data-image'), 10);
            editing = null;
            for (var i = 0; i < state.photos.length; i++) {
                if (state.photos[i].image_id === id) editing = state.photos[i];
            }
            if (!editing) return;
            $('photo-edit-img').src = editing.url;
            $('photo-caption').value = editing.caption;
            $('photo-edit').hidden = false;
        });
        $('photo-close').addEventListener('click', function () { $('photo-edit').hidden = true; });
        $('photo-caption-save').addEventListener('click', function () {
            if (!editing) return;
            api('api/photos/' + recordingId + '/' + editing.image_id, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ caption: $('photo-caption').value })
            }).then(function (body) {
                mark('photos', body.success ? 'Saved' : body.error, !body.success);
                refresh();
            });
        });
        $('photo-remove').addEventListener('click', function () {
            if (!editing) return;
            api('api/photos/' + recordingId + '/' + editing.image_id, { method: 'DELETE' })
                .then(function (body) {
                    mark('photos', body.success ? 'Removed' : body.error, !body.success);
                    $('photo-edit').hidden = true;
                    refresh();
                });
        });
    }

    function bindNotes() {
        var openedAt = null;
        var entry = $('note-entry');
        var text = $('note-text');

        $('note-button').addEventListener('click', function () {
            // The moment the note is about is now, when it was thought of, not when
            // the typing is finished
            openedAt = new Date();
            $('note-at').textContent = 'at ' + noteTime(openedAt.toISOString());
            entry.hidden = false;
            text.focus();
        });
        function close() {
            entry.hidden = true;
            text.value = '';
            openedAt = null;
        }
        function add() {
            if (!text.value.trim()) return close();
            $('note-save').disabled = true;
            api('api/notes/' + recordingId, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ text: text.value, ts: openedAt.toISOString() })
            }).then(function (body) {
                $('note-save').disabled = false;
                if (!body.success) {
                    status('Not added: ' + body.error);
                    return;
                }
                close();
                status('Note added');
                refresh();
            }).catch(function () {
                $('note-save').disabled = false;
                status('Not added: no connection. The note is still there to try again.');
            });
        }
        $('note-save').addEventListener('click', add);
        $('note-cancel').addEventListener('click', close);
        text.addEventListener('keydown', function (e) {
            if (e.key === 'Enter') {
                e.preventDefault();
                add();
            }
        });

        // Changing, removing or moving a note saves the notes field as a whole
        function saveNotes(notes) {
            state.draft.notes = notes;
            return save('notes', notes);
        }
        $('notes').addEventListener('change', function (e) {
            var row = e.target.closest ? e.target.closest('.note') : null;
            if (!row) return;
            var notes = (state.draft.notes || []).slice();
            var i = parseInt(row.getAttribute('data-index'), 10);
            notes[i] = Object.assign({}, notes[i], { text: e.target.value });
            saveNotes(notes);
        });
        $('notes').addEventListener('click', function (e) {
            var act = e.target.getAttribute('data-act');
            var row = e.target.closest ? e.target.closest('.note') : null;
            if (!act || !row) return;
            var notes = (state.draft.notes || []).slice();
            var i = parseInt(row.getAttribute('data-index'), 10);
            var note = notes.splice(i, 1)[0];
            if (act === 'story') {
                var story = $('story');
                story.value = story.value.replace(/\s+$/, '') + (story.value.trim() ? '\n\n' : '') + note.text;
                save('story');
            }
            saveNotes(notes).then(function () { showNotes(); });
        });
    }

    // === Publishing ===

    function startPublish(asDraft) {
        // Anything still waiting to save goes first, so the post has it
        var pending = TEXT_FIELDS.filter(function (f) { return dirty[f]; }).map(function (f) {
            return save(f);
        });
        $('publish').disabled = true;
        Promise.all(pending).then(function () {
            return api('api/publish/' + recordingId, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ draft: !!asDraft })
            });
        }).then(function (body) {
            if (!body.success) $('publish-why').textContent = body.error;
            refresh();
        });
    }

    function bindPublish() {
        $('publish').addEventListener('click', function () { startPublish(false); });
        $('publish-draft').addEventListener('click', function () { startPublish(true); });
    }

    function bindSwitcher() {
        $('switcher').addEventListener('change', function () {
            recordingId = parseInt(this.value, 10);
            known = {};
            dirty = {};
            load(true);
        });
    }

    setUpBack();
    bindTextFields();
    bindCrew();
    bindCategories();
    bindPhotos();
    bindNotes();
    bindPublish();
    bindSwitcher();
    load(true);
    setInterval(refresh, POLL_MS);
}());
