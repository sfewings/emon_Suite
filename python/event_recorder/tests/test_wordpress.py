#!/usr/bin/env python3
"""
Phase 4 Testing: WordPress Integration
Tests WordPress authentication, image upload, and post creation
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

def test_wordpress_connection():
    """Test WordPress connection and authentication."""
    print("="*70)
    print("PHASE 4 TESTING: WordPress Integration")
    print("="*70)
    print()

    # Check environment variables
    print("STEP 1: Check Configuration")
    wp_site = os.getenv("WP_SITE_URL")
    wp_user = os.getenv("WP_USERNAME")
    wp_pass = os.getenv("WP_APP_PASSWORD")

    if not all([wp_site, wp_user, wp_pass]):
        print("✗ WordPress credentials not configured")
        print()
        print("Please create .env file with:")
        print("  WP_SITE_URL=https://yourblog.com")
        print("  WP_USERNAME=admin")
        print('  WP_APP_PASSWORD="xxxx xxxx xxxx xxxx xxxx xxxx"')
        print()
        print("See .env.example and wordpress_config.example.yml for setup instructions")
        return False

    print(f"✓ Configuration found")
    print(f"  Site URL: {wp_site}")
    print(f"  Username: {wp_user}")
    print(f"  Password: {'*' * 24} (hidden)")
    print()

    # Import WordPress publisher
    try:
        from event_recorder.wordpress_publisher import WordPressPublisher
    except ImportError as e:
        print(f"✗ Failed to import WordPressPublisher: {e}")
        print("  Install dependencies: pip install requests python-dateutil")
        return False

    # Test connection
    print("STEP 2: Test WordPress Connection")
    try:
        wp = WordPressPublisher(
            site_url=wp_site,
            username=wp_user,
            app_password=wp_pass
        )

        success, message = wp.test_connection()

        if success:
            print(f"✓ {message}")
        else:
            print(f"✗ Connection failed: {message}")
            print()
            print("Troubleshooting:")
            print("  - Verify WordPress site URL (https://)")
            print("  - Check username spelling (case-sensitive)")
            print("  - Regenerate application password if needed")
            print("  - Ensure WordPress 5.6+ with HTTPS enabled")
            return False

    except Exception as e:
        print(f"✗ Connection test error: {e}")
        return False

    print()

    # Test media upload (if test plots exist)
    print("STEP 3: Test Image Upload")
    test_image = Path("test_plots/1/speed_over_time.png")

    if not test_image.exists():
        print("⚠️  No test images found")
        print("   Run: python test_full_cycle.py")
        print("   This will generate test plots for uploading")
    else:
        try:
            media_id = wp.upload_media(
                str(test_image),
                caption="Test Track - Speed Over Time"
            )

            if media_id:
                print(f"✓ Image uploaded successfully: Media ID={media_id}")
                print(f"  Check WordPress → Media → Library")

                # Test post creation
                print()
                print("STEP 4: Test Post Creation")

                post = wp.create_post(
                    title=f"Event Recorder Test - {wp_user}",
                    content="<h2>WordPress Integration Test</h2><p>This is a test post from Event Recorder Phase 4.</p>",
                    status="draft",
                    categories=["Track Logs"],
                    featured_media=media_id,
                    excerpt="Test post for Event Recorder WordPress integration"
                )

                if post:
                    print(f"✓ Post created successfully")
                    print(f"  Title: {post['title']}")
                    print(f"  URL: {post['link']}")
                    print(f"  Status: {post['status']}")
                    print(f"  Date: {post['date']}")
                    print()
                    print(f"  Check WordPress → Posts → All Posts")
                else:
                    print("✗ Post creation failed")
                    return False

            else:
                print("✗ Image upload failed")
                return False

        except Exception as e:
            print(f"✗ Upload/post error: {e}")
            return False

    print()
    print("="*70)
    print("WORDPRESS INTEGRATION TEST: PASSED ✅")
    print("="*70)
    print()
    print("Next steps:")
    print("  1. Check WordPress dashboard for test post")
    print("  2. Publish a real recording: curl -X POST http://localhost:5001/api/recordings/1/publish")
    print("  3. Proceed to Phase 5: Production Deployment")
    print()

    return True


if __name__ == '__main__':
    success = test_wordpress_connection()
    sys.exit(0 if success else 1)
