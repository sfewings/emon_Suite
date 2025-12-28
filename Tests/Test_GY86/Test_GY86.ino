///////////////////////////////////////////////////////////////////////////////////////////////////////
  // I2C Scanner
  // by Nick Gammon
  // http://www.gammon.com.au/forum/?id=10896
  // Modified to use Wire.h
  // Created 27th September 2010
  // Updated 18th November 2013 to use Wire library
/*  

#include <Wire.h>

byte start_address = 0;
byte end_address = 127;

void setup()
{
  byte rc;
  Wire.begin();

  Serial.begin(9600);
  Serial.println("\nI2C Scanner");

  Serial.print("Scanning I2C bus from ");
  Serial.print(start_address,DEC);  Serial.print(" to ");  Serial.print(end_address,DEC);
  Serial.println("...");

  for( byte addr  = start_address;
            addr <= end_address;
            addr++ ) {
      Wire.beginTransmission(addr);
      rc = Wire.endTransmission();

      if (addr<16) Serial.print("0");
      Serial.print(addr,HEX);
      if (rc==0) {
        Serial.print(" found!");
      } else {
        Serial.print(" "); Serial.print(rc); Serial.print("     ");
      }
      Serial.print( (addr%8)==7 ? "\n":" ");
  }

  Serial.println("\n-------------------------------\nPossible devices:");

  for( byte addr  = start_address;
            addr <= end_address;
            addr++ ) {
      Wire.beginTransmission(addr);
      rc = Wire.endTransmission();
      if (rc == 0) {
        Serial.print(addr,HEX); Serial.print(" = ");
        switch (addr) {
          case 0x50: Serial.println("AT24C32/AT24C64 - EEPROM"); break;
          case 0x68: Serial.println("DS1307"); break;
          default: Serial.println("Unknown"); break;
        }
      }
  }

  Serial.println("\ndone");
}


void loop()
{}


*/


// CoPilot  
// "Write an Arduino sketch to connect to three components connected on I2C interface. The components are 	
//  MPU6050 - 6DOF Accellerometer + gyro
//	HMC5883L - 3DOF magnetometer
//	MS5611 - Barometer and Temperature
// The sketch should connect and configure the three devices and run a loop outputting to serial the values from each of the devices"
// The MPU6050 has an I2C bypass mode that need to be configured so the HMC5883L can be read on the I2C buss. Add code to set the MPU6050 bypass mode

// Test_GY86.ino
// Read MPU6050 (accel+gyro), HMC5883L (magnetometer) and MS5611 (baro+temp) over I2C
// Outputs readings to Serial

#include <Wire.h>

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

// MS5611 calibration storage
uint16_t C[7]; // C[1]..C[6]

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

bool initMS5611() {
  ms5611Reset();
  // read calibration
  for (int i = 0; i < 7; ++i) C[i] = 0;
  for (int i = 0; i < 6; ++i) {
    C[i+1] = ms5611ReadProm(i+1);
  }
  // basic validity checks: non-zero coefficients
  for (int i = 1; i <= 6; ++i) if (C[i] == 0) return false;
  return true;
}


//Routine taken from ICM_20948_get_cal_data.ino  
// Collect data for Mahony AHRS calibration https://github.com/jremington/ICM_20948-AHRS
void collectDataForMahonyCalibration()
{
  // find gyro offsets
  Serial.println(F("Hold sensor still for gyro offset calibration ..."));
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

  // get values for calibration of acc/mag
  for (i = 0; i < acc_mag_count; i++) 
  {
    int16_t ax = readS16(ADDR_MPU6050, MPU_ACCEL_XOUT_H + 0);
    int16_t ay = readS16(ADDR_MPU6050, MPU_ACCEL_XOUT_H + 2);
    int16_t az = readS16(ADDR_MPU6050, MPU_ACCEL_XOUT_H + 4);


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

        Serial.print(mX);
        Serial.print(", ");
        Serial.print(mY);
        Serial.print(", ");
        Serial.print(mZ);
    }
    Serial.println();

    delay(200);
  }
  Serial.print(F("Done collecting"));
}


// VERY IMPORTANT!
//These are the previously determined offsets and scale factors for accelerometer and magnetometer, using ICM_20948_cal and Magneto
//The compass will NOT work well or at all if these are not correct

//Accel scale: divide by 16604.0 to normalize. These corrections are quite small and probably can be ignored.
float A_B[3] = { 574.57 , -94.66 , 2046.23 };

float A_Ainv[3][3] = {
{ 0.06152 , 0.00016 , 0.00013 },
{ 0.00016 , 0.06202 , 0.00029 },
{ 0.00013 , 0.00029 , 0.05888 }};

//Mag scale divide by 369.4 to normalize. These are significant corrections, especially the large offsets.
float M_B[3] = { 98.23 , -121.28 , 9.8 };

float M_Ainv[3][3] = {
{ 4.11223 , 0.02434 , 0.01824 },
{ 0.02434 , 4.06178 , -0.00319 },
{ 0.01824 , -0.00319 , 4.5599 }};

// local magnetic declination in degrees
float declination = -1.5;

float p[] = {1, 0, 0};  //X marking on sensor board points toward yaw = 0

#define PRINT_SPEED 1000 // ms between prints
static unsigned long lastPrint = 0; // Keep track of print time


void DoPitchRollYawLoop()
{
  static float Axyz[3], Mxyz[3]; //centered and scaled accel/mag data

  //if (millis() - lastPrint > 50)
  {
    get_scaled_IMU(Axyz, Mxyz);  //apply relative scale and offset to RAW data. UNITS are not important

    // reconcile mag and accel coordinate axes
    // Note: the illustration in the ICM_90248 data sheet implies that the magnetometer
    // Y and Z axes are inverted with respect to the accelerometer axes, verified to be correct (SJR).

    //Mxyz[1] = -Mxyz[1]; //align magnetometer with accelerometer (reflect Y and Z)
    //Mxyz[2] = -Mxyz[2];

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



void setup() {
  Serial.begin(115200);
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

  Serial.println(F("CSV: time_ms, ax(g), ay(g), az(g), gx(deg/s), gy, gz, mag_x, mag_y, mag_z, temp_C, pressure_hPa"));

  //collectDataForMahonyCalibration();
}

void loop() {

    //DoPitchRollYawLoop();
    //return;


    unsigned long t = millis();

    // MPU6050 accel & gyro
    int16_t ax = readS16(ADDR_MPU6050, MPU_ACCEL_XOUT_H + 0);
    int16_t ay = readS16(ADDR_MPU6050, MPU_ACCEL_XOUT_H + 2);
    int16_t az = readS16(ADDR_MPU6050, MPU_ACCEL_XOUT_H + 4);
    int16_t gx = readS16(ADDR_MPU6050, MPU_ACCEL_XOUT_H + 8);
    int16_t gy = readS16(ADDR_MPU6050, MPU_ACCEL_XOUT_H +10);
    int16_t gz = readS16(ADDR_MPU6050, MPU_ACCEL_XOUT_H +12);

    float ax_g = (float)ax / MPU_ACCEL_SCALE;
    float ay_g = (float)ay / MPU_ACCEL_SCALE;
    float az_g = (float)az / MPU_ACCEL_SCALE;
    float gx_dps = (float)gx / MPU_GYRO_SCALE;
    float gy_dps = (float)gy / MPU_GYRO_SCALE;
    float gz_dps = (float)gz / MPU_GYRO_SCALE;

    // HMC5883L magnetometer (X,Z,Y order)
    uint8_t magBuf[6];
    float mx = NAN, my = NAN, mz = NAN;
    if (readRegisters(ADDR_HMC5883L, HMC_DATA_X_MSB, magBuf, 6)) {
        int16_t rawX = (int16_t)((magBuf[0] << 8) | magBuf[1]);
        int16_t rawZ = (int16_t)((magBuf[2] << 8) | magBuf[3]);
        int16_t rawY = (int16_t)((magBuf[4] << 8) | magBuf[5]);
        // no scaling here (depends on gain); present raw values
        mx = rawX;
        my = rawY;
        mz = rawZ;
    }

    // MS5611: read D1 (pressure) and D2 (temperature) and compute temperature and pressure
    uint32_t D1 = ms5611ConvertRead(MS5611_CMD_CONV_D1);
    uint32_t D2 = ms5611ConvertRead(MS5611_CMD_CONV_D2);
    float temperature = NAN;
    float pressure_hPa = NAN;
    if (D1 != 0 && D2 != 0) {
        // from MS5611 datasheet
        int64_t dT = (int64_t)D2 - ((int64_t)C[5] * 256LL);
        int64_t TEMP = 2000 + (dT * (int64_t)C[6]) / 8388608LL;
        int64_t OFF = ((int64_t)C[2] * 65536LL) + (((int64_t)C[4] * dT) / 128LL);
        int64_t SENS = ((int64_t)C[1] * 32768LL) + (((int64_t)C[3] * dT) / 256LL);

        // second order compensation
        int64_t T2 = 0, OFF2 = 0, SENS2 = 0;
        if (TEMP < 2000) {
        T2 = (dT * dT) >> 31;
        OFF2 = 5 * ((TEMP - 2000) * (TEMP - 2000)) >> 1;
        SENS2 = 5 * ((TEMP - 2000) * (TEMP - 2000)) >> 2;
        if (TEMP < -1500) {
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

    // Print CSV line
    Serial.print(t); Serial.print(", ");
    Serial.print(ax_g, 3); Serial.print(", ");
    Serial.print(ay_g, 3); Serial.print(", ");
    Serial.print(az_g, 3); Serial.print(", ");
    Serial.print(gx_dps, 2); Serial.print(", ");
    Serial.print(gy_dps, 2); Serial.print(", ");
    Serial.print(gz_dps, 2); Serial.print(", ");
    if (!isnan(mx)) { Serial.print(mx, 1); } else { Serial.print("NaN"); } Serial.print(", ");
    if (!isnan(my)) { Serial.print(my, 1); } else { Serial.print("NaN"); } Serial.print(", ");
    if (!isnan(mz)) { Serial.print(mz, 1); } else { Serial.print("NaN"); } Serial.print(", ");
    if (!isnan(temperature)) { Serial.print(temperature, 2); } else { Serial.print("NaN"); } Serial.print(", ");
    if (!isnan(pressure_hPa)) { Serial.print(pressure_hPa, 2); } else { Serial.print("NaN"); }
    Serial.println();

    //delay(200); // adjust sample rate as desired
}




/*
//https://how2electronics.com/measure-pitch-roll-yaw-with-mpu6050-hmc5883l-esp32/
#include <Wire.h>

// --- DEVICE ADDRESSES ---
#define MPU6050_ADDR 0x68   // MPU6050 I2C address
#define HMC5883L_ADDR 0x1E  // HMC5883L I2C address

// --- MPU6050 REGISTERS ---
#define MPU6050_REG_ACCEL_XOUT_H 0x3B // Starting register for accelerometer readings
#define MPU6050_REG_PWR_MGMT_1   0x6B // Power management register
#define MPU6050_REG_GYRO_XOUT_H  0x43 // Starting register for gyroscope readings
#define MPU_INT_PIN_CFG  0x37  // INT pin / BYPASS config

// --- SENSITIVITY SCALES ---
#define ACCEL_SCALE 16384.0 // Accelerometer scale for ±2g (16-bit)
#define GYRO_SCALE 131.0    // Gyroscope scale for ±250°/s (16-bit)
#define MAG_SCALE 0.92      // Magnetometer scale for ±1.3 Gauss

// --- CALIBRATION OFFSETS ---
double accelOffsetX = 0, accelOffsetY = 0, accelOffsetZ = 0; // Accelerometer offsets
double gyroXOffset = 0, gyroYOffset = 0, gyroZOffset = 0;    // Gyroscope offsets
double magMinX = 0, magMaxX = 0, magMinY = 0, magMaxY = 0, magMinZ = 0, magMaxZ = 0; // Magnetometer calibration

// --- FILTER VARIABLES ---
double pitch = 0, roll = 0, yaw = 0;  // Orientation angles (degrees)
double dt = 0.02;                     // Loop time in seconds (50 Hz)

// --- KALMAN FILTER PARAMETERS ---
double Q_angle = 0.001;  // Process noise variance for the accelerometer
double Q_bias = 0.003;   // Process noise variance for the gyroscope bias
double R_measure = 0.03; // Measurement noise variance
double angle = 0, bias = 0, rate = 0; // Kalman filter state variables
double P[2][2] = {{0, 0}, {0, 0}};    // Error covariance matrix

unsigned long lastTime; // For calculating loop time

void setup() {
  // --- INITIAL SETUP ---
  Serial.begin(115200); // Initialize serial communication for debugging
  Wire.begin();         // Initialize I2C communication

  // --- SENSOR INITIALIZATION ---
  MPU6050_init();   // Initialize MPU6050
  HMC5883L_init();  // Initialize HMC5883L

  // --- SENSOR CALIBRATION ---
  calibrate_MPU6050();  // Calibrate accelerometer and gyroscope
  calibrate_HMC5883L(); // Calibrate magnetometer

  lastTime = millis(); // Set the initial time for the loop
}

void loop() {
  double ax, ay, az, gx, gy, gz; // Variables to store accelerometer and gyroscope data
  double mx, my, mz;            // Variables to store magnetometer data

  // --- READ SENSOR DATA ---
  read_MPU6050(ax, ay, az, gx, gy, gz); // Get accelerometer and gyroscope data
  read_HMC5883L(mx, my, mz);           // Get magnetometer data

  // --- CALCULATE TIME STEP ---
  unsigned long currentTime = millis();
  dt = (currentTime - lastTime) / 1000.0; // Calculate time in seconds
  if (dt == 0) dt = 0.001;               // Prevent division by zero
  lastTime = currentTime;

  // --- KALMAN FILTER FOR PITCH AND ROLL ---
  pitch = Kalman_filter(pitch, gx, atan2(-ax, sqrt(ay * ay + az * az)) * 180.0 / PI);
  roll = Kalman_filter(roll, gy, atan2(ay, az) * 180.0 / PI);

  // --- YAW CALCULATION USING MAGNETOMETER ---
  yaw = atan2(my, mx); // Calculate yaw from magnetometer readings
  //float declinationAngle = -0.1783; // Declination in radians for -10° 13'
  float declinationAngle = -0.02617993; // Declination for -1, 30'
  yaw += declinationAngle;          // Adjust for magnetic declination

  // Normalize yaw to 0-360 degrees
  if (yaw < 0) yaw += 2 * PI;
  if (yaw > 2 * PI) yaw -= 2 * PI;
  yaw = yaw * 180.0 / PI; // Convert yaw to degrees

  // --- PRINT RESULTS ---
  Serial.print("Pitch: "); Serial.print(pitch); Serial.print("°  ");
  Serial.print("Roll: "); Serial.print(roll); Serial.print("°  ");
  Serial.print("Yaw: "); Serial.print(yaw); Serial.println("°");

  delay(20); // Maintain 50 Hz loop frequency
}

// --- SENSOR INITIALIZATION FUNCTIONS ---

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

void MPU6050_init() {
  Wire.beginTransmission(MPU6050_ADDR);
  Wire.write(MPU6050_REG_PWR_MGMT_1); // Select power management register
  Wire.write(0);                      // Wake up MPU6050
  Wire.endTransmission(true);

 // Enable I2C bypass so the HMC5883L (on the MPU6050 AUX I2C/SCL/SDA)
  // can be accessed directly on the main I2C bus.
  // Set BIT1 (I2C_BYPASS_EN) in INT_PIN_CFG (0x37).
  uint8_t int_cfg = 0;
  if (readRegisters(MPU6050_ADDR, MPU_INT_PIN_CFG, &int_cfg, 1)) {
    int_cfg |= 0x02; // I2C_BYPASS_EN
    writeRegister(MPU6050_ADDR, MPU_INT_PIN_CFG, int_cfg);
    delay(10);
  }

}

void HMC5883L_init() {
  Wire.beginTransmission(HMC5883L_ADDR);
  Wire.write(0x00); // Configuration Register A
  Wire.write(0x70); // 8-average, 15 Hz default, normal measurement
  Wire.endTransmission();

  Wire.beginTransmission(HMC5883L_ADDR);
  Wire.write(0x01); // Configuration Register B
  Wire.write(0x20); // Gain = 5 (±1.3 Gauss)
  Wire.endTransmission();

  Wire.beginTransmission(HMC5883L_ADDR);
  Wire.write(0x02); // Mode Register
  Wire.write(0x00); // Continuous measurement mode
  Wire.endTransmission();
}

// --- SENSOR CALIBRATION FUNCTIONS ---
void calibrate_MPU6050() {
  Serial.println("Calibrating MPU6050...");
  double ax, ay, az, gx, gy, gz;
  int numSamples = 500;

  for (int i = 0; i < numSamples; i++) {
    read_MPU6050(ax, ay, az, gx, gy, gz);
    accelOffsetX += ax;
    accelOffsetY += ay;
    accelOffsetZ += az;
    gyroXOffset += gx;
    gyroYOffset += gy;
    gyroZOffset += gz;
    delay(10);
    if( i % 50 == 0 ) {
      Serial.print("."); // Print a dot every 50 samples to indicate progress
    }
  }

  accelOffsetX /= numSamples;
  accelOffsetY /= numSamples;
  accelOffsetZ /= numSamples;
  gyroXOffset /= numSamples;
  gyroYOffset /= numSamples;
  gyroZOffset /= numSamples;

  // Adjust for gravity on the Z-axis
  accelOffsetZ -= 1.0;

  Serial.println("MPU6050 Calibration Complete.");
}

void calibrate_HMC5883L() {
  Serial.println("Calibrating HMC5883L... Rotate the sensor in all directions.");
  double mx, my, mz;

  magMinX = magMinY = magMinZ = 1e6;
  magMaxX = magMaxY = magMaxZ = -1e6;

  unsigned long startTime = millis();
  while (millis() - startTime < 100000) { // 10 seconds for calibration
    read_HMC5883L(mx, my, mz);

    if (mx < magMinX) magMinX = mx;
    if (mx > magMaxX) magMaxX = mx;
    if (my < magMinY) magMinY = my;
    if (my > magMaxY) magMaxY = my;
    if (mz < magMinZ) magMinZ = mz;
    if (mz > magMaxZ) magMaxZ = mz;

    //Serial.print("."); // Print a dot every 100 ms to indicate progress
    Serial.print(" MinX: "); Serial.print(magMinX); Serial.print(" MaxX: "); Serial.print(magMaxX);
    Serial.print(" MinY: "); Serial.print(magMinY); Serial.print(" MaxY: "); Serial.print(magMaxY);
    Serial.print(" MinZ: "); Serial.print(magMinZ); Serial.print(" MaxZ: "); Serial.println(magMaxZ);
    delay(100);
  }
  Serial.println("\nHMC5883L Calibration Complete.");
}

// --- SENSOR READING FUNCTIONS ---
void read_MPU6050(double &ax, double &ay, double &az, double &gx, double &gy, double &gz) {
  Wire.beginTransmission(MPU6050_ADDR);
  Wire.write(MPU6050_REG_ACCEL_XOUT_H); // Starting register for Accel Readings
  Wire.endTransmission(false);
  Wire.requestFrom(MPU6050_ADDR, 14, true);

  ax = (Wire.read() << 8 | Wire.read()) / ACCEL_SCALE - accelOffsetX;
  ay = (Wire.read() << 8 | Wire.read()) / ACCEL_SCALE - accelOffsetY;
  az = (Wire.read() << 8 | Wire.read()) / ACCEL_SCALE - accelOffsetZ;
  gx = (Wire.read() << 8 | Wire.read()) / GYRO_SCALE - gyroXOffset;
  gy = (Wire.read() << 8 | Wire.read()) / GYRO_SCALE - gyroYOffset;
  gz = (Wire.read() << 8 | Wire.read()) / GYRO_SCALE - gyroZOffset;
}

void read_HMC5883L(double &mx, double &my, double &mz) {
  Wire.beginTransmission(HMC5883L_ADDR);
  Wire.write(0x03); // Starting register for magnetometer readings
  Wire.endTransmission(false);
  Wire.requestFrom(HMC5883L_ADDR, 6, true);

  int16_t x = Wire.read() << 8 | Wire.read();
  int16_t z = Wire.read() << 8 | Wire.read();
  int16_t y = Wire.read() << 8 | Wire.read();

  // Apply calibration offsets and scaling
  mx = (x - (magMinX + magMaxX) / 2) * MAG_SCALE;
  my = (y - (magMinY + magMaxY) / 2) * MAG_SCALE;
  mz = (z - (magMinZ + magMaxZ) / 2) * MAG_SCALE;
}

// --- KALMAN FILTER FUNCTION ---
double Kalman_filter(double angle, double gyroRate, double accelAngle) {
  // Predict
  rate = gyroRate - bias;
  angle += dt * rate;

  P[0][0] += dt * (dt * P[1][1] - P[0][1] - P[1][0] + Q_angle);
  P[0][1] -= dt * P[1][1];
  P[1][0] -= dt * P[1][1];
  P[1][1] += Q_bias * dt;

  // Update
  double S = P[0][0] + R_measure; // Estimate error
  double K[2];                    // Kalman gain
  K[0] = P[0][0] / S;
  K[1] = P[1][0] / S;

  double y = accelAngle - angle; // Angle difference
  angle += K[0] * y;
  bias += K[1] * y;

  double P00_temp = P[0][0];
  double P01_temp = P[0][1];

  P[0][0] -= K[0] * P00_temp;
  P[0][1] -= K[0] * P01_temp;
  P[1][0] -= K[1] * P00_temp;
  P[1][1] -= K[1] * P01_temp;

  return angle;
}
*/