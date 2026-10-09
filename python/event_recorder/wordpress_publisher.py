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
from typing import Callable, Dict, List, Optional, Tuple

import requests
from requests.auth import HTTPBasicAuth

from . import post_renderer

logger = logging.getLogger(__name__)


class WordPressPublisher:
    """
    WordPress REST API client for publishing blog posts.

    Uses Application Passwords for authentication (WordPress 5.6+).
    """

    # How a time is written in the post: seconds are as fine as a reader needs,
    # and the database's microseconds only made the date line hard to read.
    DISPLAY_TIME_FORMAT = post_renderer.DISPLAY_TIME_FORMAT

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
        """Stored UTC timestamp in the boat's timezone (post_renderer.local_time)."""
        return post_renderer.local_time(value)

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

    @staticmethod
    def _uploaded_file(media_data: Dict) -> Tuple[str, Optional[int]]:
        """
        Find the file WordPress kept from an upload, and its size if known.

        A photo wider than 2560 px is shrunk into a "-scaled" copy, and from
        then on source_url and filesize both describe that copy. The file that
        was sent is kept beside it under original_image, with no size given.
        Checking the copy against the phone's photo called every whole upload
        truncated and deleted it, so no photo reached a post.

        Args:
            media_data: An attachment, as WordPress returns it

        Returns:
            (URL of the uploaded file, its stored size or None)
        """
        details = media_data.get('media_details') or {}
        url = media_data.get('source_url', '')

        original = details.get('original_image')
        if original:
            return f"{url.rsplit('/', 1)[0]}/{original}", None

        return url, details.get('filesize')

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
        url, stored = self._uploaded_file(media_data)

        if stored is None:
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
                url, remote_size = self._uploaded_file(item)
                if os.path.basename(url) != filename:
                    continue

                if remote_size is None:
                    head = requests.head(url, auth=self.auth, timeout=self.timeout)
                    remote_size = head.headers.get('Content-Length')
                if remote_size is None or int(remote_size) != size:
                    continue

                return {'id': item['id'], 'url': url,
                        'large_url': self._large_url(item, url)}

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
                return {'id': media_id, 'url': media_url,
                        'large_url': self._large_url(media_data, media_url)}
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

    @staticmethod
    def _large_url(media_data: Dict, fallback: str) -> str:
        """
        The 'large' size WordPress made of an uploaded image, the 1024 px one
        the hand-written posts show (FR-24), or the original when it made
        none: an image already smaller than that has no large size.
        """
        sizes = (media_data.get('media_details') or {}).get('sizes') or {}
        return (sizes.get('large') or {}).get('source_url') or fallback

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

                # Check for exact match. Unescaped first as a guard: the REST
                # API gives "Ship's Log" as it is on both the dev blog and
                # enchantee.org, but WordPress stores some term names escaped
                # (wp-cli's lookup by name misses it), and with categories no
                # longer created (FR-30) a missed match would drop it silently
                for category in categories:
                    if html_module.unescape(category['name']).lower() == category_name.lower():
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

    def get_post(self, post_id: int) -> Optional[Dict]:
        """
        The post as WordPress has it now, or None if it no longer exists.

        Trashed counts as gone: updating a post in the trash would publish
        into a place nobody looks. Any other failure raises, because "could
        not tell" must not be read as "it is gone" and answered with a second
        post.
        """
        response = self._retry_request(
            'GET', self._api_url(f'posts/{post_id}') + '&context=edit')
        if response.status_code in (404, 410):
            return None
        response.raise_for_status()
        post = response.json()
        if post.get('status') == 'trash':
            return None
        return post

    def find_post_by_link(self, link: str) -> Optional[Dict]:
        """
        The post a published URL belongs to, or None if it is gone.

        For recordings published before the post id was kept (TR-11), which
        have only their link. Handles both forms WordPress gives out: ?p=N on
        a site with plain permalinks, and a slug under pretty ones. Raises
        when WordPress cannot be asked, as get_post does.
        """
        from urllib.parse import parse_qs, urlparse
        parsed = urlparse(link)
        query = parse_qs(parsed.query)
        if 'p' in query:
            return self.get_post(int(query['p'][0]))

        slug = [part for part in parsed.path.split('/') if part]
        if not slug:
            return None
        response = self._retry_request(
            'GET', self._api_url('posts') +
            f'&slug={slug[-1]}&status=publish,future,draft,pending,private&context=edit')
        response.raise_for_status()
        matches = response.json()
        return matches[0] if len(matches) == 1 else None

    def list_categories(self) -> List[str]:
        """The site's category names, unescaped, most used first (FR-30)."""
        response = self._retry_request(
            'GET', self._api_url('categories') + '&per_page=100&orderby=count&order=desc')
        response.raise_for_status()
        return [html_module.unescape(c['name']) for c in response.json()
                if c.get('name') and c['name'] != 'Uncategorized']

    def post_contents(self, category_name: str, count: int = 100) -> List[str]:
        """
        The rendered content of the latest `count` posts in a category, for
        the crew lines at their top (FR-30). Empty if there is no such category.
        """
        category_id = self.get_category_id(category_name, create=False)
        if not category_id:
            return []
        response = self._retry_request(
            'GET', self._api_url('posts') +
            f'&categories={category_id}&per_page={count}&_fields=content')
        response.raise_for_status()
        return [p.get('content', {}).get('rendered', '') for p in response.json()]

    def create_post(
        self,
        title: str,
        content: str,
        status: str = 'draft',
        categories: List[str] = None,
        featured_media: int = None,
        excerpt: str = None,
        date: str = None,
        post_id: int = None
    ) -> Optional[Dict]:
        """
        Create WordPress blog post, or update an existing one.

        Args:
            title: Post title
            content: Post content (HTML)
            status: Post status (draft, publish, pending)
            categories: List of category names
            featured_media: Featured image media ID
            excerpt: Post excerpt
            date: Publication date in ISO 8601 format (YYYY-MM-DDTHH:MM:SS);
                  WordPress treats this as the site's local timezone
            post_id: Update this post instead of creating one (TR-11)

        Returns:
            Post data dict if successful, None otherwise. `modified_gmt` is
            WordPress's own record of the change, kept so a later update can
            tell whether the post was edited in wp-admin in between.
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
                    # Never created from a name (FR-30): the event page offers
                    # the site's own list, so a name not on it is a mistake to
                    # report, not a category to add to enchantee.org
                    cat_id = self.get_category_id(cat_name, create=False)
                    if cat_id:
                        category_ids.append(cat_id)
                    else:
                        logger.warning(f"No category '{cat_name}' on the site; left off the post")

                if category_ids:
                    post_data['categories'] = category_ids

            # Add featured image
            if featured_media:
                post_data['featured_media'] = featured_media

            if post_id:
                logger.info(f"Updating post {post_id}: {title}")
                endpoint, expected = f'posts/{post_id}', 200
            else:
                logger.info(f"Creating post: {title}")
                endpoint, expected = 'posts', 201
            response = self._retry_request(
                'POST',
                self._api_url(endpoint),
                json=post_data
            )

            if response.status_code == expected:
                post = response.json()
                logger.info(f"Post {'updated' if post_id else 'created'} successfully: {post['link']}")
                return {
                    'id': post['id'],
                    'title': post['title']['rendered'],
                    'link': post['link'],
                    'status': post['status'],
                    'date': post['date'],
                    'modified_gmt': post.get('modified_gmt'),
                }
            else:
                logger.error(f"Post {'update' if post_id else 'creation'} failed: "
                             f"{response.status_code} - {response.text}")
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
        auto_publish: bool = False,
        post_id: int = None,
        progress: Callable[[str, int, int], None] = None,
        blocks: List[Dict] = None,
        draft: Dict = None
    ) -> Optional[Dict]:
        """
        Publish recording as WordPress blog post, or update the post it already is.

        Args:
            recording_data: Recording metadata dict
            images: List of image dicts with 'path' and 'caption'
            exports: List of export file dicts
            statistics: Optional statistics dict from statistics_summary.json
            map_htmls: Optional list of folium HTML file paths to embed as interactive maps
            template: HTML template string (with {placeholders})
            category: WordPress category name
            auto_publish: Publish immediately (vs draft)
            post_id: Update this post rather than create one (TR-11)
            progress: Called as progress(step, done, total) as each file goes
                up, so a background job can say how far it has got
            blocks: The draft's blocks (FR-24); today's layout when None
            draft: The draft's fields: title, excerpt, categories and crew,
                each used in place of the recording's when present

        Returns:
            Dict with post info if successful, None otherwise
        """
        logger.info(f"Publishing recording: {recording_data.get('name')}")

        total_files = len(images) + len(exports or [])
        sent = 0

        def report(step):
            if progress:
                progress(step, sent, total_files)

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
                report(f"Uploading {sent + 1} of {total_files}")
                media_result = self.upload_media(
                    image['path'],
                    caption=image.get('caption', ''),
                    upload_name=f"{prefix}{Path(image['path']).name}"
                )
                if media_result:
                    media_ids.append({
                        'id': media_result['id'],
                        'url': media_result['url'],
                        # The 1024 px size the post shows (FR-24)
                        'large_url': media_result.get('large_url'),
                        'caption': image.get('caption', ''),
                        'image_type': image.get('image_type', 'plot'),
                        'path': image['path'],
                        # Places a photo among the crew's notes (FR-29)
                        'taken_at': image.get('taken_at'),
                    })
                else:
                    failed_uploads.append(Path(image['path']).name)
                sent += 1

            if not media_ids and not statistics and not map_htmls:
                logger.error("No images uploaded successfully")
                return None

            # Upload export files and collect download links
            download_links = []
            for exp in (exports or []):
                report(f"Uploading {sent + 1} of {total_files}")
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
                sent += 1

            report("Updating the post" if post_id else "Creating the post")

            # Build HTML content
            content = self._build_post_content(
                recording_data,
                media_ids,
                template,
                download_links=download_links,
                statistics=statistics,
                map_htmls=map_htmls,
                blocks=blocks,
                draft=draft
            )

            draft = draft or {}

            # Extract title
            title = draft.get('title') or recording_data.get(
                'name', f"Track Log - {datetime.now().strftime('%Y-%m-%d')}")

            # Create excerpt
            excerpt = draft.get('excerpt') or recording_data.get('description', '')
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
                categories=draft.get('categories') or [category],
                featured_media=featured_id,
                excerpt=excerpt,
                date=post_date,
                post_id=post_id
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
        map_htmls: List[str] = None,
        blocks: List[Dict] = None,
        draft: Dict = None
    ) -> str:
        """
        The post's content, drawn by post_renderer (FR-24) from the given
        blocks. The service always passes them; the Track Log layout is only
        the fallback for a direct caller that does not.
        """
        ctx = post_renderer.PostContext(
            recording_data, media=media_ids, statistics=statistics,
            map_htmls=map_htmls, downloads=download_links, template=template,
            draft=draft)
        return post_renderer.render(blocks or post_renderer.LAYOUT_TRACK_LOG, ctx)

    # Kept for the callers they had; the work is post_renderer's now

    def _apply_template(self, recording_data: Dict, template: str) -> str:
        return post_renderer.apply_template(recording_data, template)

    def _format_duration(self, start_time: str, end_time: str) -> str:
        return post_renderer.format_duration(start_time, end_time)


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
