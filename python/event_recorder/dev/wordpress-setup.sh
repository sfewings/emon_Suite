#!/bin/sh
# Install the local test blog and give the dev recorder an application password for it.
#
#   docker compose -f dev/docker-compose.yml --profile wordpress up -d
#   sh dev/wordpress-setup.sh
#
# Safe to run again. Each step checks before it acts, and a new application password is
# only made when dev/.env does not have one. Delete dev/.env to get a fresh one.
#
# The blog is http://localhost:8080, admin / admin, and is nothing but a target for test
# posts. Its categories are enchantee.org's, so FR-30 has a real list to work from.

set -e
cd "$(dirname "$0")"
export MSYS_NO_PATHCONV=1   # Git Bash would otherwise rewrite '/%postname%/' as a path

wp() { docker compose run --rm -T wpcli wp "$@"; }

# Connected to the way WordPress connects, through PHP. `wp db check` would use the
# image's MariaDB client, which refuses MySQL 8's self-signed certificate.
db_ready() {
    wp eval --skip-wordpress '
        $db = @mysqli_connect(getenv("WORDPRESS_DB_HOST"), getenv("WORDPRESS_DB_USER"),
                              getenv("WORDPRESS_DB_PASSWORD"), getenv("WORDPRESS_DB_NAME"));
        exit($db ? 0 : 1);'
}

echo "waiting for WordPress and its database..."
tries=0
until db_ready >/dev/null 2>&1; do
    tries=$((tries + 1))
    if [ "$tries" -gt 60 ]; then
        echo "WordPress did not come up. Is the profile running?"
        echo "  docker compose -f dev/docker-compose.yml --profile wordpress up -d"
        exit 1
    fi
    sleep 2
done

if ! wp core is-installed >/dev/null 2>&1; then
    wp core install --url=http://localhost:8080 --title="Enchantee (dev)" \
        --admin_user=admin --admin_password=admin \
        --admin_email=dev@example.invalid --skip-email
fi

# Perth time, as enchantee.org must be: the recorder sends a post's date as Perth local
# time, which a UTC blog reads as eight hours ahead and schedules as a future post
wp option update timezone_string 'Australia/Perth' >/dev/null

# Pretty permalinks, so /wp-json/ resolves as it does on enchantee.org
wp rewrite structure '/%postname%/' --hard >/dev/null

for category in "Ship's Log" "Track Logs" "Twilight" "Club event" "Rottnest" \
                "Dolphins" "Whales" "Maintenance" "No Sail" "Arduino"; do
    # Created, or already there. Not looked up by name first: WordPress stores
    # "Ship's Log" with the apostrophe escaped, so that lookup never matches it.
    wp term create category "$category" --porcelain >/dev/null 2>&1 || true
done

if ! grep -q '^WP_APP_PASSWORD=' .env 2>/dev/null; then
    password=$(wp user application-password create admin event_recorder_dev --porcelain | tr -d '\r')
    # The recorder reaches the blog by its service name on the compose network.
    # Media URLs in posts still say localhost:8080, the site's own address, which is
    # what a browser on this machine needs.
    cat > .env <<EOF
WP_SITE_URL=http://wordpress
WP_USERNAME=admin
WP_APP_PASSWORD="$password"
EOF
    echo "wrote dev/.env"
fi

# Recreated, not restarted: the environment is read when a container is created
docker compose up -d --force-recreate recorder

echo
echo "Blog:     http://localhost:8080        (wp-admin: admin / admin)"
echo "Recorder: http://localhost:5000"
