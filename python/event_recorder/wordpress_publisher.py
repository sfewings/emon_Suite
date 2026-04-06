"""
WordPress Publisher - REST API Integration
Handles authentication, media upload, and post creation
"""

import html as html_module
import logging
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests
from requests.auth import HTTPBasicAuth

logger = logging.getLogger(__name__)


class WordPressPublisher:
    """
    WordPress REST API client for publishing blog posts.

    Uses Application Passwords for authentication (WordPress 5.6+).
    """

    def __init__(
        self,
        site_url: str,
        username: str,
        app_password: str,
        whitelist_endpoint: str = None,
        timeout: int = 30,
        max_retries: int = 3
    ):
        """
        Initialize WordPress publisher.

        Args:
            site_url: WordPress site URL (e.g., https://example.com)
            username: WordPress username
            app_password: Application password (24-char with spaces)
            whitelist_endpoint: Optional URL to call before first API request.
                This allows the server to whitelist the calling IP.
                (e.g., https://example.com/whitelist.php?token=xyz)
            timeout: Request timeout in seconds
            max_retries: Maximum retry attempts for failed requests
        """
        self.site_url = site_url.rstrip('/')
        self.username = username
        self.auth = HTTPBasicAuth(username, app_password)
        self.whitelist_endpoint = whitelist_endpoint
        self._whitelist_called = False  # Track whether we've called the whitelist endpoint
        self.timeout = timeout
        self.max_retries = max_retries

        logger.info(f"WordPressPublisher initialized for {self.site_url}, {self.username}, {app_password})")
        if self.whitelist_endpoint:
            logger.info(f"Whitelist endpoint configured: {self.whitelist_endpoint}")
        else:
            logger.info(f"No whitelist endpoint")

    def _api_url(self, endpoint: str) -> str:
        """
        Build REST API URL using ?rest_route= query parameter format.

        This is universally compatible with all WordPress installations,
        regardless of permalink settings.

        Args:
            endpoint: API endpoint path (e.g., 'users/me', 'posts', 'media/123')

        Returns:
            Full URL string
        """
        return f"{self.site_url}/?rest_route=/wp/v2/{endpoint}"

    def _call_whitelist_endpoint(self) -> bool:
        """
        Call whitelist endpoint to register calling IP before API access.

        Returns:
            True if successful or endpoint not configured, False if failed
        """
        if not self.whitelist_endpoint or self._whitelist_called:
            return True

        try:
            logger.info(f"Calling whitelist endpoint: {self.whitelist_endpoint}")
            response = requests.get(
                self.whitelist_endpoint,
                timeout=self.timeout
            )

            if response.status_code == 200:
                logger.info("Whitelist endpoint called successfully")
                self._whitelist_called = True
                return True
            else:
                logger.error(
                    f"Whitelist endpoint returned {response.status_code}: {response.text}"
                )
                return False

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to call whitelist endpoint: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error calling whitelist endpoint: {e}")
            return False

    def test_connection(self) -> Tuple[bool, str]:
        """
        Test WordPress API connection and authentication.

        Returns:
            Tuple of (success: bool, message: str)
        """
        # Call whitelist endpoint first if configured
        if self.whitelist_endpoint and not self._whitelist_called:
            if not self._call_whitelist_endpoint():
                return False, "Whitelist endpoint call failed"

        try:
            # Test basic API access using WP Application Password credentials
            response = requests.get(
                self._api_url('users/me'),
                auth=self.auth,
                timeout=self.timeout
            )

            if response.status_code == 200:
                user_data = response.json()
                logger.info(f"WordPress connection successful: {user_data.get('name')}")
                return True, f"Connected as {user_data.get('name')} ({user_data.get('roles')})"
            elif response.status_code == 401:
                logger.error("WordPress authentication failed")
                return False, "Authentication failed - check username and app password"
            else:
                logger.error(f"WordPress API error: {response.status_code}")
                return False, f"API error: {response.status_code} - {response.text}"

        except requests.exceptions.ConnectionError:
            logger.error(f"Cannot connect to {self.site_url}")
            return False, f"Connection failed - cannot reach {self.site_url}"
        except requests.exceptions.Timeout:
            logger.error("WordPress API request timed out")
            return False, "Request timed out"
        except Exception as e:
            logger.error(f"WordPress connection test failed: {e}")
            return False, f"Connection test failed: {str(e)}"

    def _retry_request(self, method: str, url: str, **kwargs) -> requests.Response:
        """
        Execute HTTP request with exponential backoff retry.

        Args:
            method: HTTP method (GET, POST, etc.)
            url: Request URL
            **kwargs: Additional arguments for requests

        Returns:
            Response object

        Raises:
            requests.exceptions.RequestException: If all retries fail
        """
        # Call whitelist endpoint before first request if configured
        if not self._whitelist_called:
            if not self._call_whitelist_endpoint():
                logger.error("Whitelist endpoint call failed, aborting request")
                raise requests.exceptions.RequestException(
                    "Whitelist endpoint call failed"
                )

        for attempt in range(self.max_retries):
            try:
                # Send request with WP Application Password (required by WordPress REST API)
                response = requests.request(
                    method,
                    url,
                    auth=self.auth,
                    timeout=self.timeout,
                    **kwargs
                )

                # Check for success or client error (don't retry client errors)
                if response.status_code < 500:
                    return response

                # Server error - retry with backoff
                logger.warning(f"Server error {response.status_code}, attempt {attempt + 1}/{self.max_retries}")

            except requests.exceptions.RequestException as e:
                logger.warning(f"Request failed: {e}, attempt {attempt + 1}/{self.max_retries}")

                if attempt == self.max_retries - 1:
                    raise

            # Exponential backoff: 1s, 2s, 4s
            if attempt < self.max_retries - 1:
                time.sleep(2 ** attempt)

        return response

    def upload_media(self, file_path: str, caption: str = None) -> Optional[Dict]:
        """
        Upload image to WordPress media library.

        Args:
            file_path: Path to image file
            caption: Optional image caption

        Returns:
            Dict with 'id' and 'url' if successful, None otherwise
        """
        file_path = Path(file_path)

        if not file_path.exists():
            logger.error(f"Image file not found: {file_path}")
            return None

        try:
            # Read file
            with open(file_path, 'rb') as f:
                file_data = f.read()

            # Prepare headers
            headers = {
                'Content-Disposition': f'attachment; filename="{file_path.name}"',
                'Content-Type': self._get_mime_type(file_path)
            }

            # Upload
            logger.info(f"Uploading media: {file_path.name}")
            response = self._retry_request(
                'POST',
                self._api_url('media'),
                headers=headers,
                data=file_data
            )

            if response.status_code == 201:
                media_data = response.json()
                media_id = media_data['id']
                media_url = media_data.get('source_url', media_data.get('link', ''))

                # Update caption if provided
                if caption:
                    self._update_media_caption(media_id, caption)

                logger.info(f"Media uploaded successfully: ID={media_id}")
                return {'id': media_id, 'url': media_url}
            else:
                logger.error(f"Media upload failed: {response.status_code} - {response.text}")
                return None

        except Exception as e:
            logger.error(f"Failed to upload media {file_path}: {e}")
            return None

    def _update_media_caption(self, media_id: int, caption: str):
        """Update media item caption."""
        try:
            response = self._retry_request(
                'POST',
                self._api_url(f'media/{media_id}'),
                json={'caption': caption}
            )
            if response.status_code == 200:
                logger.debug(f"Caption updated for media {media_id}")
        except Exception as e:
            logger.warning(f"Failed to update caption for media {media_id}: {e}")

    def _get_mime_type(self, file_path: Path) -> str:
        """Get MIME type for image or export file."""
        ext = file_path.suffix.lower()
        mime_types = {
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.gif': 'image/gif',
            '.webp': 'image/webp',
            '.csv': 'text/csv',
            '.kml': 'application/vnd.google-earth.kml+xml',
            '.gpx': 'application/gpx+xml',
        }
        return mime_types.get(ext, 'application/octet-stream')

    def upload_export_file(self, file_path: str, label: str = None) -> Optional[Dict]:
        """
        Upload an export file (CSV, KML, GPX) to the WordPress media library.

        Args:
            file_path: Path to the export file
            label: Optional description for the media item

        Returns:
            Dict with 'id' and 'url' if successful, None otherwise
        """
        file_path = Path(file_path)
        if not file_path.exists():
            logger.error(f"Export file not found: {file_path}")
            return None

        try:
            with open(file_path, 'rb') as f:
                file_data = f.read()

            headers = {
                'Content-Disposition': f'attachment; filename="{file_path.name}"',
                'Content-Type': self._get_mime_type(file_path),
            }

            logger.info(f"Uploading export file: {file_path.name}")
            response = self._retry_request('POST', self._api_url('media'),
                                            headers=headers, data=file_data)

            if response.status_code == 201:
                media_data = response.json()
                media_id = media_data['id']
                media_url = media_data.get('source_url', media_data.get('link', ''))
                if label:
                    self._update_media_caption(media_id, label)
                logger.info(f"Export file uploaded: ID={media_id}")
                return {'id': media_id, 'url': media_url}
            else:
                logger.error(f"Export upload failed: {response.status_code} - {response.text}")
                return None

        except Exception as e:
            logger.error(f"Failed to upload export {file_path}: {e}")
            return None

    def get_category_id(self, category_name: str, create: bool = True) -> Optional[int]:
        """
        Get WordPress category ID by name.

        Args:
            category_name: Category name
            create: Create category if it doesn't exist

        Returns:
            Category ID if found/created, None otherwise
        """
        try:
            # Search for existing category
            response = self._retry_request(
                'GET',
                self._api_url('categories'),
                params={'search': category_name}
            )

            if response.status_code == 200:
                categories = response.json()

                # Check for exact match
                for category in categories:
                    if category['name'].lower() == category_name.lower():
                        logger.debug(f"Found category '{category_name}': ID={category['id']}")
                        return category['id']

                # Create if not found
                if create:
                    logger.info(f"Creating category: {category_name}")
                    create_response = self._retry_request(
                        'POST',
                        self._api_url('categories'),
                        json={'name': category_name}
                    )

                    if create_response.status_code == 201:
                        new_category = create_response.json()
                        logger.info(f"Category created: ID={new_category['id']}")
                        return new_category['id']

            logger.warning(f"Category '{category_name}' not found")
            return None

        except Exception as e:
            logger.error(f"Failed to get category ID: {e}")
            return None

    def create_post(
        self,
        title: str,
        content: str,
        status: str = 'draft',
        categories: List[str] = None,
        featured_media: int = None,
        excerpt: str = None,
        date: str = None
    ) -> Optional[Dict]:
        """
        Create WordPress blog post.

        Args:
            title: Post title
            content: Post content (HTML)
            status: Post status (draft, publish, pending)
            categories: List of category names
            featured_media: Featured image media ID
            excerpt: Post excerpt
            date: Publication date in ISO 8601 format (YYYY-MM-DDTHH:MM:SS);
                  WordPress treats this as the site's local timezone

        Returns:
            Post data dict if successful, None otherwise
        """
        try:
            # Build post data
            post_data = {
                'title': title,
                'content': content,
                'status': status,
            }

            # Add excerpt
            if excerpt:
                post_data['excerpt'] = excerpt

            # Add publication date (sets both displayed date and sort order)
            if date:
                post_data['date'] = date

            # Add categories
            if categories:
                category_ids = []
                for cat_name in categories:
                    cat_id = self.get_category_id(cat_name, create=True)
                    if cat_id:
                        category_ids.append(cat_id)

                if category_ids:
                    post_data['categories'] = category_ids

            # Add featured image
            if featured_media:
                post_data['featured_media'] = featured_media

            # Create post
            logger.info(f"Creating post: {title}")
            response = self._retry_request(
                'POST',
                self._api_url('posts'),
                json=post_data
            )

            if response.status_code == 201:
                post = response.json()
                logger.info(f"Post created successfully: {post['link']}")
                return {
                    'id': post['id'],
                    'title': post['title']['rendered'],
                    'link': post['link'],
                    'status': post['status'],
                    'date': post['date']
                }
            else:
                logger.error(f"Post creation failed: {response.status_code} - {response.text}")
                return None

        except Exception as e:
            logger.error(f"Failed to create post: {e}")
            return None

    def publish_recording(
        self,
        recording_data: Dict,
        images: List[Dict],
        exports: List[Dict] = None,
        statistics: Dict = None,
        map_htmls: List[str] = None,
        template: str = None,
        category: str = "Track Logs",
        auto_publish: bool = False
    ) -> Optional[Dict]:
        """
        Publish recording as WordPress blog post.

        Args:
            recording_data: Recording metadata dict
            images: List of image dicts with 'path' and 'caption'
            exports: List of export file dicts
            statistics: Optional statistics dict from statistics_summary.json
            map_htmls: Optional list of folium HTML file paths to embed as interactive maps
            template: HTML template string (with {placeholders})
            category: WordPress category name
            auto_publish: Publish immediately (vs draft)

        Returns:
            Dict with post info if successful, None otherwise
        """
        logger.info(f"Publishing recording: {recording_data.get('name')}")

        try:
            # Upload images to WordPress
            media_ids = []
            for image in images:
                media_result = self.upload_media(
                    image['path'],
                    caption=image.get('caption', '')
                )
                if media_result:
                    media_ids.append({
                        'id': media_result['id'],
                        'url': media_result['url'],
                        'caption': image.get('caption', ''),
                        'image_type': image.get('image_type', 'plot'),
                        'path': image['path']
                    })

            if not media_ids and not statistics and not map_htmls:
                logger.error("No images uploaded successfully")
                return None

            # Upload export files and collect download links
            download_links = []
            for exp in (exports or []):
                result = self.upload_export_file(exp['path'], label=exp.get('label', ''))
                if result:
                    download_links.append({
                        'url': result['url'],
                        'label': exp.get('label', exp['export_type'].upper()),
                        'export_type': exp['export_type'],
                    })

            # Build HTML content
            content = self._build_post_content(
                recording_data,
                media_ids,
                template,
                download_links=download_links,
                statistics=statistics,
                map_htmls=map_htmls
            )

            # Extract title
            title = recording_data.get('name', f"Track Log - {datetime.now().strftime('%Y-%m-%d')}")

            # Create excerpt
            excerpt = recording_data.get('description', '')
            if not excerpt:
                start_time = recording_data.get('start_time', '')
                duration = self._format_duration(
                    recording_data.get('start_time'),
                    recording_data.get('end_time')
                )
                excerpt = f"Track recording from {start_time}. Duration: {duration}"

            # Featured image priority:
            #   1. Last user-uploaded photo (most recent/relevant shot of the trip)
            #   2. First generated plot (route map, speed chart, etc.)
            #   3. Any uploaded image
            user_uploads = [m for m in media_ids if m.get('image_type') == 'user_upload']
            plots_for_featured = [m for m in media_ids if m.get('image_type', 'plot') == 'plot']
            if user_uploads:
                featured_id = user_uploads[-1]['id']
            elif plots_for_featured:
                featured_id = plots_for_featured[0]['id']
            elif media_ids:
                featured_id = media_ids[0]['id']
            else:
                featured_id = None

            # Format recording start time as ISO 8601 for WordPress date field
            post_date = None
            raw_start = recording_data.get('start_time')
            if raw_start:
                try:
                    from dateutil import parser as _dateutil_parser
                    post_date = _dateutil_parser.parse(str(raw_start)).strftime('%Y-%m-%dT%H:%M:%S')
                except Exception:
                    pass  # Leave post_date as None; WordPress will use current time

            # Create post
            post_status = 'publish' if auto_publish else 'draft'
            post = self.create_post(
                title=title,
                content=content,
                status=post_status,
                categories=[category],
                featured_media=featured_id,
                excerpt=excerpt,
                date=post_date
            )

            return post

        except Exception as e:
            logger.error(f"Failed to publish recording: {e}")
            return None

    def _build_post_content(
        self,
        recording_data: Dict,
        media_ids: List[Dict],
        template: str = None,
        download_links: List[Dict] = None,
        statistics: Dict = None,
        map_htmls: List[str] = None
    ) -> str:
        """
        Build HTML content for post.

        Args:
            recording_data: Recording metadata
            media_ids: List of uploaded media dicts
            template: Optional HTML template
            download_links: List of download link dicts
            statistics: Optional statistics dict; rendered as an HTML table
            map_htmls: Optional list of folium HTML paths; embedded as interactive maps

        Returns:
            HTML content string
        """
        if template:
            # Use custom template with placeholder substitution
            content = self._apply_template(recording_data, template)
        else:
            # Default template
            content = f"<h2>Track Summary</h2>\n"
            content += f"<p><strong>Date:</strong> {recording_data.get('start_time', 'N/A')}</p>\n"

            duration = self._format_duration(
                recording_data.get('start_time'),
                recording_data.get('end_time')
            )
            content += f"<p><strong>Duration:</strong> {duration}</p>\n"

            if recording_data.get('description'):
                content += f"<p>{recording_data['description']}</p>\n"

        # Statistics table (HTML, not image)
        if statistics:
            content += self._build_statistics_table_html(statistics)

        # Interactive route map(s) — embedded folium HTML
        # Wrapped in Gutenberg <!-- wp:html --> blocks so WordPress does NOT
        # run wpautop() on the content (wpautop mangles <script> tags by
        # wrapping them in <p> tags and inserting <br /> between them).
        if map_htmls:
            label = "Route Maps" if len(map_htmls) > 1 else "Route Map"
            content += f"\n<h2>{label}</h2>\n"
            for html_path in map_htmls:
                embed = self._extract_folium_embed(html_path)
                if embed:
                    content += '<!-- wp:html -->\n' + embed + '\n<!-- /wp:html -->\n\n'

        # Split images: user-uploaded photos go in their own section before plots
        user_photos = [m for m in media_ids if m.get('image_type') == 'user_upload']
        plots = [m for m in media_ids if m.get('image_type', 'plot') == 'plot']

        # Photos section — user uploads with by-line captions
        if user_photos:
            content += "\n<h2>Photos</h2>\n"
            for media in user_photos:
                caption = media.get('caption', '')
                img_url = media.get('url', '')
                alt_text = html_module.escape(caption) if caption else 'Photo'
                content += f'<figure class="wp-block-image">\n'
                content += f'  <img src="{img_url}" alt="{alt_text}" />\n'
                if caption:
                    content += f'  <figcaption><em>{html_module.escape(caption)}</em></figcaption>\n'
                content += f'</figure>\n\n'

        # Data Visualizations section — generated plots
        if plots:
            content += "\n<h2>Data Visualizations</h2>\n"
            for media in plots:
                caption = media.get('caption', '')
                img_url = media.get('url', '')
                content += f'<figure class="wp-block-image">\n'
                content += f'  <img src="{img_url}" alt="{html_module.escape(caption)}" />\n'
                if caption:
                    content += f'  <figcaption>{html_module.escape(caption)}</figcaption>\n'
                content += f'</figure>\n\n'

        # Add Downloads section if export files were uploaded
        if download_links:
            content += "\n<h2>Downloads</h2>\n<ul>\n"
            for link in download_links:
                label = link['label']
                url = link['url']
                ext = link['export_type'].upper()
                content += f'  <li><a href="{url}" download>{label} ({ext})</a></li>\n'
            content += "</ul>\n"

        return content

    def _extract_folium_embed(self, html_path: str, height: int = 500) -> str:
        """
        Extract an embeddable HTML snippet from a folium-generated map file.

        Folium saves a full standalone HTML page.  This method pulls out:
          - CDN <link> stylesheet tags
          - CDN <script src="..."> tags
          - The map <div> with corrected fixed height
          - The Leaflet initialisation <script> (placed after </body> by folium)

        The resulting snippet can be pasted directly into a WordPress post.
        Admin users with the ``unfiltered_html`` capability can save <script>
        tags through the REST API, so the interactive map renders correctly.

        Args:
            html_path: Path to the folium-saved .html file
            height:    Height in pixels for the map container (default 500)

        Returns:
            HTML string ready for embedding, or '' on failure
        """
        try:
            with open(html_path, 'r', encoding='utf-8') as f:
                content = f.read()

            parts = []

            # CDN stylesheets
            for m in re.finditer(
                r'<link\b[^>]*\brel=["\']stylesheet["\'][^>]*>',
                content, re.IGNORECASE
            ):
                parts.append(m.group(0))

            # CDN JS scripts (external src only, not inline)
            seen_srcs = set()
            for m in re.finditer(
                r'<script\b[^>]*\bsrc="([^"]+)"[^>]*>\s*</script>',
                content, re.IGNORECASE
            ):
                src = m.group(1)
                if src not in seen_srcs:
                    seen_srcs.add(src)
                    parts.append(f'<script src="{src}"></script>')

            # Find the map div ID
            id_m = re.search(
                r'<div\b[^>]*\bclass="folium-map"[^>]*\bid="([^"]+)"',
                content, re.IGNORECASE
            )
            if not id_m:
                logger.warning(f"Could not find folium map div in {html_path}")
                return ''
            map_id = id_m.group(1)

            # Map container — fixed pixel height, not 100%
            parts.append(
                f'<style>'
                f'#{map_id}{{position:relative;width:100%;height:{height}px;}}'
                f'.leaflet-container{{font-size:1rem;}}'
                f'</style>'
            )

            # Leaflet initialisation flags (needed by awesome-markers plugin)
            parts.append('<script>L_NO_TOUCH=false;L_DISABLE_3D=false;</script>')

            # Map div
            parts.append(f'<div class="folium-map" id="{map_id}"></div>')

            # Initialisation script — folium puts it after </body>
            body_end = content.lower().rfind('</body>')
            if body_end != -1:
                tail = content[body_end + len('</body>'):]
                script_m = re.search(
                    r'<script\b[^>]*>(.*?)</script>',
                    tail, re.DOTALL | re.IGNORECASE
                )
                if script_m:
                    parts.append(f'<script>{script_m.group(1)}</script>')

            logger.info(f"Extracted folium embed from {Path(html_path).name}")
            return '\n'.join(parts)

        except Exception as e:
            logger.warning(f"Could not extract folium embed from {html_path}: {e}")
            return ''

    def _build_statistics_table_html(self, statistics: Dict) -> str:
        """Render statistics dict as an HTML table for embedding in a WordPress post."""
        # Ordered display list: keys rendered in this exact order, then any remaining keys
        _ordered_keys = [
            'start_time', 'end_time', 'duration',
            'distance_km', 'max_speed', 'avg_speed',
            'total_energy_wh', 'avg_power_w', 'max_power_w',
            'message_count',
        ]
        # Human-readable labels and units for known keys
        _label_map = {
            'start_time':        ('Start Time',        ''),
            'end_time':          ('End Time',          ''),
            'duration':          ('Duration',          ''),
            'distance_km':       ('Distance',          'km'),
            'max_speed':         ('Max Speed',         'km/h'),
            'avg_speed':         ('Average Speed',     'km/h'),
            'total_energy_wh':   ('Total Energy',      'Wh'),
            'avg_power_w':       ('Average Power',     'W'),
            'max_power_w':       ('Max Power',         'W'),
            'message_count':     ('Messages Recorded', ''),
        }
        # Keys we skip entirely (internal / not user-facing)
        _skip = {'duration_seconds'}

        def _make_row(key, value):
            label, unit = _label_map.get(key, (key.replace('_', ' ').title(), ''))
            if isinstance(value, float):
                formatted = f"{value:.2f}"
            else:
                formatted = html_module.escape(str(value))
            if unit:
                formatted = f"{formatted} {html_module.escape(unit)}"
            return (
                f'  <tr><th style="text-align:left;padding:6px 12px;'
                f'background:#f2f2f2;border:1px solid #ddd;">'
                f'{html_module.escape(label)}</th>'
                f'<td style="padding:6px 12px;border:1px solid #ddd;">'
                f'{formatted}</td></tr>\n'
            )

        rows = []
        seen = set()
        # Render known keys in defined order first
        for key in _ordered_keys:
            if key in statistics and key not in _skip:
                rows.append(_make_row(key, statistics[key]))
                seen.add(key)
        # Append any remaining keys not in the ordered list
        for key, value in statistics.items():
            if key not in seen and key not in _skip:
                rows.append(_make_row(key, value))

        if not rows:
            return ''

        html = '\n<h2>Statistics</h2>\n'
        html += '<table style="border-collapse:collapse;width:100%;max-width:480px;">\n'
        html += ''.join(rows)
        html += '</table>\n'
        return html

    def _apply_template(self, recording_data: Dict, template: str) -> str:
        """Apply template with placeholder substitution."""
        # Extract values for common placeholders
        values = {
            'start_time': recording_data.get('start_time', 'N/A'),
            'end_time': recording_data.get('end_time', 'N/A'),
            'duration': self._format_duration(
                recording_data.get('start_time'),
                recording_data.get('end_time')
            ),
            'name': recording_data.get('name', 'Track Log'),
            'description': recording_data.get('description', ''),
            'message_count': recording_data.get('message_count', 0)
        }

        # Apply substitutions
        try:
            return template.format(**values)
        except KeyError as e:
            logger.warning(f"Template placeholder not found: {e}")
            return template

    def _format_duration(self, start_time: str, end_time: str) -> str:
        """Format duration between timestamps."""
        try:
            if not start_time or not end_time:
                return "N/A"

            # Parse timestamps (handles various formats)
            from dateutil import parser
            start = parser.parse(start_time)
            end = parser.parse(end_time)

            duration = end - start

            hours = duration.seconds // 3600
            minutes = (duration.seconds % 3600) // 60
            seconds = duration.seconds % 60

            if hours > 0:
                return f"{hours}h {minutes}m {seconds}s"
            elif minutes > 0:
                return f"{minutes}m {seconds}s"
            else:
                return f"{seconds}s"

        except Exception as e:
            logger.warning(f"Failed to format duration: {e}")
            return "N/A"


if __name__ == '__main__':
    # CLI for testing WordPress connection
    import argparse

    parser = argparse.ArgumentParser(description="Test WordPress connection")
    parser.add_argument('--site-url', required=True, help="WordPress site URL")
    parser.add_argument('--username', required=True, help="WordPress username")
    parser.add_argument('--password', required=True, help="Application password")

    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Test connection
    publisher = WordPressPublisher(
        site_url=args.site_url,
        username=args.username,
        app_password=args.password,
    )

    success, message = publisher.test_connection()

    if success:
        print(f"✓ {message}")
    else:
        print(f"✗ {message}")
