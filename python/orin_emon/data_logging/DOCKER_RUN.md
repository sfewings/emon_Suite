# Running orin_emon.py in Docker on NVIDIA Orin

## Build

```bash
docker build -t orin-emon .
```

## Run

```bash
docker run -d \
  --name orin-emon \
  --restart unless-stopped \
  --privileged \
  -e SERIAL_PORT=/dev/ttyUSB1 \
  -v /sys:/sys:ro \
  -v /home/terra15/data_logging/logs:/data/logs \
  --device /dev/ttyUSB1 \
  orin-emon
```

## Docker Compose

A `docker-compose.yml` file is available for easier container management. To use it:

```bash
docker-compose up -d
```

The compose file contains the same configuration as the `docker run` command above. Edit `docker-compose.yml` to override environment variables like `SERIAL_PORT`, `LOG_DIR`, or `INTERVAL`:

```yaml
services:
  orin-emon:
    environment:
      SERIAL_PORT: /dev/ttyUSB1
      LOG_DIR: /data/logs
      INTERVAL: 5
```

To stop the container:

```bash
docker-compose down
```

## Environment Variables

| Variable      | Default         | Description                        |
|---------------|-----------------|------------------------------------|
| `SERIAL_PORT` | `/dev/ttyUSB0`  | Serial port for packet output      |
| `LOG_DIR`     | `/data/logs`    | Directory for daily CSV log files  |
| `INTERVAL`    | `5`             | Sensor query interval (seconds)    |

Override any variable with `-e`:

```bash
docker run -d \
  --name orin-emon \
  --restart unless-stopped \
  --privileged \
  -v /sys:/sys:ro \
  -v /home/nvidia/StephenFewings/logs:/data/logs \
  --device /dev/ttyUSB0 \
  -e SERIAL_PORT=/dev/ttyTHS0 \
  -e LOG_DIR=/data/logs \
  -e INTERVAL=10 \
  orin-emon
```

## Notes

- **`--privileged`** is required so the container can read `/sys/class/thermal` and `/sys/class/hwmon` sensor files.
- **`-v /sys:/sys:ro`** bind-mounts the host sysfs read-only into the container so the Python script can discover thermal zones and INA3221 power rails.
- **`--device /dev/ttyUSB0`** passes the serial device through to the container. Change this if your serial adapter uses a different device node.
- **`-v .../logs:/data/logs`** persists the daily CSV log files on the host. Adjust the host path as needed.
- To run without serial output (logging only), change the CMD by appending `--no-serial` or override it: `docker run ... orin-emon python3 orin_emon.py --log-dir /data/logs --no-serial --verbose`

## Stop / Remove

```bash
docker stop orin-emon
docker rm orin-emon
```

## View Logs

```bash
docker logs -f orin-emon
```
