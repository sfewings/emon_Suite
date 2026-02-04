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

float GyroOffset[3] = {0.0f, 0.0f, 0.0f};


// VERY IMPORTANT!
//These are the previously determined offsets and scale factors for accelerometer and magnetometer, using ICM_20948_cal and Magneto
//The compass will NOT work well or at all if these are not correct

//Accel scale: divide by 16604.0 to normalize. These corrections are quite small and probably can be ignored.
float A_B [3] = {-142.37, 1379.88, 2941.27};


float A_Ainv[3][3] = {
{ 0.05835, 0.00087, -0.00058 },
{ 0.00087, 0.06162, 0.00127 },
{ -0.00058, 0.00127, 0.05849 }};

//Mag scale divide by 369.4 to normalize. These are significant corrections, especially the large offsets.
float M_B [3] = {45.68, -121.05, 2.35};


float M_Ainv[3][3] = {
{ 5.18943, -0.08813, 0.03296 },
{ -0.08813, 4.98646, -0.14547 },
{ 0.03296, -0.14547, 6.13326 }};


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

  // True wind = apparent wind + vessel motion
  float twx = awx + vx;
  float twy = awy + vy;

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
//Routine taken from ICM_20948_get_cal_data.ino  
// Collect data for Mahony AHRS calibration https://github.com/jremington/ICM_20948-AHRS
// Paste output to acc_mag_raw.csv file for input to calibrate3.py to create updates for A_B, A_AInv, M_B, M_Ainv calibration arrays
// Outputs pasted into this sketch
void collectDataForMahonyCalibration()
{
    int16_t acc_mag_readings[6];
    
    g_rf69.setHeaderId(99);
    
    // find gyro offsets
    Serial.println(F("ax(g), ay(g), az(g), mag_x, mag_y, mag_z"));

    Serial.println(F("Hold sensor still for 5 seconds for gyro offset calibration ..."));
    delay(5000);

    float goff;
    int i;
    long gyro[3] = {0};
    int offset_count = 500; //average this many values for gyro
    int acc_mag_count = 300; //collect this many values for acc/mag calibration


    for (i = 0; i < offset_count; i++) 
    {
        // MPU6050 accel & gyro
        int16_t gx = readS16(ADDR_MPU6050, MPU_ACCEL_XOUT_H + 8);
        int16_t gy = readS16(ADDR_MPU6050, MPU_ACCEL_XOUT_H +10);
        int16_t gz = readS16(ADDR_MPU6050, MPU_ACCEL_XOUT_H +12);

        gyro[0] += gx;
        gyro[1] += gy;
        gyro[2] += gz;
    } //done with gyro

    Serial.print("Gyro offsets x, y, z: ");
    for (i = 0; i < 3; i++) 
    {
        goff = (float)gyro[i] / offset_count;
        Serial.print(goff, 1);
        Serial.print(", ");
    }
    Serial.println();

    Serial.println(F("Turn sensor SLOWLY and STEADILY in all directions until done"));
    delay(5000);
    Serial.println(F("Starting..."));

    //get values for calibration of acc/mag
    for (i = 0; i < acc_mag_count; i++) 
    {
        int16_t ax = readS16(ADDR_MPU6050, MPU_ACCEL_XOUT_H + 0);
        int16_t ay = readS16(ADDR_MPU6050, MPU_ACCEL_XOUT_H + 2);
        int16_t az = readS16(ADDR_MPU6050, MPU_ACCEL_XOUT_H + 4);

        acc_mag_readings[0] = ax;
        acc_mag_readings[1] = ay;
        acc_mag_readings[2] = az;

        Serial.print(ax);
        Serial.print(", ");
        Serial.print(ay);
        Serial.print(", ");
        Serial.print(az);
        Serial.print(", ");


        uint8_t magBuf[6];
        if (readRegisters(ADDR_HMC5883L, HMC_DATA_X_MSB, magBuf, 6)) {
            int16_t mX = (int16_t)((magBuf[0] << 8) | magBuf[1]);
            int16_t mZ = (int16_t)((magBuf[2] << 8) | magBuf[3]);
            int16_t mY = (int16_t)((magBuf[4] << 8) | magBuf[5]);

            acc_mag_readings[3] = mX;
            acc_mag_readings[4] = mY;
            acc_mag_readings[5] = mZ;

            Serial.print(mX);
            Serial.print(", ");
            Serial.print(mY);
            Serial.print(", ");
            Serial.print(mZ);
        }

        digitalWrite(MOTEINO_LED,HIGH);
        g_rf69.send((const uint8_t*) acc_mag_readings, 6*sizeof(int16_t) );
        if( g_rf69.waitPacketSent() )
            Serial.print(",sent");   
        digitalWrite(MOTEINO_LED,LOW);

        Serial.println();
           delay(200);
    }

    // for (i = 0; i < acc_mag_count; i++) 
    // {
    //     for(int j=0; j<6;j++)
    //     {
    //         acc_mag_readings[j] = i;
    //         Serial.print(i);
    //         if(j<5)
    //             Serial.print(", ");
    //     }

    //     digitalWrite(MOTEINO_LED,HIGH);
    //     g_rf69.send((const uint8_t*) acc_mag_readings, 6*sizeof(int16_t) );
    //     if( g_rf69.waitPacketSent() )
    //         Serial.print(",sent");   
    //     digitalWrite(MOTEINO_LED,LOW);

    //     Serial.println();

    //     delay(200);
    // }
    Serial.print(F("Done collecting"));
    
    g_rf69.setHeaderId(ANEMOMETER_NODE);
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
  int heading = round(h + magdec);
  heading = (heading + 720) % 360; //apply compass wrap
  return heading;
}

void get_gyro(float Gxyz[3]) 
{
  int16_t gx = readS16(ADDR_MPU6050, MPU_ACCEL_XOUT_H + 8);
  int16_t gy = readS16(ADDR_MPU6050, MPU_ACCEL_XOUT_H +10);
  int16_t gz = readS16(ADDR_MPU6050, MPU_ACCEL_XOUT_H +12);

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
    memset(&payloadIMU, 0, sizeof(g_payloadIMU));
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

        //calculate the vessel heading so we can send apparent wind direction as well as vessel oriented wind direction

        get_scaled_IMU(g_payloadIMU.Acc, g_payloadIMU.Mag);  //apply relative scale and offset to RAW data. UNITS are not important
        get_gyro(g_payloadIMU.Gyro);                         //get gyro data with offsets removed
        g_payloadIMU.heading = get_heading(g_payloadIMU.Acc, g_payloadIMU.Mag, p, declination);

        g_rf69.setHeaderId(IMU_NODE);
        g_rf69.send((const uint8_t*) &g_payloadIMU, sizeof(PayloadIMU) );
        if( g_rf69.waitPacketSent() )
        {
            EmonSerial::PrintIMUPayload(&g_payloadIMU);
        }

        if (readAnemometerOK) 
        {
            //printValues(anemometerReadings);


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
            //now send compass based wind direction as a separate packet
            float apparentWindDirection = fmod(anemometerReadings.windDirection + (float) heading, 360.0);
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
                g_payloadPressure.pressure = anemometerReadings.pressure;
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