"""
WordPress Publisher - REST API Integration
Handles authentication, media upload, and post creation
"""

import html as html_module
import logging
import os
import re
import time
from datetime import datetime, timezone
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

    # How a time is written in the post: seconds are as fine as a reader needs,
    # and the database's microseconds only made the date line hard to read.
    DISPLAY_TIME_FORMAT = '%Y-%m-%d %H:%M:%S'

    # The stylesheets an embedded map may bring into the page with it. Every
    # rule in these is scoped to the map's own classes. Anything else folium
    # links, Bootstrap above all, styles the elements of the page itself and
    # cannot be let near a post.
    _MAP_STYLESHEETS = (
        'leaflet.css',
        'awesome-markers',
        'awesome.rotate',
        'fontawesome',
    )

    def __init__(
        self,
        site_url: str,
        username: str,
        app_password: str,
        timeout: int = 30,
        max_retries: int = 3,
        max_upload_mb: int = 25
    ):
        """
        Initialize WordPress publisher.

        Args:
            site_url: WordPress site URL (e.g., https://example.com)
            username: WordPress username
            app_password: Application password (24-char with spaces)
            timeout: Request timeout in seconds. Applies to uploads too: a
                longer one was tried for the sake of the large CSV export and
                only made the failure slower, since the server stops reading a
                body it will not accept and the write blocks until the timeout
                expires either way.
            max_retries: Maximum retry attempts for failed requests
            max_upload_mb: Largest file worth sending. What can be uploaded is
                set by the link, not by the server: a quarter-gigabyte CSV
                cannot cross a marina uplink inside the timeout, and the
                attempt leaves a truncated attachment behind each time. 0
                removes the limit.
        """
        self.site_url = site_url.rstrip('/')
        self.username = username
        self.auth = HTTPBasicAuth(username, app_password)
        self.timeout = timeout
        self.max_retries = max_retries
        self.max_upload_bytes = max_upload_mb * 1048576 if max_upload_mb else 0

        logger.info(f"WordPressPublisher initialized for {self.site_url}, {self.username}, {app_password})")

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

    def test_connection(self) -> Tuple[bool, str]:
        """
        Test WordPress API connection and authentication.

        Returns:
            Tuple of (success: bool, message: str)
        """
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
                www_auth = response.headers.get('WWW-Authenticate', '')
                logger.error(
                    f"WordPress 401. WWW-Authenticate: {www_auth!r}. "
                    f"Response body: {response.text[:500]!r}"
                )
                if 'WordPress' not in www_auth:
                    return False, "Access blocked (401) — see logs for detail"
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

    def _retry_request(self, method: str, url: str,
                       retry_timeouts: bool = True, **kwargs) -> requests.Response:
        """
        Execute HTTP request with exponential backoff retry.

        Args:
            method: HTTP method (GET, POST, etc.)
            url: Request URL
            retry_timeouts: Whether a timeout is worth another attempt. False
                for uploads: the server keeps the bytes it received before the
                connection dropped and makes an attachment out of them, so
                each retry of an upload too slow to finish leaves behind
                another truncated copy of the file.
            **kwargs: Additional arguments for requests

        Returns:
            Response object

        Raises:
            requests.exceptions.RequestException: If all retries fail
        """
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

                if self._is_permanent_error(response):
                    logger.warning(
                        f"WordPress refused the request ({response.status_code}); not retrying"
                    )
                    return response

                # Server error - retry with backoff
                logger.warning(f"Server error {response.status_code}, attempt {attempt + 1}/{self.max_retries}")

            except requests.exceptions.RequestException as e:
                if not retry_timeouts and self._is_timeout(e):
                    logger.error(f"Upload did not finish in {self.timeout}s: {e}")
                    raise

                logger.warning(f"Request failed: {e}, attempt {attempt + 1}/{self.max_retries}")

                if attempt == self.max_retries - 1:
                    raise

            # Exponential backoff: 1s, 2s, 4s
            if attempt < self.max_retries - 1:
                time.sleep(2 ** attempt)

        return response

    @staticmethod
    def _local_time(value) -> Optional[datetime]:
        """
        Read a recorded timestamp and return it in the boat's timezone.

        Recordings are stored with datetime.utcnow(). Left alone, the post
        carried UTC throughout: an afternoon sail dated to that morning, and a
        WordPress date field that reads whatever it is given as site-local.

        Args:
            value: Stored timestamp, as a string or datetime

        Returns:
            Naive local datetime, or None when there is nothing to read
        """
        if not value:
            return None

        if isinstance(value, datetime):
            stamp = value
        else:
            from dateutil import parser as _dateutil_parser
            try:
                stamp = _dateutil_parser.parse(str(value))
            except (ValueError, OverflowError, TypeError):
                return None

        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return stamp.astimezone().replace(tzinfo=None)

    @staticmethod
    def _is_timeout(error: Exception) -> bool:
        """
        Report whether a request failed for want of time.

        A write that runs out of time surfaces as a bare ConnectionError
        wrapping TimeoutError rather than as requests' own Timeout, so the
        message has to be read as well as the type.

        Args:
            error: The exception raised by requests

        Returns:
            True when the request ran out of time
        """
        if isinstance(error, requests.exceptions.Timeout):
            return True
        return 'timed out' in str(error).lower()

    def _remove_partial_upload(self, upload_name: str, expected: int):
        """
        Delete a truncated attachment left behind by an upload that timed out.

        Nothing comes back from a request that times out mid-body, so the
        attachment WordPress made from the bytes it did receive has to be
        found by name afterwards. Only a copy whose size is wrong is removed,
        so an upload that in fact completed is left alone.

        Args:
            upload_name: Name the file was being uploaded under
            expected: Size the whole file should be
        """
        try:
            response = self._retry_request(
                'GET', self._api_url('media'),
                params={'search': upload_name, 'per_page': 100}
            )
            if response.status_code != 200:
                return

            for item in response.json():
                if os.path.basename(item.get('source_url', '')) != upload_name:
                    continue
                stored = (item.get('media_details') or {}).get('filesize')
                if stored is not None and int(stored) != expected:
                    if self._delete_media(item['id']):
                        logger.info(
                            f"Removed the truncated {upload_name} "
                            f"({int(stored)} of {expected} bytes) left by the timeout"
                        )

        except (requests.exceptions.RequestException, ValueError, KeyError) as e:
            logger.warning(f"Could not clear a partial {upload_name}: {e}")

    def _uploaded_whole(self, media_data: Dict, expected: int, name: str) -> bool:
        """
        Check that the file WordPress stored is the file that was sent.

        WordPress builds an attachment from whatever reached it, so an upload
        cut short by the timeout becomes a valid-looking media item holding a
        truncated file. Three of those, at 34MB each, stood in the library
        against a 255MB export. Anything short of the whole file is no use to
        a reader and has to go.

        Args:
            media_data: The created attachment, as WordPress returned it
            expected: Local file size in bytes
            name: Upload name, for the log

        Returns:
            True when the stored size matches
        """
        stored = (media_data.get('media_details') or {}).get('filesize')

        if stored is None:
            url = media_data.get('source_url', '')
            try:
                head = requests.head(url, auth=self.auth, timeout=self.timeout)
                stored = head.headers.get('Content-Length')
            except requests.exceptions.RequestException:
                stored = None

        if stored is None:
            logger.warning(f"Could not confirm the stored size of {name}; keeping it")
            return True

        if int(stored) != expected:
            logger.error(
                f"{name} arrived truncated: {int(stored)} of {expected} bytes. "
                f"Removing the partial upload."
            )
            return False

        return True

    def _delete_media(self, media_id: int) -> bool:
        """
        Delete a media item, discarding it entirely rather than trashing it.

        Args:
            media_id: Attachment ID

        Returns:
            True if WordPress reported it gone
        """
        try:
            response = self._retry_request(
                'DELETE', self._api_url(f'media/{media_id}'), params={'force': True}
            )
            return response.status_code == 200
        except requests.exceptions.RequestException as e:
            logger.warning(f"Could not delete media {media_id}: {e}")
            return False

    @staticmethod
    def _is_permanent_error(response: requests.Response) -> bool:
        """
        Report whether WordPress has refused this request for good.

        A blocked file type comes back as a 500, which the retry loop would
        otherwise read as a server hiccup and send the whole file twice more.
        The refusal is permanent, and the files it applies to are the large
        ones.

        Args:
            response: Response to classify

        Returns:
            True when retrying cannot succeed
        """
        permanent_codes = {
            'rest_upload_sideload_error',    # file type not permitted
            'rest_upload_unknown_error',
            'rest_upload_file_too_big',
        }
        try:
            return response.json().get('code') in permanent_codes
        except ValueError:
            return False

    def _find_existing_media(self, filename: str, size: int) -> Optional[Dict]:
        """
        Find a media item already holding this exact file.

        Publishing uploads every image before it creates the post, so each
        attempt that failed afterwards left a full set behind: the library had
        forty copies of the CSV against four posts. A file is only reused when
        its name and its length both match, so a reprocessed chart is uploaded
        again rather than the stale one being shown.

        Args:
            filename: Name the file is uploaded under
            size: Local file size in bytes

        Returns:
            Dict with 'id' and 'url' of the match, or None
        """
        try:
            response = self._retry_request(
                'GET', self._api_url('media'),
                params={'search': filename, 'per_page': 100}
            )
            if response.status_code != 200:
                return None

            for item in response.json():
                url = item.get('source_url', '')
                if os.path.basename(url) != filename:
                    continue

                remote_size = (item.get('media_details') or {}).get('filesize')
                if remote_size is None:
                    head = requests.head(url, auth=self.auth, timeout=self.timeout)
                    remote_size = head.headers.get('Content-Length')
                if remote_size is None or int(remote_size) != size:
                    continue

                return {'id': item['id'], 'url': url}

        except (requests.exceptions.RequestException, ValueError, KeyError) as e:
            logger.debug(f"Could not check for an existing {filename}: {e}")

        return None

    def upload_media(self, file_path: str, caption: str = None,
                     upload_name: str = None) -> Optional[Dict]:
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

        upload_name = upload_name or file_path.name
        size = file_path.stat().st_size

        existing = self._find_existing_media(upload_name, size)
        if existing:
            logger.info(f"Reusing media already uploaded: {upload_name} (ID={existing['id']})")
            return existing

        try:
            # Read file
            with open(file_path, 'rb') as f:
                file_data = f.read()

            # Prepare headers
            headers = {
                'Content-Disposition': f'attachment; filename="{upload_name}"',
                'Content-Type': self._get_mime_type(file_path)
            }

            # Upload
            logger.info(f"Uploading media: {upload_name}")
            response = self._retry_request(
                'POST',
                self._api_url('media'),
                headers=headers,
                data=file_data,
                retry_timeouts=False
            )

            if response.status_code == 201:
                media_data = response.json()
                media_id = media_data['id']
                media_url = media_data.get('source_url', media_data.get('link', ''))

                if not self._uploaded_whole(media_data, size, upload_name):
                    self._delete_media(media_id)
                    return None

                # Update caption if provided
                if caption:
                    self._update_media_caption(media_id, caption)

                logger.info(f"Media uploaded successfully: ID={media_id}")
                return {'id': media_id, 'url': media_url}
            else:
                logger.error(
                    f"Media upload failed for {file_path.name}: "
                    f"{response.status_code} - {response.text}"
                )
                return None

        except Exception as e:
            logger.error(f"Failed to upload media {file_path}: {e}")
            if self._is_timeout(e):
                self._remove_partial_upload(upload_name, size)
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

    def upload_export_file(self, file_path: str, label: str = None,
                           upload_name: str = None) -> Optional[Dict]:
        """
        Upload an export file (CSV, KML, GPX) to the WordPress media library.

        Args:
            file_path: Path to the export file
            label: Optional description for the media item
            upload_name: Name to store it under. Defaults to the file's own.

        Returns:
            Dict with 'id' and 'url' if successful, None otherwise
        """
        file_path = Path(file_path)
        if not file_path.exists():
            logger.error(f"Export file not found: {file_path}")
            return None

        upload_name = upload_name or file_path.name
        size = file_path.stat().st_size

        if self.max_upload_bytes and size > self.max_upload_bytes:
            logger.error(
                f"Not uploading {upload_name}: {size / 1048576:.0f} MB is over the "
                f"{self.max_upload_bytes / 1048576:.0f} MB limit. It would not finish "
                f"inside the {self.timeout}s timeout, and the part that did arrive "
                f"would be kept as a truncated file."
            )
            return None

        existing = self._find_existing_media(upload_name, size)
        if existing:
            logger.info(f"Reusing export already uploaded: {upload_name} (ID={existing['id']})")
            return existing

        try:
            with open(file_path, 'rb') as f:
                file_data = f.read()

            headers = {
                'Content-Disposition': f'attachment; filename="{upload_name}"',
                'Content-Type': self._get_mime_type(file_path),
            }

            logger.info(f"Uploading export file: {upload_name}")
            response = self._retry_request('POST', self._api_url('media'),
                                            headers=headers, data=file_data,
                                            retry_timeouts=False)

            if response.status_code == 201:
                media_data = response.json()
                media_id = media_data['id']
                media_url = media_data.get('source_url', media_data.get('link', ''))
                if not self._uploaded_whole(media_data, size, upload_name):
                    self._delete_media(media_id)
                    return None
                if label:
                    self._update_media_caption(media_id, label)
                logger.info(f"Export file uploaded: ID={media_id}")
                return {'id': media_id, 'url': media_url}
            else:
                logger.error(
                    f"Export upload failed for {upload_name} "
                    f"(type {headers['Content-Type']}, {size} bytes): "
                    f"{response.status_code} - {response.text}"
                )
                return None

        except Exception as e:
            logger.error(f"Failed to upload export {file_path}: {e}")
            if self._is_timeout(e):
                self._remove_partial_upload(upload_name, size)
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
            # Files that did not make it. A post is still worth publishing
            # without them, but the caller has to be told: a silently missing
            # Downloads section looks like a successful publish.
            failed_uploads = []

            # Every recording generates the same filenames — gps_speed.png,
            # route_map_0.png — so without this they all land in one library as
            # gps_speed-1 through -14 and no upload can ever be matched to the
            # recording that made it, or reused on a second attempt.
            prefix = f"rec{recording_data['id']}_" if recording_data.get('id') else ''

            # Upload images to WordPress
            media_ids = []
            for image in images:
                media_result = self.upload_media(
                    image['path'],
                    caption=image.get('caption', ''),
                    upload_name=f"{prefix}{Path(image['path']).name}"
                )
                if media_result:
                    media_ids.append({
                        'id': media_result['id'],
                        'url': media_result['url'],
                        'caption': image.get('caption', ''),
                        'image_type': image.get('image_type', 'plot'),
                        'path': image['path']
                    })
                else:
                    failed_uploads.append(Path(image['path']).name)

            if not media_ids and not statistics and not map_htmls:
                logger.error("No images uploaded successfully")
                return None

            # Upload export files and collect download links
            download_links = []
            for exp in (exports or []):
                result = self.upload_export_file(
                    exp['path'], label=exp.get('label', ''),
                    upload_name=f"{prefix}{Path(exp['path']).name}"
                )
                if result:
                    download_links.append({
                        'url': result['url'],
                        'label': exp.get('label', exp['export_type'].upper()),
                        'export_type': exp['export_type'],
                    })
                else:
                    failed_uploads.append(Path(exp['path']).name)

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
                shown_start = self._local_time(recording_data.get('start_time'))
                duration = self._format_duration(
                    recording_data.get('start_time'),
                    recording_data.get('end_time')
                )
                excerpt = (
                    f"Track recording from "
                    f"{shown_start.strftime(self.DISPLAY_TIME_FORMAT) if shown_start else 'N/A'}. "
                    f"Duration: {duration}"
                )

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
            # WordPress reads this field as the site's local time, so it has to
            # be given local time and not the stored UTC.
            local_start = self._local_time(recording_data.get('start_time'))
            post_date = local_start.strftime('%Y-%m-%dT%H:%M:%S') if local_start else None

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

            if post and failed_uploads:
                logger.warning(
                    f"Post created without {len(failed_uploads)} file(s) that "
                    f"failed to upload: {', '.join(failed_uploads)}"
                )
                post['failed_uploads'] = failed_uploads

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
            local_start = self._local_time(recording_data.get('start_time'))
            shown_date = (local_start.strftime(self.DISPLAY_TIME_FORMAT)
                          if local_start else 'N/A')

            content = f"<h2>Track Summary</h2>\n"
            content += f"<p><strong>Date:</strong> {shown_date}</p>\n"

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

        # Split images: user-uploaded photos go in their own section before plots
        user_photos = [m for m in media_ids if m.get('image_type') == 'user_upload']
        plots = [m for m in media_ids if m.get('image_type', 'plot') == 'plot']

        # The drawn track goes above the fold, with the summary: it is the one
        # picture that says what the day was, and the homepage shows nothing
        # below the break. Taken out of `plots` so it is not repeated further
        # down among the charts.
        route_map = self._pop_primary_route_map(plots)
        if route_map:
            content += self._build_figure_html(route_map.get('url', ''),
                                               route_map.get('caption', ''))

        # Everything below is the body of the post. The red-shadow theme on
        # enchantee.org renders the homepage with the_content(), so without this
        # break the listing carries the whole post — map JS included — and the
        # layout collapses under it.
        #
        # The inner tag has no spaces: the_content() looks for <!--more-->, and
        # <!-- more --> is just a comment to it. The wp:more wrapper is what the
        # block editor writes around it, and keeps the break editable there.
        content += "\n<!-- wp:more -->\n<!--more-->\n<!-- /wp:more -->\n"

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

        # Photos section — user uploads with by-line captions
        if user_photos:
            content += "\n<h2>Photos</h2>\n"
            for media in user_photos:
                content += self._build_figure_html(media.get('url', ''),
                                                   media.get('caption', ''),
                                                   italic_caption=True,
                                                   default_alt='Photo')

        # Data Visualizations section — generated plots
        if plots:
            content += "\n<h2>Data Visualizations</h2>\n"
            for media in plots:
                content += self._build_figure_html(media.get('url', ''),
                                                   media.get('caption', ''))

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

    @staticmethod
    def _pop_primary_route_map(plots: List[Dict]) -> Optional[Dict]:
        """
        Remove the first route map from a list of plots and return it.

        Titles are 'Route Map' for a single GPS unit and 'Route Map 0',
        'Route Map 1' when the boat carries more than one; sorting picks the
        lowest, which is the primary unit. The remaining units' maps stay with
        the other charts.

        Args:
            plots: Generated-plot media dicts. The chosen entry is removed.

        Returns:
            The route map's media dict, or None when no map was uploaded
        """
        def is_route_map(media: Dict) -> bool:
            caption = (media.get('caption') or '').strip().lower()
            stem = Path(media.get('path', '')).stem.lower()
            return caption.startswith('route map') or stem.startswith('route_map')

        candidates = [m for m in plots if is_route_map(m)]
        if not candidates:
            return None

        primary = min(candidates,
                      key=lambda m: (m.get('caption') or Path(m.get('path', '')).stem))
        plots.remove(primary)
        return primary

    @staticmethod
    def _build_figure_html(img_url: str, caption: str,
                           italic_caption: bool = False,
                           default_alt: str = '') -> str:
        """
        Render one image as a WordPress figure block.

        Args:
            img_url: Uploaded image URL
            caption: Caption text, used for the alt text as well
            italic_caption: Wrap the caption in <em>, as photo by-lines are
            default_alt: Alt text to fall back on when there is no caption

        Returns:
            HTML string
        """
        safe_caption = html_module.escape(caption) if caption else ''
        alt_text = safe_caption or html_module.escape(default_alt)

        html = '<figure class="wp-block-image">\n'
        html += f'  <img src="{img_url}" alt="{alt_text}" />\n'
        if caption:
            body = f'<em>{safe_caption}</em>' if italic_caption else safe_caption
            html += f'  <figcaption>{body}</figcaption>\n'
        html += '</figure>\n\n'
        return html

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

            # CDN stylesheets, but only the map's own. folium also links the
            # whole Bootstrap framework and Bootstrap 3's glyphicons, and both
            # carry a CSS reset: html{font-size:62.5%}, body{margin:0} and
            # rules for figure and img. Copied into a post they restyle the
            # page around the map, which is what pushed the blog off centre,
            # changed its type size and dropped the banner.
            for m in re.finditer(
                r'<link\b[^>]*\brel=["\']stylesheet["\'][^>]*>',
                content, re.IGNORECASE
            ):
                href_m = re.search(r'href=["\']([^"\']+)["\']', m.group(0))
                href = href_m.group(1) if href_m else ''
                if any(part in href for part in self._MAP_STYLESHEETS):
                    parts.append(m.group(0))
                else:
                    logger.debug(f"Skipping page-wide stylesheet in map embed: {href}")

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
            # knots, not km/h: these come straight off gps/speed, which the
            # charts label knots too. Labelled km/h they disagreed with the
            # distance and duration beside them by a factor of 1.9.
            'max_speed':         ('Max Speed',         'knots'),
            'avg_speed':         ('Average Speed',     'knots'),
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
