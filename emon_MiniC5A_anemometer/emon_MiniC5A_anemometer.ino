// Mini-C5A Modbus RTU reader - reads 5 registers starting at 0x0000 from slave addr 0x01
// Parses registers (0..4) into windSpeed, windDirection, temperature, humidity, pressure.
// Adjust scaling constants to match your sensor's register scaling.
#include <SoftwareSerial.h>

#include <EmonShared.h>
#include <RH_RF69.h>
#include <Wire.h>

//#define HOME_NETWORK
#define BOAT_NETWORK
#ifdef BOAT_NETWORK
	#define NETWORK_FREQUENCY 914.0
#elif defined( HOME_NETWORK )
	#define NETWORK_FREQUENCY 915.0
#endif

const uint8_t MOTEINO_LED = 9;	// LED on Moteino
SoftwareSerial g_rs232Serial(3,4); // rx, tx

const unsigned long BAUD_RS232 = 9600;  // Mini-C5A RS232 baud

const uint8_t MODBUS_ADDR = 0x01;
const uint8_t MODBUS_FN_READ = 0x03;
const uint16_t MODBUS_REG_START = 0x0000;
const uint16_t MODBUS_REG_COUNT = 5;

const unsigned long SEND_WIND_INTERVAL_MS = 1000; // ms
const unsigned long RESPONSE_TIMEOUT = 500;  // ms
const unsigned long SEND_PRESSURE_INTERVAL_MS = 5000; // send pressure data at least every 5 seconds

// scaling as in the Mini C5A datasheet
const float SCALE_WIND_SPEED = 0.01f; // register value * 0.01 -> m/s
const float SCALE_MPS_TO_KNOTS = 1.94384449; //metres per second to knots
const float SCALE_WIND_DIR   = 1.0f; // degrees
const float SCALE_TEMPERATURE= 0.1f; // degC
const float SCALE_HUMIDITY   = 0.1f; // %RH
const float SCALE_PRESSURE   = 0.1f; // hPa or other unit

// I2C addresses
#define ADDR_MPU6050 0x68
#define ADDR_HMC5883L 0x1E
#define ADDR_MS5611 0x77 // or 0x76 depending on module

// MPU6050 registers
#define MPU_PWR_MGMT_1   0x6B
#define MPU_ACCEL_XOUT_H 0x3B
#define MPU_WHO_AM_I     0x75
#define MPU_INT_PIN_CFG  0x37  // INT pin / BYPASS config

// HMC5883L registers
#define HMC_CONFIG_A 0x00
#define HMC_CONFIG_B 0x01
#define HMC_MODE     0x02
#define HMC_DATA_X_MSB 0x03
#define HMC_ID_A 0x0A

// MS5611 commands
#define MS5611_CMD_RESET 0x1E
#define MS5611_CMD_PROM_READ 0xA0 // +2*n
#define MS5611_CMD_CONV_D1 0x40   // pressure OSR=4096
#define MS5611_CMD_CONV_D2 0x50   // temperature OSR=4096
#define MS5611_CMD_ADC_READ 0x00

// scaling constants
const float MPU_ACCEL_SCALE = 16384.0f; // LSB/g for ±2g
const float MPU_GYRO_SCALE = 131.0f;    // LSB/(deg/s) for ±250deg/s
// Degrees the sensor board's X axis is rotated clockwise from the boat's centreline.
// Subtracted from the computed heading. Measured from the Enchantee_20260816 log:
// over 5799 steady straight-line samples spanning all 36 ten-degree heading bins the
// compass read a constant 11.9 deg high against GPS course over ground.
const int INSTALATION_HEADING_OFFSET = 12;

// Degrees the anemometer's zero mark is rotated clockwise from the boat's centreline.
// Subtracted from the vane angle before it is combined with the heading, so it shifts
// apparent and true wind direction without touching the boat-relative reading (subnode 0).
// The 20260816 log puts this within about +-10 deg of zero, so it is left at 0; this is
// the knob to trim if a residual tack-to-tack true-wind-direction split reappears.
const int ANEMOMETER_HEADING_OFFSET = 0;

float GyroOffset[3] = {-693.9f, -62.5f, -40.3f};


// VERY IMPORTANT!
//These are the previously determined offsets and scale factors for accelerometer and magnetometer, using ICM_20948_cal and Magneto
//The compass will NOT work well or at all if these are not correct

//Accel scale: divide by 16604.0 to normalize. These corrections are quite small and probably can be ignored.
float A_B [3] = {1152.16, -1208.87, 1895.63};


float A_Ainv[3][3] = {
{ 0.06165, 0.0015, 0.00235 },
{ 0.0015, 0.05959, -0.00639 },
{ 0.00235, -0.00639, 0.05417 }};;

//Mag scale divide by 369.4 to normalize. These are significant corrections, especially the large offsets.
// M_B updated from the Enchantee_20260816 afternoon log. The bench sweep that produced
// {107.82, -122.78, 5.68} was done off the boat, so it contained none of the boat's own
// hard iron; in service the residual bias was 7.5% of full field (about 17 raw LSB).
// Leaving it uncorrected caused a 13.1 deg one-cycle compass error and, through it, a
// 7.1 deg tack-to-tack split in true wind direction. See calculateTrueWind() below.
float M_B [3] = {100.98, -105.97, 5.85};


float M_Ainv[3][3] = {
{ 4.27479, 0.01328, 0.00683 },
{ 0.01328, 4.28946, -0.05025 },
{ 0.00683, -0.05025, 5.32997 }};


// local magnetic declination in degrees
float declination = -1.5;  // Perth, Western Australia

float p[] = {1, 0, 0};  //X marking on sensor board points toward yaw = 0

//Anemometer readings as received from MiniC5A
struct AnemometerReadings {
    float windSpeed = NAN;
    float windDirection = NAN;
    float temperature = NAN;
    float humidity = NAN;
    float pressure = NAN;
};

PayloadPressure g_payloadPressure;
PayloadAnemometer g_payloadAnemometer;
PayloadGPS g_payloadGPS;
PayloadIMU g_payloadIMU;

RH_RF69 g_rf69;


////////////////////////////////////////////////
struct TrueWind {
  float tws;   // True Wind Speed
  float twd;   // True Wind Direction (FROM)
};

// A tack-to-tack split in true wind direction (the same breeze reading differently on
// port and starboard) is NOT fixed in here. This function is exact given its inputs, and
// because it uses velocity over ground from GPS, leeway cancels out of it entirely.
// A split means one of the two inputs that flip sense with tack is wrong:
//   - the compass  -> fix M_B / INSTALATION_HEADING_OFFSET above
//   - the vane zero -> fix ANEMOMETER_HEADING_OFFSET above
// On the 20260816 log the split was 7.1 deg and came from the compass; correcting M_B
// took it to 0.05 deg. Resist adding an empirical fudge factor here - it would hide a
// compass fault that also corrupts the heading and apparent wind outputs.
TrueWind calculateTrueWind(float aws, float awd, float sog, float hdg) {
  // Convert degrees to radians
  auto deg2rad = [](float d) { return d * PI / 180.0; };
  auto rad2deg = [](float r) { return r * 180.0 / PI; };

  float awdRad = deg2rad(awd);
  float hdgRad = deg2rad(hdg);

  // Apparent wind vector (coming FROM awd)
  float awx = aws * sin(awdRad);
  float awy = aws * cos(awdRad);

  // Vessel motion vector (moving TOWARD hdg)
  float vx = sog * sin(hdgRad);
  float vy = sog * cos(hdgRad);

  // True wind (FROM) = apparent wind (FROM) - vessel motion (TOWARD)
  float twx = awx - vx;
  float twy = awy - vy;

  // Convert back to polar
  float tws = sqrt(twx * twx + twy * twy);
  float twd = rad2deg(atan2(twx, twy));

  // Normalize to 0–360°
  if (twd < 0) 
    twd += 360.0;

  TrueWind result;
  result.tws = tws;
  result.twd = twd;
  return result;
}



void writeRegister(uint8_t addr, uint8_t reg, uint8_t val) {
  Wire.beginTransmission(addr);
  Wire.write(reg);
  Wire.write(val);
  Wire.endTransmission();
}

bool readRegisters(uint8_t addr, uint8_t reg, uint8_t *buf, uint8_t len) {
  Wire.beginTransmission(addr);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return false;
  uint8_t got = Wire.requestFrom((int)addr, (int)len);
  if (got != len) return false;
  for (uint8_t i = 0; i < len; ++i) buf[i] = Wire.read();
  return true;
}

int16_t readS16(uint8_t addr, uint8_t regHigh) {
  uint8_t b[2];
  if (!readRegisters(addr, regHigh, b, 2)) return 0;
  return (int16_t)((b[0] << 8) | b[1]);
}

uint32_t readU24(uint8_t addr, uint8_t reg) {
  // for MS5611 ADC read (3 bytes) after issuing ADC read command
  uint8_t b[3];
  if (!readRegisters(addr, reg, b, 3)) return 0;
  return ((uint32_t)b[0] << 16) | ((uint32_t)b[1] << 8) | b[2];
}

void ms5611Reset() {
  Wire.beginTransmission(ADDR_MS5611);
  Wire.write(MS5611_CMD_RESET);
  Wire.endTransmission();
  delay(3);
}

uint16_t ms5611ReadProm(int index) {
  uint8_t b[2];
  uint8_t cmd = MS5611_CMD_PROM_READ + (index * 2);
  if (!readRegisters(ADDR_MS5611, cmd, b, 2)) return 0;
  return (uint16_t)(b[0] << 8) | b[1];
}

uint32_t ms5611ConvertRead(uint8_t convCmd) {
  Wire.beginTransmission(ADDR_MS5611);
  Wire.write(convCmd);
  Wire.endTransmission();
  // OSR=4096 conversion time ~9-10 ms
  delay(10);
  // read ADC
  Wire.beginTransmission(ADDR_MS5611);
  Wire.write(MS5611_CMD_ADC_READ);
  Wire.endTransmission();
  uint8_t b[3];
  if (!readRegisters(ADDR_MS5611, MS5611_CMD_ADC_READ, b, 3)) return 0;
  return ((uint32_t)b[0] << 16) | ((uint32_t)b[1] << 8) | b[2];
}

bool initMPU6050() {
  // wake up
  writeRegister(ADDR_MPU6050, MPU_PWR_MGMT_1, 0x00);
  delay(10);
  uint8_t who = 0;
  if (!readRegisters(ADDR_MPU6050, MPU_WHO_AM_I, &who, 1)) return false;
  if (who != 0x68) return false;

  // Enable I2C bypass so the HMC5883L (on the MPU6050 AUX I2C/SCL/SDA)
  // can be accessed directly on the main I2C bus.
  // Set BIT1 (I2C_BYPASS_EN) in INT_PIN_CFG (0x37).
  uint8_t int_cfg = 0;
  if (readRegisters(ADDR_MPU6050, MPU_INT_PIN_CFG, &int_cfg, 1)) {
    int_cfg |= 0x02; // I2C_BYPASS_EN
    writeRegister(ADDR_MPU6050, MPU_INT_PIN_CFG, int_cfg);
    delay(10);
  }

  return true;
}

bool initHMC5883L() {
  // set to 8-average, 15 Hz, normal measurement
  writeRegister(ADDR_HMC5883L, HMC_CONFIG_A, 0x70);
  // gain = 1090 (recommended)
  writeRegister(ADDR_HMC5883L, HMC_CONFIG_B, 0xA0);
  // continuous measurement mode
  writeRegister(ADDR_HMC5883L, HMC_MODE, 0x00);
  delay(10);
  // check ID registers
  uint8_t id[3];
  if (!readRegisters(ADDR_HMC5883L, HMC_ID_A, id, 3)) return false;
  // Typical ID: 'H','4','3' or 'H','4','3' depending on variant; accept printable
  return (id[0] >= 0x20 && id[0] <= 0x7E);
}

bool initMS5611() 
{
    ms5611Reset();
  // read calibration
    uint16_t C[6];
    for (int i = 0; i < 6; i++) 
    {
        C[i] = 0;
    }
    for (int i = 0; i < 6; i++) 
    {
        C[i] = ms5611ReadProm(i+1);
    }
    // basic validity checks: non-zero coefficients
    for (int i = 0; i < 6; i++) 
    {
        if (C[i] == 0) 
            return false;
    }
    return true;
}

/////////////////////////////////////////////////
// Calibration data collection.  Originally from ICM_20948_get_cal_data.ino
// https://github.com/jremington/ICM_20948-AHRS
//
// Capture the whole serial session to a text file and feed it to calibrate4.py,
// which emits paste-ready GyroOffset, A_B, A_Ainv, M_B and M_Ainv blocks.
//
// The v3 routine logged the accelerometer while the sensor was being turned, so it
// recorded gravity plus hand movement. On the Enchantee_20260816 data set the median
// sample was 1.11 g and 59% were outside 1 g +-10%, which made the accelerometer
// ellipsoid fit meaningless. The accelerometer is therefore now sampled ONLY while
// the sensor is verifiably stationary, one discrete orientation at a time.
//
// The magnetometer is unaffected by movement, so it still uses a continuous sweep.
//
// The three phases are separately selectable because they happen in different places:
// the gyro and accelerometer phases need the unit in your hands on a bench, while the
// magnetometer sweep must be done with the unit mounted in its final position on the
// boat, otherwise it cannot capture the boat's own hard and soft iron.
//
// Every record is also broadcast on CALIBRATION_NODE as a PayloadCalibration, which
// emon_RaspPiSerial relays to its own serial port in the identical line format. That is
// what makes an in-situ magnetometer swing possible: the sensor can be up the mast with
// no serial cable and the capture still lands in a file at the Pi. (The v3 routine also
// broadcast on node 99, but nothing in the repo ever received those packets.)
//
// Define CAL_AUTOSTART_MAG before flashing a unit that will be swung with no serial
// cable attached - it skips the menu and sweeps on power-up.
//#define CAL_AUTOSTART_MAG

const uint8_t  CAL_ACC_POSITIONS   = 12;   // discrete orientations for the accelerometer
const uint16_t CAL_ACC_AVG         = 200;  // samples averaged at each orientation
const uint16_t CAL_GYRO_SAMPLES    = 500;  // samples averaged for the gyro offsets
const uint16_t CAL_MAG_SAMPLES     = 600;  // samples in the magnetometer sweep
const uint16_t CAL_MAG_INTERVAL_MS = 100;  // -> 60 s sweep
const uint8_t  CAL_STILL_WINDOW    = 25;   // samples examined when testing for stillness
const int16_t  CAL_STILL_PP        = 400;  // max peak-to-peak per axis to count as still (~0.024 g)
const uint16_t CAL_STILL_TIMEOUT_S = 30;   // give up waiting for stillness after this long

void readRawAcc(int16_t v[3])
{
    v[0] = readS16(ADDR_MPU6050, MPU_ACCEL_XOUT_H + 0);
    v[1] = readS16(ADDR_MPU6050, MPU_ACCEL_XOUT_H + 2);
    v[2] = readS16(ADDR_MPU6050, MPU_ACCEL_XOUT_H + 4);
}

void readRawGyro(int16_t v[3])
{
    v[0] = readS16(ADDR_MPU6050, MPU_ACCEL_XOUT_H + 8);
    v[1] = readS16(ADDR_MPU6050, MPU_ACCEL_XOUT_H + 10);
    v[2] = readS16(ADDR_MPU6050, MPU_ACCEL_XOUT_H + 12);
}

// Returns false if the HMC5883L did not answer. Note the on-the-wire order is X, Z, Y.
bool readRawMag(int16_t v[3])
{
    uint8_t b[6];
    if (!readRegisters(ADDR_HMC5883L, HMC_DATA_X_MSB, b, 6))
        return false;
    v[0] = (int16_t)((b[0] << 8) | b[1]);   // X
    v[2] = (int16_t)((b[2] << 8) | b[3]);   // Z
    v[1] = (int16_t)((b[4] << 8) | b[5]);   // Y
    return true;
}

// Broadcast one calibration record so emon_RaspPiSerial can relay it to serial.
// The caller has already set the radio header to CALIBRATION_NODE.
void calBroadcast(char phase, uint8_t index, const int16_t* v, uint8_t n)
{
    PayloadCalibration p;
    memset(&p, 0, sizeof(p));
    p.phase = (byte)phase;
    p.index = index;
    for (uint8_t i = 0; i < n && i < 9; i++)
        p.v[i] = v[i];
    g_rf69.send((const uint8_t*)&p, sizeof(p));
    g_rf69.waitPacketSent();
}

// Block until the operator sends any character. Discards anything already buffered so a
// stray newline from the previous prompt cannot skip this one.
void calWaitForKey()
{
    while (Serial.available())
        Serial.read();
    while (!Serial.available())
        delay(10);
    while (Serial.available())
        Serial.read();
}

void calPrintPositionName(uint8_t i)
{
    switch (i)
    {
        // The six axis-aligned faces pin down the bias and the per-axis scale.
        case 0:  Serial.print(F("FLAT, component side UP      (+Z up)")); break;
        case 1:  Serial.print(F("FLAT, UPSIDE DOWN            (-Z up)")); break;
        case 2:  Serial.print(F("on its side, +X edge UP      (+X up)")); break;
        case 3:  Serial.print(F("on its side, -X edge UP      (-X up)")); break;
        case 4:  Serial.print(F("on its side, +Y edge UP      (+Y up)")); break;
        case 5:  Serial.print(F("on its side, -Y edge UP      (-Y up)")); break;
        // Six tilted positions constrain the off-diagonal (cross-axis) terms.
        default: Serial.print(F("TILTED about 45 deg - any position, just different from the others"));
                 break;
    }
}

// Waits for the sensor to stop moving, then averages CAL_ACC_AVG accelerometer samples
// and one magnetometer sample set. Returns false if it never settled.
bool calCaptureStatic(int32_t accMean[3], int16_t accPP[3], int32_t magMean[3])
{
    int16_t a[3], lo[3], hi[3];
    bool still = false;

    for (uint16_t sec = 0; sec < CAL_STILL_TIMEOUT_S * 4 && !still; sec++)
    {
        readRawAcc(a);
        for (uint8_t k = 0; k < 3; k++)
            lo[k] = hi[k] = a[k];
        for (uint8_t s = 1; s < CAL_STILL_WINDOW; s++)
        {
            delay(10);
            readRawAcc(a);
            for (uint8_t k = 0; k < 3; k++)
            {
                if (a[k] < lo[k]) lo[k] = a[k];
                if (a[k] > hi[k]) hi[k] = a[k];
            }
        }
        still = true;
        for (uint8_t k = 0; k < 3; k++)
            if ((int32_t)hi[k] - (int32_t)lo[k] > CAL_STILL_PP)
                still = false;
    }
    if (!still)
        return false;

    int32_t sum[3] = {0, 0, 0};
    int32_t msum[3] = {0, 0, 0};
    uint16_t mcount = 0;
    readRawAcc(a);
    for (uint8_t k = 0; k < 3; k++)
        lo[k] = hi[k] = a[k];

    for (uint16_t s = 0; s < CAL_ACC_AVG; s++)
    {
        readRawAcc(a);
        for (uint8_t k = 0; k < 3; k++)
        {
            sum[k] += a[k];
            if (a[k] < lo[k]) lo[k] = a[k];
            if (a[k] > hi[k]) hi[k] = a[k];
        }
        if ((s % 8) == 0)
        {
            int16_t m[3];
            if (readRawMag(m))
            {
                for (uint8_t k = 0; k < 3; k++)
                    msum[k] += m[k];
                mcount++;
            }
        }
        delay(5);
    }
    for (uint8_t k = 0; k < 3; k++)
    {
        accMean[k] = sum[k] / (int32_t)CAL_ACC_AVG;
        // clamp: a bump mid-average can make this exceed an int16 and wrap negative,
        // which would sneak past the "was it still" check in calibrate4.py
        int32_t range = (int32_t)hi[k] - (int32_t)lo[k];
        accPP[k]   = (range > 32767) ? 32767 : (int16_t)range;
        magMean[k] = mcount ? msum[k] / (int32_t)mcount : 0;
    }
    return true;
}

void calGyroPhase()
{
    Serial.println(F("#BEGIN GYRO"));
    Serial.println(F("# Put the unit down on a solid surface and DO NOT TOUCH IT."));
    Serial.println(F("# Press any key when it is settled..."));
    calWaitForKey();
    Serial.println(F("# sampling..."));

    int16_t g[3], lo[3], hi[3];
    int32_t sum[3] = {0, 0, 0};
    readRawGyro(g);
    for (uint8_t k = 0; k < 3; k++)
        lo[k] = hi[k] = g[k];

    for (uint16_t i = 0; i < CAL_GYRO_SAMPLES; i++)
    {
        readRawGyro(g);
        for (uint8_t k = 0; k < 3; k++)
        {
            sum[k] += g[k];
            if (g[k] < lo[k]) lo[k] = g[k];
            if (g[k] > hi[k]) hi[k] = g[k];
        }
        delay(4);
    }
    // G,<mean x>,<mean y>,<mean z>,<peak-to-peak x>,<pp y>,<pp z>,<n>
    // The means go over RF scaled by 10 so the one decimal place survives an int16.
    int16_t rec[7];
    Serial.print(F("G"));
    for (uint8_t k = 0; k < 3; k++)
    {
        float mean = (float)sum[k] / CAL_GYRO_SAMPLES;
        // clamp so the x10 encoding cannot silently wrap an int16. A real MPU6050 zero
        // rate offset is within +-20 deg/s (~2620 LSB), so hitting this means a fault.
        float scaled = mean * 10.0;
        if (scaled > 32767.0)  scaled = 32767.0;
        if (scaled < -32768.0) scaled = -32768.0;
        rec[k] = (int16_t)scaled;
        Serial.print(F(","));
        Serial.print(mean, 1);
    }
    for (uint8_t k = 0; k < 3; k++)
    {
        rec[3 + k] = hi[k] - lo[k];
        Serial.print(F(","));
        Serial.print(hi[k] - lo[k]);
    }
    rec[6] = CAL_GYRO_SAMPLES;
    Serial.print(F(","));
    Serial.println(CAL_GYRO_SAMPLES);
    calBroadcast('G', 0, rec, 7);
    Serial.println(F("#END GYRO"));
}

void calAccPhase()
{
    Serial.println(F("#BEGIN ACC"));
    Serial.println(F("# Hold the unit STILL in each orientation. It waits until it stops"));
    Serial.println(F("# moving before it samples, so resting it against something helps."));
    Serial.println(F("# The magnetometer is logged here too, for the dip cross-check."));

    for (uint8_t i = 0; i < CAL_ACC_POSITIONS; i++)
    {
        Serial.print(F("# position "));
        Serial.print(i + 1);
        Serial.print(F(" of "));
        Serial.print(CAL_ACC_POSITIONS);
        Serial.print(F(": "));
        calPrintPositionName(i);
        Serial.println();
        Serial.println(F("# place it, let go, then press any key..."));
        calWaitForKey();

        int32_t acc[3], mag[3];
        int16_t pp[3];
        digitalWrite(MOTEINO_LED, HIGH);
        bool ok = calCaptureStatic(acc, pp, mag);
        digitalWrite(MOTEINO_LED, LOW);

        if (!ok)
        {
            Serial.println(F("# NOT STILL - never settled, position skipped. Try again."));
            i--;                     // repeat this position
            continue;
        }
        // A,<pos>,<ax>,<ay>,<az>,<mx>,<my>,<mz>,<ppx>,<ppy>,<ppz>
        int16_t rec[9];
        for (uint8_t k = 0; k < 3; k++)
        {
            rec[k]     = (int16_t)acc[k];
            rec[3 + k] = (int16_t)mag[k];
            rec[6 + k] = pp[k];
        }
        Serial.print(F("A,"));
        Serial.print(i);
        for (uint8_t k = 0; k < 9; k++)
        {
            Serial.print(F(","));
            Serial.print(rec[k]);
        }
        Serial.println();
        calBroadcast('A', i, rec, 9);
    }
    Serial.println(F("#END ACC"));
}

void calMagPhase(bool prompt)
{
    Serial.println(F("#BEGIN MAG"));
    Serial.println(F("# Mount the unit where it normally lives, then turn the BOAT slowly"));
    Serial.println(F("# through at least two full circles, rocking it if you can."));
    Serial.println(F("# On the bench instead, turn the unit slowly about all three axes."));
    Serial.print(F("# This takes "));
    Serial.print((uint16_t)((uint32_t)CAL_MAG_SAMPLES * CAL_MAG_INTERVAL_MS / 1000));
    Serial.println(F(" seconds."));
    if (prompt)
    {
        Serial.println(F("# Press any key to start..."));
        calWaitForKey();
    }
    else
    {
        // no serial cable: give the operator time to get to the helm
        Serial.println(F("# autostart, beginning in 30 s..."));
        for (uint8_t s = 0; s < 30; s++)
        {
            digitalWrite(MOTEINO_LED, (s & 1) ? HIGH : LOW);
            delay(1000);
        }
    }
    Serial.println(F("# sweeping..."));

    for (uint16_t i = 0; i < CAL_MAG_SAMPLES; i++)
    {
        int16_t m[3];
        if (readRawMag(m))
        {
            // M,<mx>,<my>,<mz>
            Serial.print(F("M,"));
            Serial.print(m[0]);
            Serial.print(F(","));
            Serial.print(m[1]);
            Serial.print(F(","));
            Serial.println(m[2]);
            calBroadcast('M', (uint8_t)(i & 0xFF), m, 3);
        }
        if ((i % 50) == 0)
        {
            Serial.print(F("# "));
            Serial.print(i);
            Serial.print(F("/"));
            Serial.println(CAL_MAG_SAMPLES);
            digitalWrite(MOTEINO_LED, HIGH);
        }
        else
        {
            digitalWrite(MOTEINO_LED, LOW);
        }
        delay(CAL_MAG_INTERVAL_MS);
    }
    Serial.println(F("#END MAG"));
}

void collectDataForMahonyCalibration()
{
    Serial.println();
    Serial.println(F("#EMON_CAL,4"));
    Serial.println(F("# emon_MiniC5A_anemometer calibration capture"));
    Serial.println(F("# Save this whole session to a file and run:  python calibrate4.py <file>"));
    Serial.println(F("# Records are also broadcast to CALIBRATION_NODE; emon_RaspPiSerial"));
    Serial.println(F("# relays them to serial in the same format if no cable is attached."));

    // everything below transmits as the calibration node, not the anemometer
    g_rf69.setHeaderId(CALIBRATION_NODE);

#ifdef CAL_AUTOSTART_MAG
    calMagPhase(false);
    Serial.println(F("#DONE"));
    g_rf69.setHeaderId(ANEMOMETER_NODE);
    return;
#endif

    while (true)
    {
        Serial.println();
        Serial.println(F("# ---- choose a phase ----"));
        Serial.println(F("#  1 = gyro offsets      (bench, unit still)"));
        Serial.println(F("#  2 = accelerometer     (bench, 12 static orientations)"));
        Serial.println(F("#  3 = magnetometer      (in situ, slow sweep)"));
        Serial.println(F("#  4 = all three in order"));
        Serial.println(F("#  0 = done, restart the sketch normally"));
        Serial.println(F("# send the digit..."));

        while (Serial.available())
            Serial.read();
        while (!Serial.available())
            delay(10);
        char c = Serial.read();
        while (Serial.available())
            Serial.read();

        switch (c)
        {
            case '1': calGyroPhase(); break;
            case '2': calAccPhase();  break;
            case '3': calMagPhase(true);  break;
            case '4': calGyroPhase(); calAccPhase(); calMagPhase(true); break;
            case '0':
                Serial.println(F("#DONE"));
                g_rf69.setHeaderId(ANEMOMETER_NODE);
                return;
            default:
                Serial.println(F("# unrecognised, try again"));
                break;
        }
    }
}

// Routine to call to output on serial to wireFrame.py or wireFramePitchRollYaw.py. 
// Be sure to set baud rate to 115200
void DoPitchRollYawLoop()
{
    static float Axyz[3], Mxyz[3]; //centered and scaled accel/mag data
    static unsigned long lastPrint = millis();
    Serial.println(F("Output for external pitch, roll, yaw display"));
    Serial.println(F("ax(g), ay(g), az(g), mag_x, mag_y, mag_z, heading, loop_time_ms"));

    //if (millis() - lastPrint > 50)
    while(true)
    {
        get_scaled_IMU(Axyz, Mxyz);  //apply relative scale and offset to RAW data. UNITS are not important

        Serial.print(Axyz[0]);
        Serial.print(", ");
        Serial.print(Axyz[1]);
        Serial.print(", ");
        Serial.print(Axyz[2]);
        Serial.print(", ");
        Serial.print(Mxyz[0]);
        Serial.print(", ");
        Serial.print(Mxyz[1]);
        Serial.print(", ");
        Serial.print(Mxyz[2]);
        //  get heading in degrees
        Serial.print(", ");
        Serial.print(get_heading(Axyz, Mxyz, p, declination));
        Serial.print(", ");
        Serial.print(millis()-lastPrint);
        Serial.println();
        lastPrint = millis(); // Update lastPrint time
    }
    // consider averaging a few headings for better results
}


//read temperature and pressure from the MS5611
void get_temperature_pressure(float &temperature, float &pressure_hPa)
{
    // MS5611: get calibration values
    // read D1 (pressure) and D2 (temperature) and compute temperature and pressure
    uint16_t C[6];
    for (int i = 0; i < 6; i++) 
    {
        C[i] = ms5611ReadProm(i+1);
    }

    uint32_t D1 = ms5611ConvertRead(MS5611_CMD_CONV_D1);
    uint32_t D2 = ms5611ConvertRead(MS5611_CMD_CONV_D2);
    temperature = NAN;
    pressure_hPa = NAN;
    if (D1 != 0 && D2 != 0) 
    {
        // from MS5611 datasheet
        int64_t dT = (int64_t)D2 - ((int64_t)C[4] * 256LL);
        int64_t TEMP = 2000 + (dT * (int64_t)C[5]) / 8388608LL;
        int64_t OFF = ((int64_t)C[1] * 65536LL) + (((int64_t)C[3] * dT) / 128LL);
        int64_t SENS = ((int64_t)C[0] * 32768LL) + (((int64_t)C[2] * dT) / 256LL);

        // second order compensation
        int64_t T2 = 0, OFF2 = 0, SENS2 = 0;
        if (TEMP < 2000) 
        {
            T2 = (dT * dT) >> 31;
            OFF2 = 5 * ((TEMP - 2000) * (TEMP - 2000)) >> 1;
            SENS2 = 5 * ((TEMP - 2000) * (TEMP - 2000)) >> 2;
            if (TEMP < -1500) 
            {
                OFF2 += 7 * ((TEMP + 1500) * (TEMP + 1500));
                SENS2 += ((11 * ((TEMP + 1500) * (TEMP + 1500))) >> 1);
            }
        }
        TEMP -= T2;
        OFF -= OFF2;
        SENS -= SENS2;

        int64_t P = (((int64_t)D1 * SENS) / 2097152LL - OFF) / 32768LL;
        temperature = (float)TEMP / 100.0f;
        pressure_hPa = (float)P / 100.0f; // convert Pa->hPa if P is in Pa (datasheet units)
    }
}

//////////////////////////////
// basic vector operations
void vector_cross(float a[3], float b[3], float out[3])
{
  out[0] = a[1] * b[2] - a[2] * b[1];
  out[1] = a[2] * b[0] - a[0] * b[2];
  out[2] = a[0] * b[1] - a[1] * b[0];
}

float vector_dot(float a[3], float b[3])
{
  return a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
}

void vector_normalize(float a[3])
{
  float mag = sqrt(vector_dot(a, a));
  a[0] /= mag;
  a[1] /= mag;
  a[2] /= mag;
}
////////////////////////////////////


// Returns a heading (in degrees) given an acceleration vector a due to gravity, a magnetic vector m, and a facing vector p.
// applies magnetic declination
int get_heading(float acc[3], float mag[3], float p[3], float magdec)
{
  float W[3], N[3]; //derived direction vectors

  // cross "Up" (acceleration vector, g) with magnetic vector (magnetic north + inclination) with  to produce "West"
  vector_cross(acc, mag, W);
  vector_normalize(W);

  // cross "West" with "Up" to produce "North" (parallel to the ground)
  vector_cross(W, acc, N);
  vector_normalize(N);

  // compute heading in horizontal plane, correct for local magnetic declination in degrees

  float h = -atan2(vector_dot(W, p), vector_dot(N, p)) * 180 / M_PI; //minus: conventional nav, heading increases North to East
  int heading = round(h + magdec) - INSTALATION_HEADING_OFFSET;
  heading = (heading + 720) % 360; //apply compass wrap
  return heading;
}

void get_gyro(float Gxyz[3]) 
{
  int16_t gx = readS16(ADDR_MPU6050, MPU_ACCEL_XOUT_H + 8);
  int16_t gy = readS16(ADDR_MPU6050, MPU_ACCEL_XOUT_H +10);
  int16_t gz = readS16(ADDR_MPU6050, MPU_ACCEL_XOUT_H +12);

  // GyroOffset holds the MEAN of the raw readings taken while the sensor was held
  // still by collectDataForMahonyCalibration(), so it must be SUBTRACTED. Adding it
  // doubled the bias instead of removing it.
  Gxyz[0] = (float)gx - GyroOffset[0];
  Gxyz[1] = (float)gy - GyroOffset[1];
  Gxyz[2] = (float)gz - GyroOffset[2];
}

// subtract offsets and correction matrix to accel and mag data

void get_scaled_IMU(float Axyz[3], float Mxyz[3]) {
  byte i;
  float temp[3];

  int16_t ax = readS16(ADDR_MPU6050, MPU_ACCEL_XOUT_H + 0);
  int16_t ay = readS16(ADDR_MPU6050, MPU_ACCEL_XOUT_H + 2);
  int16_t az = readS16(ADDR_MPU6050, MPU_ACCEL_XOUT_H + 4);

  uint8_t magBuf[6];
  readRegisters(ADDR_HMC5883L, HMC_DATA_X_MSB, magBuf, 6);
  int16_t mX = (int16_t)((magBuf[0] << 8) | magBuf[1]);
  int16_t mZ = (int16_t)((magBuf[2] << 8) | magBuf[3]);
  int16_t mY = (int16_t)((magBuf[4] << 8) | magBuf[5]);

  Axyz[0] = ax;
  Axyz[1] = ay;
  Axyz[2] = az;
  Mxyz[0] = mX;
  Mxyz[1] = mY;
  Mxyz[2] = mZ;
  //apply offsets (bias) and scale factors from Magneto
  for (i = 0; i < 3; i++) temp[i] = (Axyz[i] - A_B[i]);
  Axyz[0] = A_Ainv[0][0] * temp[0] + A_Ainv[0][1] * temp[1] + A_Ainv[0][2] * temp[2];
  Axyz[1] = A_Ainv[1][0] * temp[0] + A_Ainv[1][1] * temp[1] + A_Ainv[1][2] * temp[2];
  Axyz[2] = A_Ainv[2][0] * temp[0] + A_Ainv[2][1] * temp[1] + A_Ainv[2][2] * temp[2];
  vector_normalize(Axyz);

  //apply offsets (bias) and scale factors from Magneto
  for (int i = 0; i < 3; i++) temp[i] = (Mxyz[i] - M_B[i]);
  Mxyz[0] = M_Ainv[0][0] * temp[0] + M_Ainv[0][1] * temp[1] + M_Ainv[0][2] * temp[2];
  Mxyz[1] = M_Ainv[1][0] * temp[0] + M_Ainv[1][1] * temp[1] + M_Ainv[1][2] * temp[2];
  Mxyz[2] = M_Ainv[2][0] * temp[0] + M_Ainv[2][1] * temp[1] + M_Ainv[2][2] * temp[2];
  vector_normalize(Mxyz);
}


/////////////////////////////////////////////////
// MiniC5 anemometer routines

void flashErrorToLED(int error, bool haltExecution = false)
{
  do
  { 
    for( int i = 0; i < error; i++)
    {
      digitalWrite(MOTEINO_LED, HIGH);
      delay(300);
      digitalWrite(MOTEINO_LED, LOW);
      delay(200);
    }
	delay(1000);
  }
  while( haltExecution );
}


uint16_t modbus_crc16(const uint8_t *buf, uint16_t len)
{
    uint16_t crc = 0xFFFF;
    for (uint16_t pos = 0; pos < len; pos++) 
    {
        crc ^= (uint16_t)buf[pos];
        for (int i = 0; i < 8; i++) 
        {
            if (crc & 0x0001) crc = (crc >> 1) ^ 0xA001;
            else crc >>= 1;
        }
    }
    return crc;
}

// build and send Modbus RTU read request for registers START..START+COUNT-1
void sendReadRequest()
{
    uint8_t req[8];
    req[0] = MODBUS_ADDR;
    req[1] = MODBUS_FN_READ;
    req[2] = (MODBUS_REG_START >> 8) & 0xFF;
    req[3] = MODBUS_REG_START & 0xFF;
    req[4] = (MODBUS_REG_COUNT >> 8) & 0xFF;
    req[5] = MODBUS_REG_COUNT & 0xFF;
    uint16_t crc = modbus_crc16(req, 6);
    req[6] = crc & 0xFF;       // CRC low
    req[7] = (crc >> 8) & 0xFF; // CRC high

    g_rs232Serial.write(req, 8);
}

// Attempt to read a Modbus RTU response for the last request.
// Blocks up to RESPONSE_TIMEOUT ms while collecting bytes.
// Returns true if a valid frame was parsed.
bool readResponseAndParse(AnemometerReadings &anemometerReadings)
{
    const uint8_t expectedByteCount = MODBUS_REG_COUNT * 2; // 10
    const uint8_t expectedLen = 1 + 1 + 1 + expectedByteCount + 2; // addr+func+bytecount+data+crc

    uint8_t buf[64];
    uint8_t pos = 0;
    unsigned long start = millis();

    while (millis() - start < RESPONSE_TIMEOUT) 
    {
        while (g_rs232Serial.available() && pos < sizeof(buf)) 
        {
            buf[pos++] = (uint8_t)g_rs232Serial.read();
        }
        if (pos >= expectedLen) 
            break;
    }

    if (pos < expectedLen) 
        return false;

    // Try to find a valid frame inside buf (sliding window)
    for (uint8_t offset = 0; offset + expectedLen <= pos; ++offset) 
    {
        uint8_t *p = buf + offset;
        if (p[0] != MODBUS_ADDR) 
            continue;
        if (p[1] != MODBUS_FN_READ) 
            continue;
        if (p[2] != expectedByteCount) 
            continue;
        uint16_t crc_calc = modbus_crc16(p, 3 + expectedByteCount);
        uint16_t crc_recv = (uint16_t)p[3 + expectedByteCount] | ((uint16_t)p[3 + expectedByteCount + 1] << 8);
        if (crc_calc != crc_recv) 
            continue;

        // parse registers
        for (uint8_t i = 0; i < MODBUS_REG_COUNT; ++i) 
        {
            uint8_t hi = p[3 + i*2];
            uint8_t lo = p[3 + i*2 + 1];
            uint16_t reg = ((uint16_t)hi << 8) | lo;
            switch (i) 
            {
                case 0: anemometerReadings.windSpeed = reg * SCALE_WIND_SPEED * SCALE_MPS_TO_KNOTS; break;
                case 1: anemometerReadings.windDirection   = reg * SCALE_WIND_DIR;   break;
                case 2: anemometerReadings.temperature = (int16_t)reg * SCALE_TEMPERATURE; break; // cast if signed
                case 3: anemometerReadings.humidity = reg * SCALE_HUMIDITY; break;
                case 4: anemometerReadings.pressure = reg * SCALE_PRESSURE; break;
            }
        }
        return true;
    }

    return false;
}

void printValues(AnemometerReadings anemometerReadings)
{
    Serial.print(millis()); Serial.print(", ");
    Serial.print("WSPD=");
    if (isnan(anemometerReadings.windSpeed)) 
        Serial.print("NaN"); 
    else 
        Serial.print(anemometerReadings.windSpeed, 2);
    
    Serial.print(", WDIR=");
    if (isnan(anemometerReadings.windDirection)) 
        Serial.print("NaN"); 
    else 
        Serial.print(anemometerReadings.windDirection, 1);

    Serial.print(", TEMP=");
    if (isnan(anemometerReadings.temperature)) 
        Serial.print("NaN"); 
    else 
        Serial.print(anemometerReadings.temperature, 2);

    Serial.print(", HUM=");
    if (isnan(anemometerReadings.humidity)) 
        Serial.print("NaN"); 
    else 
        Serial.print(anemometerReadings.humidity, 2);
    
    Serial.print(", PRES=");
    if (isnan(anemometerReadings.pressure)) 
        Serial.print("NaN"); 
    else 
        Serial.print(anemometerReadings.pressure, 2);
    Serial.println();
}

void setup()
{
    pinMode(MOTEINO_LED, OUTPUT);     
    digitalWrite(MOTEINO_LED, HIGH );
    Serial.begin(9600);

    g_rs232Serial.begin(BAUD_RS232);
    g_rs232Serial.stopListening();  //disable as interrupt can interfer with g_rf69
    Serial.println(F("Mini-C5A Modbus RTU reader starting"));

    if (!g_rf69.init())
        Serial.println(F("rf69 init failed"));
    if (!g_rf69.setFrequency(NETWORK_FREQUENCY))
        Serial.println(F("rf69 setFrequency failed"));
    // The encryption key has to be the same as the one in the client
    uint8_t key[] = { 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
                    0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08};
    g_rf69.setEncryptionKey(key);
    g_rf69.setHeaderId(ANEMOMETER_NODE);
    //g_rf69.setIdleMode(RH_RF69_OPMODE_MODE_SLEEP);
    //when using the RH_RF69 driver with the RFM69HW module, you must setTxPowercan with isHigherPowerModule set to true
    //Otherwise, the library will not set the PA_BOOST pin high and the module will not transmit
    //g_rf69.setTxPower(13,true);
    Serial.print(F("RF69 initialise node: "));
    Serial.print(ANEMOMETER_NODE);
    Serial.print(F(" Freq: "));Serial.print(NETWORK_FREQUENCY,1); Serial.println(F("MHz"));

    memset(&g_payloadAnemometer, 0, sizeof(g_payloadAnemometer));
    g_payloadAnemometer.subnode = 1;
    memset(&g_payloadPressure, 0, sizeof(g_payloadPressure));
    g_payloadPressure.subnode = 1;
    memset(&g_payloadIMU, 0, sizeof(g_payloadIMU));
    g_payloadIMU.subnode = 0;
    EmonSerial::PrintPressurePayload(NULL);
    EmonSerial::PrintGPSPayload(NULL);
    EmonSerial::PrintAnemometerPayload(NULL);
    EmonSerial::PrintIMUPayload(NULL);
    Serial.println(F("mwv,0= wind relative to boat"));
    Serial.println(F("mwv,1= apparent wind"));
    Serial.println(F("mwv,2= true wind"));

    Wire.begin();
    delay(50);
    Serial.println(F("GY-86 sensor test startup"));

    bool okMPU = initMPU6050();
    Serial.print(F("MPU6050: "));
    Serial.println(okMPU ? F("OK") : F("NOT FOUND"));

    bool okHMC = initHMC5883L();
    Serial.print(F("HMC5883L: "));
    Serial.println(okHMC ? F("OK") : F("NOT FOUND"));

    bool okMS5 = initMS5611();
    Serial.print(F("MS5611: "));
    Serial.println(okMS5 ? F("OK") : F("NOT FOUND"));


    digitalWrite(MOTEINO_LED, LOW );

    /////////calibration routine////////////
    //collectDataForMahonyCalibration();

    /////////wireFrame and wireFramePitchRollHeave routines
    //DoPitchRollYawLoop();
}

void loop()
{
    static unsigned long lastSendWindTime = millis();
    static unsigned long lastSendPressureTime = millis();
    static unsigned long lastGPSUpdate = 0;

    unsigned long now = millis();

    //receive a GPS update
    if(g_rf69.available() && g_rf69.headerId()==GPS_NODE)
    {
        uint8_t buf[RH_RF69_MAX_MESSAGE_LEN];
        memset(buf, 0, RH_RF69_MAX_MESSAGE_LEN);

        uint8_t len = sizeof(buf);
        if (g_rf69.recv(buf, &len) && len == sizeof(PayloadGPS))
        {
			g_payloadGPS = *(PayloadGPS*)buf;
			EmonSerial::PrintGPSPayload(&g_payloadGPS);
            lastGPSUpdate = millis();
        }
    }


    if (now - lastSendWindTime >= SEND_WIND_INTERVAL_MS) 
    {
        //turn off the radio to avoid interference with RS232 reading
        lastSendWindTime = now;
        g_rf69.setIdleMode(RH_RF69_OPMODE_MODE_SLEEP);
        g_rs232Serial.listen();
        sendReadRequest();          // send request to MiniC5A anemometer
        // read and parse response
        AnemometerReadings anemometerReadings;
        bool readAnemometerOK = readResponseAndParse(anemometerReadings);
        g_rs232Serial.stopListening();
        g_rf69.setIdleMode(RH_RF69_OPMODE_MODE_STDBY);

        digitalWrite(MOTEINO_LED, HIGH );

        //Get the IMU data to publish
        // Calculate the vessel heading so we can send apparent wind direction as well as vessel oriented wind direction
        get_scaled_IMU(g_payloadIMU.acc, g_payloadIMU.mag);  //apply relative scale and offset to RAW data. UNITS are not important
        get_gyro(g_payloadIMU.gyro);                         //get gyro data with offsets removed
        g_payloadIMU.heading = get_heading(g_payloadIMU.acc, g_payloadIMU.mag, p, declination);

        g_rf69.setHeaderId(IMU_NODE);
        g_rf69.send((const uint8_t*) &g_payloadIMU, sizeof(PayloadIMU) );
        if( g_rf69.waitPacketSent() )
        {
            EmonSerial::PrintIMUPayload(&g_payloadIMU);
        }
        digitalWrite(MOTEINO_LED, LOW );

        if (readAnemometerOK) 
        {
            //printValues(anemometerReadings);

            digitalWrite(MOTEINO_LED, HIGH );

            //Send vessel relatative wind data first
            g_rf69.setHeaderId(ANEMOMETER_NODE);
            g_payloadAnemometer.subnode = 0;    //relative to boat wind
            g_payloadAnemometer.windSpeed = anemometerReadings.windSpeed;      // m/s
            g_payloadAnemometer.windDirection = anemometerReadings.windDirection;          // degrees
            g_payloadAnemometer.temperature = anemometerReadings.temperature;  // degree celcius

            g_rf69.send((const uint8_t*) &g_payloadAnemometer, sizeof(PayloadAnemometer) );
            if( g_rf69.waitPacketSent() )
            {
                EmonSerial::PrintAnemometerPayload(&g_payloadAnemometer);
            }
            else
            {
                Serial.println(F("No packet sent"));
            }
            //now send compass based wind direction as a separate packet.
            //ANEMOMETER_HEADING_OFFSET trims the vane's zero relative to the centreline; the
            //compass's own alignment is already removed inside get_heading().
            float apparentWindDirection = anemometerReadings.windDirection - ANEMOMETER_HEADING_OFFSET + g_payloadIMU.heading;
            apparentWindDirection = fmod(apparentWindDirection + 720.0, 360.0);
            g_payloadAnemometer.subnode = 1;    //apparent wind
            g_payloadAnemometer.windDirection = apparentWindDirection;
            g_rf69.send((const uint8_t*) &g_payloadAnemometer, sizeof(PayloadAnemometer) );
            if( g_rf69.waitPacketSent() )   
            {
                EmonSerial::PrintAnemometerPayload(&g_payloadAnemometer);
            }
            else
            {
                Serial.println(F("No packet sent"));
            }

            //Finally send true wind speed and direction based on a recent GPS update if we have a recent GPS update
            if( now - lastGPSUpdate < 3000 )
            {
                TrueWind tw = calculateTrueWind(anemometerReadings.windSpeed, apparentWindDirection, g_payloadGPS.speed, g_payloadGPS.course);
                g_payloadAnemometer.subnode = 2;    //True wind
                g_payloadAnemometer.windDirection = tw.twd;
                g_payloadAnemometer.windSpeed = tw.tws;
                g_rf69.send((const uint8_t*) &g_payloadAnemometer, sizeof(PayloadAnemometer) );
                if( g_rf69.waitPacketSent() )   
                {
                    EmonSerial::PrintAnemometerPayload(&g_payloadAnemometer);
                }
                else
                {
                    Serial.println(F("No packet sent"));
                }
            }

            digitalWrite(MOTEINO_LED, LOW );

            //send the pressure readings less regularly
            if( (now - lastSendPressureTime) >= SEND_PRESSURE_INTERVAL_MS )
            {
                //delay(100);
                digitalWrite(MOTEINO_LED, HIGH );

                lastSendPressureTime = now;
                // send pressure packet
                g_rf69.setHeaderId(PRESSURE_NODE);
                g_payloadPressure.subnode = 1;
                g_payloadPressure.pressure = anemometerReadings.pressure*100.0;
                g_payloadPressure.humidity = anemometerReadings.humidity;
                g_payloadPressure.temperature = anemometerReadings.temperature;

                g_rf69.send((const uint8_t*) &g_payloadPressure, sizeof(PayloadPressure) );
                if( g_rf69.waitPacketSent() )
                {
                    EmonSerial::PrintPressurePayload(&g_payloadPressure);
                }
                else
                {
                    Serial.println(F("No packet sent"));
                }

                // send another packet with details from the M5611 on the 9dof sensor
                // g_payloadPressure.subnode = 1;
                // g_payloadPressure.humidity = 0;
                // get_temperature_pressure(g_payloadPressure.temperature, g_payloadPressure.pressure );
                // g_rf69.send((const uint8_t*) &g_payloadPressure, sizeof(PayloadPressure) );
                // if( g_rf69.waitPacketSent() )
                // {
                //     EmonSerial::PrintPressurePayload(&g_payloadPressure);
                // }
                // else
                // {
                //     Serial.println(F("No packet sent"));
                // }


                digitalWrite(MOTEINO_LED, LOW );
            }
        } 
        else 
        {
            Serial.println(F("No valid Modbus response"));
            flashErrorToLED(4);
        }
    }

    // small idle delay
    delay(10);
}