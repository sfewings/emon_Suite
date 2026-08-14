<?php
/**
 * Plugin Name: Allow Geo File Uploads
 * Description: Adds KML and GPX to WordPress allowed upload MIME types.
 * Version: 1.0
 */

// Add KML and GPX to the allowed MIME types list
add_filter('upload_mimes', function ($mimes) {
    $mimes['kml']  = 'application/vnd.google-earth.kml+xml';
    $mimes['gpx']  = 'application/gpx+xml';
    return $mimes;
});

// Override WordPress's file type verification for KML and GPX.
// WordPress uses finfo/mime_content_type which returns generic types for these
// formats, so we must explicitly declare the correct ext/type to prevent the
// "Sorry, this file type is not permitted" error.
add_filter('wp_check_filetype_and_ext', function ($data, $file, $filename, $mimes, $real_mime) {
    $ext = strtolower(pathinfo($filename, PATHINFO_EXTENSION));
    if ($ext === 'kml') {
        $data['ext']  = 'kml';
        $data['type'] = 'application/vnd.google-earth.kml+xml';
    } elseif ($ext === 'gpx') {
        $data['ext']  = 'gpx';
        $data['type'] = 'application/gpx+xml';
    }
    return $data;
}, 10, 5);
