import argparse
import datetime
import time
import os


DEFAULT_SERIAL_PORT = "/dev/ttyUSB0"
DEFAULT_BAUD_RATE = 9600


def writeLog(logPath, line):
    """Write log message with timestamp"""
    current_time = datetime.datetime.now()
    logLine = f"{current_time.strftime('%d/%m/%Y %H:%M:%S')},{line}"
    print(logLine)
    if os.path.exists(logPath):
        filePath = f"{logPath}/{current_time.strftime('%Y%m%d_emonCSVToSerial.TXT')}"
        with open(filePath, "a+", encoding='utf-8') as f:
            f.write(logLine)
            f.write('\n')


def parse_timestamp(timestamp_str):
    """Parse timestamp string in format DD/MM/YYYY HH:MM:SS"""
    return datetime.datetime.strptime(timestamp_str, '%d/%m/%Y %H:%M:%S')


def parse_offset(offset_str):
    """Parse offset string in H:MM or HH:MM format. Returns timedelta."""
    parts = offset_str.split(':')
    if len(parts) != 2:
        raise ValueError(f"Invalid offset format '{offset_str}'. Expected H:MM or HH:MM")
    hours = int(parts[0])
    minutes = int(parts[1])
    return datetime.timedelta(hours=hours, minutes=minutes)


def open_serial(port, baud):
    """Open a serial port. Returns the serial object or None."""
    try:
        import serial
        ser = serial.Serial(port, baud, timeout=1)
        return ser
    except ImportError:
        print("WARNING: pyserial not installed. Install with: pip install pyserial")
        print("         Serial output disabled.")
        return None
    except Exception as e:
        print(f"WARNING: Cannot open serial port {port}: {e}")
        print("         Serial output disabled.")
        return None


def send_packet(ser, packet_str):
    """Send a text packet over the serial port."""
    if ser is None:
        return False
    try:
        ser.write((packet_str + "\n").encode("ascii"))
        return True
    except Exception as e:
        print(f"Serial write error: {e}")
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Read CSV log file and replay to serial port")
    parser.add_argument("-f", "--file", help="Path to CSV input file", required=True)
    parser.add_argument("-l", "--logPath", help="Path to log directory",
                        default="/share/Output/emonCSVToSerial")
    parser.add_argument("-p", "--port", type=str, default=DEFAULT_SERIAL_PORT,
                        help=f"Serial port (default: {DEFAULT_SERIAL_PORT})")
    parser.add_argument("-b", "--baud", type=int, default=DEFAULT_BAUD_RATE,
                        help=f"Baud rate (default: {DEFAULT_BAUD_RATE})")
    parser.add_argument("-x", "--speed", type=float, default=1.0,
                        help="Playback speed multiplier (e.g. 10 = 10x faster, 0.5 = half speed, default: 1.0)")
    parser.add_argument("-o", "--offset", type=str, default=None,
                        help="Start offset in H:MM or HH:MM format, skipping that duration into the file (e.g. 1:10)")
    args = parser.parse_args()

    if args.speed <= 0:
        print("Error: --speed must be greater than 0")
        exit(1)

    start_offset = None
    if args.offset is not None:
        try:
            start_offset = parse_offset(args.offset)
        except ValueError as e:
            print(f"Error: {e}")
            exit(1)

    csvFile = str(args.file)
    logPath = str(args.logPath)

    writeLog(logPath, f"Starting emonCSVToSerial with file: {csvFile}, port: {args.port}, baud: {args.baud}, speed: {args.speed}x" +
             (f", offset: {args.offset}" if args.offset else ""))

    # Open serial port
    ser = open_serial(args.port, args.baud)
    if ser:
        writeLog(logPath, f"Opened serial port {args.port} @ {args.baud} baud")
    else:
        writeLog(logPath, f"Error opening serial port {args.port}")
        exit(1)

    # Read and process CSV file
    try:
        with open(csvFile, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        if not lines:
            writeLog(logPath, "CSV file is empty")
            exit(1)

        previous_timestamp = None
        first_timestamp = None

        for line_num, line in enumerate(lines, 1):
            line = line.rstrip('\r\n')
            if not line.strip():
                continue

            try:
                # Parse the line: timestamp,device_name,data...:RSSI
                parts = line.split(',', 2)

                if len(parts) < 3:
                    writeLog(logPath, f"Line {line_num}: Invalid format - {line}")
                    continue

                timestamp_str = parts[0]
                device_data = parts[1] + ',' + parts[2]

                # Parse timestamp
                current_timestamp = parse_timestamp(timestamp_str)

                # Record the first timestamp in the file for offset calculation
                if first_timestamp is None:
                    first_timestamp = current_timestamp

                # Skip lines until we reach the start offset
                if start_offset is not None:
                    if current_timestamp - first_timestamp < start_offset:
                        continue
                    elif previous_timestamp is None:
                        writeLog(logPath, f"Offset reached at line {line_num} ({timestamp_str}), starting playback")

                # If not the first line played, wait for the time difference (adjusted for speed)
                if previous_timestamp is not None:
                    time_diff = (current_timestamp - previous_timestamp).total_seconds()
                    if time_diff > 0:
                        adjusted = time_diff / args.speed
                        writeLog(logPath, f"Waiting {adjusted:.2f} seconds before processing next line")
                        time.sleep(adjusted)
                    elif time_diff < 0:
                        writeLog(logPath, f"Warning: Line {line_num} has earlier timestamp than previous line")

                writeLog(logPath, f"Sending: {device_data}")
                if send_packet(ser, device_data):
                    writeLog(logPath, f"Sent OK")
                else:
                    writeLog(logPath, f"Line {line_num}: Failed to send")

                previous_timestamp = current_timestamp

            except ValueError as e:
                writeLog(logPath, f"Line {line_num}: Error parsing line - {str(e)}")
                writeLog(logPath, f"  Line content: {line}")
                continue
            except Exception as e:
                writeLog(logPath, f"Line {line_num}: Unexpected error - {str(e)}")
                writeLog(logPath, f"  Line content: {line}")
                continue

        writeLog(logPath, f"Successfully processed {len(lines)} lines from {csvFile}")

    except FileNotFoundError:
        writeLog(logPath, f"Error: CSV file not found - {csvFile}")
        exit(1)
    except Exception as e:
        writeLog(logPath, f"Error reading CSV file: {str(e)}")
        exit(1)
    finally:
        if ser:
            ser.close()

    writeLog(logPath, "emonCSVToSerial completed successfully")
