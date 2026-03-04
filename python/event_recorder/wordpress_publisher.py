"""
WordPress Publisher - REST API Integration
Handles authentication, media upload, and post creation
"""

import logging
import os
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
        timeout: int = 30,
        max_retries: int = 3
    ):
        """
        Initialize WordPress publisher.

        Args:
            site_url: WordPress site URL (e.g., https://example.com)
            username: WordPress username
            app_password: Application password (24-char with spaces)
            timeout: Request timeout in seconds
            max_retries: Maximum retry attempts for failed requests
        """
        self.site_url = site_url.rstrip('/')
        self.username = username
        self.auth = HTTPBasicAuth(username, app_password)
        self.timeout = timeout
        self.max_retries = max_retries

        logger.info(f"WordPressPublisher initialized for {self.site_url}")

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
            # Test basic API access
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
        for attempt in range(self.max_retries):
            try:
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

    def upload_media(self, file_path: str, caption: str = None) -> Optional[int]:
        """
        Upload image to WordPress media library.

        Args:
            file_path: Path to image file
            caption: Optional image caption

        Returns:
            Media ID if successful, None otherwise
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

                # Update caption if provided
                if caption:
                    self._update_media_caption(media_id, caption)

                logger.info(f"Media uploaded successfully: ID={media_id}")
                return media_id
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
        excerpt: str = None
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
        template: str = None,
        category: str = "Track Logs",
        auto_publish: bool = False
    ) -> Optional[Dict]:
        """
        Publish recording as WordPress blog post.

        Args:
            recording_data: Recording metadata dict
            images: List of image dicts with 'path' and 'caption'
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
                media_id = self.upload_media(
                    image['path'],
                    caption=image.get('caption', '')
                )
                if media_id:
                    media_ids.append({
                        'id': media_id,
                        'caption': image.get('caption', ''),
                        'path': image['path']
                    })

            if not media_ids:
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
                download_links=download_links
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

            # Create post
            post_status = 'publish' if auto_publish else 'draft'
            post = self.create_post(
                title=title,
                content=content,
                status=post_status,
                categories=[category],
                featured_media=media_ids[0]['id'],  # First image as featured
                excerpt=excerpt
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
        download_links: List[Dict] = None
    ) -> str:
        """
        Build HTML content for post.

        Args:
            recording_data: Recording metadata
            media_ids: List of uploaded media dicts
            template: Optional HTML template

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

        # Add images
        content += "\n<h2>Data Visualizations</h2>\n"
        for media in media_ids:
            caption = media.get('caption', '')
            content += f'<figure class="wp-block-image">\n'
            content += f'  <img src="{self.site_url}/wp-content/uploads/{Path(media["path"]).name}" alt="{caption}" />\n'
            if caption:
                content += f'  <figcaption>{caption}</figcaption>\n'
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
        app_password=args.password
    )

    success, message = publisher.test_connection()

    if success:
        print(f"✓ {message}")
    else:
        print(f"✗ {message}")
