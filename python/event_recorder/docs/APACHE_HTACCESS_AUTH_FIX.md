# Apache .htaccess Auth Bypass for WordPress REST API

## Problem

When a WordPress site is protected by Apache HTTP Basic Authentication (`.htaccess`
with `AuthType Basic` + `Require valid-user`), the Python `WordPressPublisher`
client cannot connect via the REST API, even with a valid WordPress Application
Password.

### Symptoms

- `test_connection()` returns 401 with message: `"Access blocked (401) — see logs for detail"`
- The `WWW-Authenticate` header in the 401 response shows Apache's realm
  (e.g. `"Basic realm="For access please contact..."`) instead of WordPress's
  expected `"X-WP-Nonce"` or no `WWW-Authenticate` at all
- The Apache error log shows: `AH01618: user <wp_username> not found: /`
- The `whitelist_endpoint` (if configured) may succeed but the REST API call
  still fails

### Root Cause

Apache intercepts the `Authorization: Basic <credentials>` header sent by
`requests.auth.HTTPBasicAuth` and tries to validate it against its own
`AuthUserFile` (htpasswd file). The WordPress Application Password is **not**
in that file, so Apache rejects the request with 401 before it ever reaches
WordPress.

The IP whitelist (`Require ip ...`) only helps if the calling IP is listed.
If the client has a dynamic IP, the whitelist must be updated each time.

## Solution

Add a `Require expr` rule to the `.htaccess` file that lets REST API requests
through Apache's auth gate **only when an Authorization header is present**.
WordPress then validates the Application Password itself.

### .htaccess Configuration

Replace the existing auth block in the **document root** `.htaccess` (not the
WordPress subdirectory `.htaccess`) with:

```apache
# BEGIN WordPress Auth + REST API Bypass
# Apache 2.4 syntax
# REST API requests with an Authorization header bypass Apache auth;
# WordPress validates the application password itself.
<FilesMatch "\.php$">
    AuthUserFile "/path/to/wordpress/htusers"
    AuthType Basic
    AuthName "Restricted Area"
    <RequireAny>
        Require valid-user
        Require ip 192.0.2.10
        Require ip 203.0.113.20
        Require expr (%{HTTP:Authorization} != "" && %{QUERY_STRING} =~ /rest_route=/)
    </RequireAny>
</FilesMatch>

# Also protect the directory root (which serves index.php)
<FilesMatch "^$">
    AuthUserFile "/path/to/wordpress/htusers"
    AuthType Basic
    AuthName "Restricted Area"
    <RequireAny>
        Require valid-user
        Require ip 192.0.2.10
        Require ip 203.0.113.20
        Require expr (%{HTTP:Authorization} != "" && %{QUERY_STRING} =~ /rest_route=/)
    </RequireAny>
</FilesMatch>
<Files htusers>
    Require all denied
</Files>
# END WordPress Auth + REST API Bypass
```

### How It Works

The `Require expr` line grants access only when **both** conditions are true:

1. `%{HTTP:Authorization}` is not empty — the request carries credentials
2. `%{QUERY_STRING}` contains `rest_route=` — it's a WordPress REST API request

This means:

| Request type | Authorization header? | REST API? | Result |
|---|---|---|---|
| Browser visit (no auth) | No | No | Blocked by Apache (401) |
| Browser visit (with htusers auth) | Yes | No | Allowed by `Require valid-user` |
| REST API (no auth header) | No | Yes | Blocked by Apache (401) |
| REST API (with app password) | Yes | Yes | **Allowed through to WordPress** |
| REST API (with fake auth) | Yes | Yes | Passes Apache, WordPress returns 401 |

No unauthenticated access is possible. The REST API is only reachable when
credentials are present, and WordPress validates those credentials itself.

### Important Notes

- The `?rest_route=` query parameter format is used by `WordPressPublisher`
  (via `_api_url()`) for universal permalink compatibility
- If you use pretty permalinks (`/wp-json/wp/v2/...`), also add:
  `Require expr (%{HTTP:Authorization} != "" && %{REQUEST_URI} =~ /wp-json/)`
- The `SetEnvIfNoCase ^Authorization$ "(.+)" HTTP_AUTHORIZATION=$1` directive
  in `php.conf` ensures the Authorization header passes through to PHP-FPM
- This requires Apache 2.4+ (the `Require expr` directive is not available
  in Apache 2.2)

## Whitelist Endpoint (ewl.php) Bug

If using a whitelist endpoint script (e.g. `ewl.php`) to add the caller's IP
to `.htaccess`, ensure it writes to the **correct** `.htaccess` file.

The script must write to the **document root** `.htaccess` (where the
`AuthType Basic` directives live), not the WordPress subdirectory
`.htaccess` (which typically only has rewrite rules).

```php
// WRONG — writes to WordPress subdirectory (no auth rules there)
$htaccessFile = "/home/user/public_html/wordpress/.htaccess";

// CORRECT — writes to document root (where auth rules are)
$htaccessFile = "/home/user/public_html/.htaccess";
```

With the REST API auth bypass above, the whitelist endpoint is no longer
needed for the Python client to work. It remains useful for browser access
from dynamic IPs.

## Verification

After applying the fix, test from the client machine:

```bash
# Should return WordPress JSON (not Apache 401 HTML)
curl -s -H "Authorization: Basic dGVzdDp0ZXN0" \
  "https://yourblog.com/?rest_route=/wp/v2/users/me"
# Expected: {"code":"rest_not_logged_in","message":"You are not currently logged in.",...}

# Without auth header — should still be blocked by Apache
curl -s -o /dev/null -w "%{http_code}" "https://yourblog.com/?rest_route=/wp/v2/users/me"
# Expected: 401

# Regular page without auth — should be blocked by Apache
curl -s -o /dev/null -w "%{http_code}" "https://yourblog.com/"
# Expected: 401
```

Then test the Python client:

```python
from wordpress_publisher import WordPressPublisher

wp = WordPressPublisher(
    site_url="https://yourblog.com",
    username="event_recorder_user",
    app_password="xxxx xxxx xxxx xxxx xxxx xxxx"
)
success, message = wp.test_connection()
print(success, message)
# Expected: True "Connected as event_recorder_user (['administrator'])"
```
