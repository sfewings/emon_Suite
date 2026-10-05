// Mini-C5A Modbus RTU reader - reads 5 registers starting at 0x0000 from slave addr 0x01
// Parses registers (0..4) into windSpeed, windDirection, temperature, humidity, pressure.
// Adjust scaling constants to match your sensor's register scaling.
#include <SoftwareSerial.h>

#include <EmonShared.h>
#include <RH_RF69.h>
#include <Wire.h>
#include <avr/wdt.h>    //watchdog timer

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
const uint16_t PACKET_SENT_TIMEOUT_MS = 200;  // ample for a 60 byte packet at 250kbps
const uint8_t MAX_IMU_FAILURES = 5;   // consecutive IMU read failures before recovering the I2C bus

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
// Subtracted from the computed heading.
// Re-measured on the Enchantee_20260823 sail, the first with the bench recalibration
// aboard: over 4702 steady straight-line samples the compass read 4.85 deg LOW against
// GPS course (95% CI 4.3 to 5.4), so the previous 12 over-corrected. Allowing for
// leeway, which the same fit puts at 0.34 deg per degree of heel, gives 5.45 deg low.
// 12 came from the 20260816 log and was correct for the OLD magnetometer calibration;
// changing M_B shifts the heading by a heading-dependent amount, so this constant has
// to be re-measured whenever the magnetometer is recalibrated.
const int INSTALATION_HEADING_OFFSET = 7;

// Degrees the anemometer's zero mark is rotated clockwise from the boat's centreline.
// Subtracted from the vane angle before it is combined with the heading, so it shifts
// apparent and true wind direction without touching the boat-relative reading (subnode 0).
// Confirmed at 0 on the Enchantee_20260823 sail by two independent tests: the
// true-wind-steadiness fit is flat (2.005 kt scatter at -11 deg against 2.051 at 0, not
// a real minimum), and the tack-to-tack true wind direction split is -0.15 +-3 deg.
// Trim this if a genuine split reappears - but measure the split INSIDE 5-minute
// windows. Pooling a whole sail turns any wind shift into a fake split: on 20260823 the
// breeze veered 60 deg and the pooled figure read +5.5 deg when the real one was zero.
const int ANEMOMETER_HEADING_OFFSET = 0;

//Use calibrato4.py to calculate these values
float GyroOffset[3] = {-654.9f, -85.8f, -100.5f};

float A_B [3] = {648.80, 14.56, 2393.87};
float A_Ainv[3][3] = {
{ 0.06098, -0.00029, 0.00008 },
{ -0.00029, 0.06140, 0.00004 },
{ 0.00008, 0.00004, 0.06050 }};

float M_B [3] = {102.05, -121.66, 10.22};

float M_Ainv[3][3] = {
{ 3.81800, 0.02270, -0.02062 },
{ 0.02270, 3.81465, -0.04824 },
{ -0.02062, -0.04824, 4.76717 }};

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

// As readS16() but reports the failure instead of silently returning zero, so callers that publish
// the value can keep the last known good reading rather than a fabricated one
bool readS16Checked(uint8_t addr, uint8_t regHigh, int16_t &value) {
  uint8_t b[2];
  if (!readRegisters(addr, regHigh, b, 2)) return false;
  value = (int16_t)((b[0] << 8) | b[1]);
  return true;
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

//A reset part way through an I2C transfer can leave a slave holding SDA low, which stops the master
//generating a START for ever after. Clock SCL by hand until the slave lets go, then issue a STOP
void i2cBusClear()
{
    pinMode(SDA, INPUT_PULLUP);
    pinMode(SCL, INPUT_PULLUP);
    delayMicroseconds(10);

    for (uint8_t i = 0; i < 9 && digitalRead(SDA) == LOW; i++)
    {
        digitalWrite(SCL, LOW);      //clears the pull up before the pin becomes an output
        pinMode(SCL, OUTPUT);
        delayMicroseconds(5);
        pinMode(SCL, INPUT_PULLUP);  //release, the pull up takes it high
        delayMicroseconds(5);
    }

    //STOP condition. SDA low to high while SCL is high
    digitalWrite(SDA, LOW);
    pinMode(SDA, OUTPUT);
    delayMicroseconds(5);
    pinMode(SDA, INPUT_PULLUP);
    delayMicroseconds(5);
}

//Recover the bus and bring up the three GY-86 sensors. Called from setup(), and again from loop()
//if the IMU reads keep failing
void i2cInit()
{
    //Recover the bus before touching Wire, otherwise initMPU6050() can block for ever. This is the
    //likeliest cause of a lockup with the LED left on: a brown out reset in the middle of a transfer
    //leaves the slave driving SDA, and setup() then hangs on the first transaction
    i2cBusClear();
    Wire.begin();
    //Without this the Wire library busy waits with no timeout, so one stuck slave hangs the sketch
    //for ever. Needs Arduino AVR core 1.8.4 or later, which is where setWireTimeout() was added
    Wire.setWireTimeout(25000, true);   //25ms, and reset the TWI hardware on a timeout
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
}

//Bring the radio up from cold. Called from setup() and again from waitPacketSentOrRecover() if the
//driver ever wedges, so everything the sketch relies on has to be set here rather than in setup()
bool radioInit()
{
    bool ok = true;
    if (!g_rf69.init())
    {
        Serial.println(F("rf69 init failed"));
        ok = false;
    }
    if (!g_rf69.setFrequency(NETWORK_FREQUENCY))
    {
        Serial.println(F("rf69 setFrequency failed"));
        ok = false;
    }
    // The encryption key has to be the same as the one in the client
    uint8_t key[] = { 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
                    0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08};
    g_rf69.setEncryptionKey(key);
    g_rf69.setHeaderId(ANEMOMETER_NODE);
    //Leave _idleMode at its RH_RF69_OPMODE_MODE_STDBY default, see the note in loop()
    //when using the RH_RF69 driver with the RFM69HW module, you must setTxPowercan with isHigherPowerModule set to true
    //Otherwise, the library will not set the PA_BOOST pin high and the module will not transmit
    //g_rf69.setTxPower(13,true);
    Serial.print(F("RF69 initialise node: "));
    Serial.print(ANEMOMETER_NODE);
    Serial.print(F(" Freq: "));Serial.print(NETWORK_FREQUENCY,1); Serial.println(F("MHz"));
    return ok;
}

//RH_RF69::waitPacketSent() with no argument is "while (_mode == RHModeTx) YIELD;" with no escape,
//and RH_RF69::send() opens with the same wait, so one missed PACKETSENT interrupt wedges the radio
//permanently: no packets, LED left on, only a power cycle recovers it. The interrupt can be missed
//because setModeTx() writes the TX opmode register before it assigns _mode = RHModeTx, so a
//PACKETSENT arriving in that window is seen by the ISR while _mode is still Idle and discarded, and
//being RISING edge triggered it never comes again. Use the timeout form and rebuild the driver.
bool waitPacketSentOrRecover()
{
    if( g_rf69.waitPacketSent(PACKET_SENT_TIMEOUT_MS) )
        return true;

    Serial.println(F("waitPacketSent timeout, re-initialising the radio"));
    radioInit();
    return false;
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

// Returns false if the MPU6050 did not answer, in which case v is only partly written. The
// calibration phases ignore the result, get_scaled_IMU() and get_gyro() do not.
bool readRawAcc(int16_t v[3])
{
    return readS16Checked(ADDR_MPU6050, MPU_ACCEL_XOUT_H + 0, v[0])
        && readS16Checked(ADDR_MPU6050, MPU_ACCEL_XOUT_H + 2, v[1])
        && readS16Checked(ADDR_MPU6050, MPU_ACCEL_XOUT_H + 4, v[2]);
}

bool readRawGyro(int16_t v[3])
{
    return readS16Checked(ADDR_MPU6050, MPU_ACCEL_XOUT_H + 8, v[0])
        && readS16Checked(ADDR_MPU6050, MPU_ACCEL_XOUT_H + 10, v[1])
        && readS16Checked(ADDR_MPU6050, MPU_ACCEL_XOUT_H + 12, v[2]);
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
// Sets the header every time rather than trusting the caller: a radio recovery inside
// waitPacketSentOrRecover() puts it back to ANEMOMETER_NODE, and silently mislabelling the rest of
// an in-situ magnetometer swing would waste the whole trip up the mast.
void calBroadcast(char phase, uint8_t index, const int16_t* v, uint8_t n)
{
    PayloadCalibration p;
    memset(&p, 0, sizeof(p));
    p.phase = (byte)phase;
    p.index = index;
    for (uint8_t i = 0; i < n && i < 9; i++)
        p.v[i] = v[i];
    g_rf69.setHeaderId(CALIBRATION_NODE);
    g_rf69.send((const uint8_t*)&p, sizeof(p));
    waitPacketSentOrRecover();
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

// The 12 orientations. ORDER DOES NOT MATTER, and neither does the accuracy of any
// individual position - see the note above calAccPhase() for why.
//
// 0-5  are the six axis-aligned faces. Between them they place a full +1 g and a full
//      -1 g on each axis in turn, which is what fixes the zero offset and the scale of
//      that axis. All six must appear or that axis is left unconstrained; calibrate4.py
//      reports the gap if one is missed.
// 6-11 are tilted so that gravity lands on two or three axes at once. These are what
//      constrain the off-diagonal (cross-axis) terms of A_Ainv. Roughly 45 degrees is
//      plenty - the angle is not measured, so it only has to differ from the others.
//      Four are component-side-up and two are component-side-down, which spreads them
//      over both hemispheres.
void calPrintPositionName(uint8_t i)
{
    switch (i)
    {
        case 0:  Serial.print(F("FLAT on the bench, component side UP        -> +Z up")); break;
        case 1:  Serial.print(F("FLAT, turned over, component side DOWN     -> -Z up")); break;
        case 2:  Serial.print(F("on its side, edge the X arrow points to UP  -> +X up")); break;
        case 3:  Serial.print(F("on its side, that same X edge DOWN          -> -X up")); break;
        case 4:  Serial.print(F("on its side, edge the Y arrow points to UP  -> +Y up")); break;
        case 5:  Serial.print(F("on its side, that same Y edge DOWN          -> -Y up")); break;
        case 6:  Serial.print(F("TILTED ~45 deg, component side up, corner between +X and +Y highest")); break;
        case 7:  Serial.print(F("TILTED ~45 deg, component side up, corner between -X and +Y highest")); break;
        case 8:  Serial.print(F("TILTED ~45 deg, component side up, corner between +X and -Y highest")); break;
        case 9:  Serial.print(F("TILTED ~45 deg, component side up, corner between -X and -Y highest")); break;
        case 10: Serial.print(F("TILTED ~45 deg, component side DOWN, corner between +X and +Y highest")); break;
        case 11: Serial.print(F("TILTED ~45 deg, component side DOWN, corner between -X and -Y highest")); break;
        default: Serial.print(F("any orientation not already used")); break;
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

// Does the ORDER of the 12 orientations matter?  No.
//
// The fit is a least-squares ellipsoid through an unordered cloud of points, so the
// sequence has no effect on the result. Nor does the accuracy of any one position: the
// claimed orientation is never used as an input. calibrate4.py reads only the measured
// counts, and the position index in each 'A' record is a label for the operator's
// benefit, nothing more.
//
// What the prompts are actually for is COVERAGE. The fit needs points spread over the
// whole sphere, and the quickest way to get a human to produce that is to name twelve
// specific attitudes. So:
//   - all six faces must appear, or the missing axis is left unconstrained
//   - no two positions should be the same, or a constraint is wasted and the
//     least-squares weighting skews toward that direction
//   - exact angles are irrelevant; "roughly 45 degrees" really is roughly
// calibrate4.py measures the coverage it actually got and names the worst gap, so a
// missed or duplicated position is caught there rather than being assumed away here.
//
// Worth doing in one sitting though, not because of order but because the MPU6050's
// zero-g offset drifts with temperature, and the fit assumes one constant bias.
void calAccPhase()
{
    Serial.println(F("#BEGIN ACC"));
    Serial.println(F("# Hold the unit STILL in each orientation. It waits until it stops"));
    Serial.println(F("# moving before it samples, so resting it against something helps."));
    Serial.println(F("# The magnetometer is logged here too, for the dip cross-check."));
    Serial.println(F("# Order does not matter and the angles need not be exact - what"));
    Serial.println(F("# matters is that all 6 faces appear and no two are the same."));
    Serial.println(F("# Try to get through all 12 without a long break: the zero-g offset"));
    Serial.println(F("# drifts with temperature and the fit assumes it is constant."));

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
    //This routine waits on the operator indefinitely and sweeps for minutes at a time, so it cannot
    //live inside the 8 second watchdog. Re-enabled at both exits, below
    wdt_disable();

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
    wdt_enable(WDTO_8S);
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
                wdt_enable(WDTO_8S);
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

    //never returns, so it cannot live inside the 8 second watchdog
    wdt_disable();

    Serial.println(F("Output for external pitch, roll, yaw display"));
    Serial.println(F("ax(g), ay(g), az(g), mag_x, mag_y, mag_z, heading, loop_time_ms"));

    //if (millis() - lastPrint > 50)
    while(true)
    {
        //on a failed read the previous values are printed again, so a stalled line means I2C trouble
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

// Returns false and leaves the vector alone if it has no length. Dividing by a zero magnitude
// produced NaN, which propagated silently into the published heading
bool vector_normalize(float a[3])
{
  float mag = sqrt(vector_dot(a, a));
  if (!(mag > 0.0f))    //written this way so a NaN magnitude also fails
    return false;
  a[0] /= mag;
  a[1] /= mag;
  a[2] /= mag;
  return true;
}
////////////////////////////////////


// Returns a heading (in degrees) given an acceleration vector a due to gravity, a magnetic vector m, and a facing vector p.
// applies magnetic declination
// Returns -1 if the geometry is degenerate, meaning the acceleration and magnetic vectors are
// parallel so there is no horizontal reference to work from. That needs a tilt of about 66 degrees
// here, where the magnetic dip is steep, so it takes a knockdown, but the zero length cross product
// used to divide through to NaN and casting a NaN to int is undefined.
int get_heading(float acc[3], float mag[3], float p[3], float magdec)
{
  float W[3], N[3]; //derived direction vectors

  // cross "Up" (acceleration vector, g) with magnetic vector (magnetic north + inclination) with  to produce "West"
  vector_cross(acc, mag, W);
  if (!vector_normalize(W))
    return -1;

  // cross "West" with "Up" to produce "North" (parallel to the ground)
  vector_cross(W, acc, N);
  if (!vector_normalize(N))
    return -1;

  // compute heading in horizontal plane, correct for local magnetic declination in degrees

  float h = -atan2(vector_dot(W, p), vector_dot(N, p)) * 180 / M_PI; //minus: conventional nav, heading increases North to East
  int heading = round(h + magdec) - INSTALATION_HEADING_OFFSET;
  heading = (heading + 720) % 360; //apply compass wrap
  return heading;
}

// Returns false and leaves Gxyz untouched if the read failed
bool get_gyro(float Gxyz[3])
{
  int16_t g[3];
  if (!readRawGyro(g))
    return false;

  // GyroOffset holds the MEAN of the raw readings taken while the sensor was held
  // still by collectDataForMahonyCalibration(), so it must be SUBTRACTED. Adding it
  // doubled the bias instead of removing it.
  Gxyz[0] = (float)g[0] - GyroOffset[0];
  Gxyz[1] = (float)g[1] - GyroOffset[1];
  Gxyz[2] = (float)g[2] - GyroOffset[2];
  return true;
}

// subtract offsets and correction matrix to accel and mag data
// Returns false and leaves Axyz and Mxyz untouched if any read failed or the result could not be
// normalized, so the caller keeps its last known good values. The old version ignored the
// magnetometer read result and used magBuf uninitialised on a failure, which put whatever was on
// the stack through the correction matrix and into the published payload.
bool get_scaled_IMU(float Axyz[3], float Mxyz[3]) {
  byte i;
  float temp[3];
  float acc[3], mag[3];
  int16_t a[3], m[3];

  if (!readRawAcc(a))
    return false;
  if (!readRawMag(m))    //handles the X, Z, Y order on the wire
    return false;

  acc[0] = a[0];
  acc[1] = a[1];
  acc[2] = a[2];
  mag[0] = m[0];
  mag[1] = m[1];
  mag[2] = m[2];
  //apply offsets (bias) and scale factors from Magneto
  for (i = 0; i < 3; i++) temp[i] = (acc[i] - A_B[i]);
  acc[0] = A_Ainv[0][0] * temp[0] + A_Ainv[0][1] * temp[1] + A_Ainv[0][2] * temp[2];
  acc[1] = A_Ainv[1][0] * temp[0] + A_Ainv[1][1] * temp[1] + A_Ainv[1][2] * temp[2];
  acc[2] = A_Ainv[2][0] * temp[0] + A_Ainv[2][1] * temp[1] + A_Ainv[2][2] * temp[2];
  if (!vector_normalize(acc))
    return false;

  //apply offsets (bias) and scale factors from Magneto
  for (i = 0; i < 3; i++) temp[i] = (mag[i] - M_B[i]);
  mag[0] = M_Ainv[0][0] * temp[0] + M_Ainv[0][1] * temp[1] + M_Ainv[0][2] * temp[2];
  mag[1] = M_Ainv[1][0] * temp[0] + M_Ainv[1][1] * temp[1] + M_Ainv[1][2] * temp[2];
  mag[2] = M_Ainv[2][0] * temp[0] + M_Ainv[2][1] * temp[1] + M_Ainv[2][2] * temp[2];
  if (!vector_normalize(mag))
    return false;

  //only commit once everything succeeded
  for (i = 0; i < 3; i++)
  {
    Axyz[i] = acc[i];
    Mxyz[i] = mag[i];
  }
  return true;
}


/////////////////////////////////////////////////
// MiniC5 anemometer routines

// Note this blocks for error*500ms plus a second, so a Modbus failure costs 3 seconds of loop time
void flashErrorToLED(int error, bool haltExecution = false)
{
  do
  {
    for( int i = 0; i < error; i++)
    {
      wdt_reset();    //this blocks for seconds, and with haltExecution for ever
      digitalWrite(MOTEINO_LED, HIGH);
      delay(300);
      digitalWrite(MOTEINO_LED, LOW);
      delay(200);
    }
	wdt_reset();
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
    //Capture the reset cause and get the watchdog out of the way before anything else. After a
    //watchdog reset the AVR re-enables the watchdog at its 16ms minimum, and if the bootloader does
    //not clear it the chip resets again before setup() can finish. That is an endless reset loop
    //which looks exactly like a dead board, and the reset button does not help either
    uint8_t mcusr = MCUSR;
    MCUSR = 0;
    wdt_disable();

    pinMode(MOTEINO_LED, OUTPUT);
    digitalWrite(MOTEINO_LED, HIGH );

    //8 seconds, as used by the other emon nodes. Comfortably longer than the 500ms Modbus timeout
    //plus the packet sends, and it turns a lockup at the top of the mast into a short gap in the log
    wdt_enable(WDTO_8S);

    Serial.begin(9600);
//    Serial.begin(115200); For DoPitchRollYaw()

    g_rs232Serial.begin(BAUD_RS232);
    g_rs232Serial.stopListening();  //disable as interrupt can interfer with g_rf69
    Serial.println(F("Mini-C5A Modbus RTU reader starting"));

    //BORF here means the supply is sagging, most likely on the transmit current spike, and that is
    //also what leaves the I2C bus stuck for i2cBusClear() to sort out below
    Serial.print(F("Reset cause MCUSR=0x")); Serial.println(mcusr, HEX);   //0 if the bootloader cleared it
    if( mcusr & _BV(WDRF) )  Serial.println(F(" watchdog reset"));
    if( mcusr & _BV(BORF) )  Serial.println(F(" brown out reset"));
    if( mcusr & _BV(EXTRF) ) Serial.println(F(" external reset"));
    if( mcusr & _BV(PORF) )  Serial.println(F(" power on reset"));

    radioInit();

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

    i2cInit();

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
    static uint8_t imuFailures = 0;

    wdt_reset();

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
        //The radio deliberately stays in receive while the Modbus response is read. The two
        //setIdleMode() calls that used to sit here did not turn it off: setIdleMode() only assigns
        //RH_RF69's _idleMode field, it never touches the chip. What they did do is leave _idleMode
        //at SLEEP across the read, so an incoming packet made the ISR put the chip to sleep, and the
        //following send() then filled the FIFO with the chip asleep. Staying in RX is also what
        //catches the GPS packets that true wind needs.
        lastSendWindTime = now;
        g_rs232Serial.listen();
        sendReadRequest();          // send request to MiniC5A anemometer
        // read and parse response
        AnemometerReadings anemometerReadings;
        bool readAnemometerOK = readResponseAndParse(anemometerReadings);
        g_rs232Serial.stopListening();

        digitalWrite(MOTEINO_LED, HIGH );

        //Get the IMU data to publish
        // Calculate the vessel heading so we can send apparent wind direction as well as vessel oriented wind direction
        //On a failed I2C read the previous values are kept and published again, which is far better
        //than the garbage the old code let through, but it does mean a wedged sensor shows up as a
        //frozen heading rather than an obviously bad one. Watch for the message below.
        bool imuOK = get_scaled_IMU(g_payloadIMU.acc, g_payloadIMU.mag);  //apply relative scale and offset to RAW data. UNITS are not important
        if( imuOK )
        {
            int heading = get_heading(g_payloadIMU.acc, g_payloadIMU.mag, p, declination);
            if( heading >= 0 )
                g_payloadIMU.heading = heading;
            else
                imuOK = false;
        }
        if( !get_gyro(g_payloadIMU.gyro) )                   //get gyro data with offsets removed
            imuOK = false;

        if( imuOK )
        {
            imuFailures = 0;
        }
        else if( ++imuFailures >= MAX_IMU_FAILURES )
        {
            //Wire.setWireTimeout() has already reset the TWI hardware, so the only thing left that
            //it cannot fix is a slave holding SDA low. Clock it out and re-initialise the sensors
            Serial.println(F("IMU reads failing, recovering the I2C bus"));
            i2cInit();
            imuFailures = 0;
        }

        g_rf69.setHeaderId(IMU_NODE);
        g_rf69.send((const uint8_t*) &g_payloadIMU, sizeof(PayloadIMU) );
        if( waitPacketSentOrRecover() )
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
            if( waitPacketSentOrRecover() )
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
            if( waitPacketSentOrRecover() )   
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
                if( waitPacketSentOrRecover() )   
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
                if( waitPacketSentOrRecover() )
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
                // if( waitPacketSentOrRecover() )
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