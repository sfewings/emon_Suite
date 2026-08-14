# WordPress Setup Guide - Quick Reference

## Initial Setup (Do Once)

### 1. Start All Services
```bash
cd test_event_recorder
docker-compose up -d
```

Wait 30 seconds for MySQL to initialize.

### 2. Complete WordPress Installation

Open browser: **http://localhost:8080**

Fill in:
- **Site Title**: Event Recorder Test Blog
- **Username**: `admin` (remember this!)
- **Password**: Choose a strong password
- **Email**: your@email.com
- Click **"Install WordPress"**

### 3. Generate Application Password

1. **Login to WordPress Admin**
   - URL: http://localhost:8080/wp-admin
   - Username: `admin` (or what you chose)
   - Password: (what you set)

2. **Navigate to Profile**
   - Click "Users" → "Profile" (or your username in top right)
   - Scroll down to "Application Passwords" section

3. **Create Application Password**
   - Application Name: `Event Recorder`
   - Click **"Add New Application Password"**
   - **COPY THE PASSWORD** (format: `xxxx xxxx xxxx xxxx xxxx xxxx`)
   - You won't be able to see it again!

### 4. Update .env File

```bash
nano .env
```

Update these lines:
```env
WP_USERNAME=admin  # Or your chosen username
WP_APP_PASSWORD=abcd 1234 efgh 5678 ijkl 9012  # PASTE YOUR PASSWORD HERE
```

Save and exit (Ctrl+X, Y, Enter)

### 5. Restart Event Recorder

```bash
docker-compose restart event_recorder
```

### 6. Test Connection

```bash
# Via curl
curl http://localhost:5001/api/wordpress/test

# Via browser
# Open: http://localhost:5001
# Click "Test WordPress Connection"
```

You should see: ✅ "Connection successful! Connected as: admin"

---

## Quick Test Workflow

### Create and Publish a Test Recording

1. **Publish GPS movement data**
   ```bash
   # Start position
   mosquitto_pub -h localhost -t "gps/latitude/0" -m "-31.9505"
   mosquitto_pub -h localhost -t "gps/longitude/0" -m "115.8605"

   # Wait 15 seconds, then simulate movement
   sleep 15

   # New position (20+ meters away)
   mosquitto_pub -h localhost -t "gps/latitude/0" -m "-31.9510"
   mosquitto_pub -h localhost -t "gps/longitude/0" -m "115.8610"

   # Wait 70 seconds for recording to stop
   sleep 70
   ```

2. **View recording**
   - Open: http://localhost:5001
   - You should see a new recording in "Completed" state

3. **Publish to WordPress**
   - Click on the recording
   - Click "Publish to WordPress"
   - Wait for success message

4. **View WordPress Post**
   - Open: http://localhost:8080
   - You should see your published post with plots!

---

## Troubleshooting

### "Application Passwords not available"

WordPress requires HTTPS for Application Passwords in production, but allows HTTP for localhost.

If you see this error:
- Make sure you're accessing via http://localhost:8080 (not 127.0.0.1)
- Check WordPress is version 5.6 or newer

### "Authentication failed"

Check:
```bash
# 1. Verify .env has the password
cat .env | grep WP_APP_PASSWORD

# 2. Verify event_recorder can reach WordPress
docker exec test_event_recorder ping -c 3 wordpress

# 3. Check event_recorder logs
docker logs test_event_recorder | grep -i wordpress
```

### "Connection refused"

WordPress might still be starting:
```bash
# Check WordPress logs
docker logs test_wordpress

# Wait 30 seconds and try again
sleep 30
curl http://localhost:8080
```

### Reset Everything

If something goes wrong:
```bash
# Stop and remove everything (including data!)
docker-compose down -v

# Start fresh
docker-compose up -d

# Wait for MySQL to initialize
sleep 30

# Complete WordPress setup again
open http://localhost:8080
```

---

## WordPress Admin Quick Links

- **Dashboard**: http://localhost:8080/wp-admin
- **Posts**: http://localhost:8080/wp-admin/edit.php
- **Media Library**: http://localhost:8080/wp-admin/upload.php
- **Users**: http://localhost:8080/wp-admin/users.php
- **Profile** (App Passwords): http://localhost:8080/wp-admin/profile.php

---

## Important Notes

⚠️ **This is a TEST environment**
- Default passwords are weak
- MySQL and WordPress data is stored in Docker volumes
- Running `docker-compose down -v` will DELETE ALL DATA
- Use `docker-compose down` (without `-v`) to keep data

🔒 **Security**
- Don't expose ports 8080/5001/1883 to the internet
- Change passwords before production use
- Application Passwords can be revoked individually from WordPress admin

📁 **Data Locations**
- Recordings: `./data/`
- WordPress: Docker volume `wordpress-data`
- Database: Docker volume `mysql-data`
- MQTT: Docker volume `mosquitto-data`
