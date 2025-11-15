// emon_SevConTHrottleDisplay.ino
// Listens to packets from the SevCon controller and displays RPM speed, direction and controller temperature info
// on a ring of NeoPixel LEDs.  The display brightness is adjusted based on ambient light
// Pulses a red glow when the motor is idle
// A ring formation of pixels looks best.  
#include <EmonShared.h>

#include <SPI.h>
#include <RH_RF69.h>
#include <NeoPixelBus.h>

//#define HOUSE_BANNER
#define BOAT_BANNER
#ifdef HOUSE_BANNER
    #define NETWORK_FREQUENCY 915.0
#elif defined(BOAT_BANNER)
    #define NETWORK_FREQUENCY 914.0
#endif

const uint8_t LDR_PIN = A0;
const uint8_t VOLTAGE_MEASURE_PIN = A5;
const uint8_t PIXEL_PIN = 3;
const uint8_t LED_PIN = 9;  //LED on Moteino. Note that the PCB has an LED space at A3;  //Pin 17
const uint16_t NUM_PIXELS = 60;

NeoPixelBus<NeoGrbFeature, Neo800KbpsMethod> strip(NUM_PIXELS,PIXEL_PIN);

RH_RF69 g_rf69;
PayloadSevCon       g_payloadSevCon;

uint8_t readLDR()
{
    const uint8_t BUF_SIZE = 10;
    static uint16_t buf[BUF_SIZE];
    static uint8_t idx = 0;
    static uint8_t count = 0;

    // single analog read per call
    int raw = analogRead(LDR_PIN); // 0..1023
    raw = sqrt(250.0*raw); // approx. linearize response
    // compute current average of stored values (before inserting new)
    uint32_t sum = 0;
    for (uint8_t i = 0; i < count; ++i) 
        sum += buf[i];
    uint16_t avgRaw = (count == 0) ? raw : (uint16_t)(sum / count);

    // despike: allow +/-20% around current average
    // if (count > 0)
    // {
    //     int lower = avgRaw - (avgRaw * 20) / 100;
    //     int upper = avgRaw + (avgRaw * 20) / 100;
    //     if (lower < 0) lower = 0;
    //     if (upper > 1023) upper = 1023;

    //     if (raw < lower || raw > upper)
    //     {
    //         // treat as spike -> use current average instead of raw
    //         raw = avgRaw;
    //     }
    // }

    // store accepted reading in circular buffer
    buf[idx] = (uint16_t)raw;
    idx = (idx + 1) % BUF_SIZE;
    if (count < BUF_SIZE) ++count;

    // compute average of last up to 10 readings
    sum = 0;
    for (uint8_t i = 0; i < count; ++i) 
        sum += buf[i];
    avgRaw = (uint16_t)(sum / count);

    // scale 0..1023 -> 0..255
    uint8_t intensity = (uint8_t)((avgRaw * 255UL) / 1023UL);
    return intensity;
}


// --- new helper to rotate a single lit pixel ---
// direction: 1 = clockwise (increasing index), -1 = counterclockwise
void updateRotatingPixel(RgbColor inColour, unsigned long stepMs, int direction = 1, uint8_t intensity = 255, uint16_t onCount = 1)
{
    static int currentIndex = 0;
    static int previousIndex = -1;
    static unsigned long lastMove = 0;

    // clamp onCount to valid range
    uint16_t count = (onCount == 0) ? 1 : min(onCount, NUM_PIXELS);

    RgbColor col = RgbColor(inColour.R*intensity/255,inColour.G*intensity/255,inColour.B*intensity/255);

    int dir = (direction >= 0) ? 1 : -1;

    unsigned long now = millis();
    Serial.print(now - lastMove); Serial.print(",");
    if (now - lastMove < stepMs)
        return; // not time to move yet

    Serial.println(stepMs);

    lastMove = now;

    // clear previous block of pixels
    if (previousIndex >= 0)
    {
        for (uint16_t i = 0; i < count; ++i)
        {
            int idx = (previousIndex + i) % NUM_PIXELS;
            strip.SetPixelColor(idx, RgbColor(0,0,0));
        }
    }

    // set current block of pixels
    for (uint16_t i = 0; i < count; ++i)
    {
        int idx = (currentIndex + i + NUM_PIXELS) % NUM_PIXELS;
        strip.SetPixelColor(idx, col);
    }
    strip.Show();

    previousIndex = currentIndex;
    currentIndex = (currentIndex + dir + NUM_PIXELS) % NUM_PIXELS;
}

// --- new non-blocking pulse helper ---
// colour: base colour to pulse
// pulseTime: total time for one full up-and-down cycle in milliseconds
// This function sets pixel state and returns immediately; call it frequently from loop().
void pulseAllPixels(RgbColor colour, unsigned long pulseTime, uint8_t intensityLDR=255)
{
    static unsigned long startTime = 0;
    static bool started = false;

    if (!started)
    {
        startTime = millis();
        started = true;
    }

    if (pulseTime == 0)
        pulseTime = 1; // avoid div-by-zero

    unsigned long now = millis();
    unsigned long elapsed = now - startTime;
    unsigned long phase = elapsed % pulseTime;

    // triangular wave: 0 -> 255 -> 0 over pulseTime
    unsigned long half = pulseTime / 2;
    uint8_t intensity;
    if (phase <= half)
    {
        // rising edge: map [0..half] -> [0..255]
        unsigned long denom = (half == 0) ? 1 : half;
        intensity = (uint8_t)(((phase * 255UL) / denom) * intensityLDR / 255UL);
    }
    else
    {
        // falling edge: map (half..pulseTime) -> (255..0)
        unsigned long d = phase - half;
        unsigned long denom = (pulseTime - half == 0) ? 1 : (pulseTime - half);
        intensity = (uint8_t)((255UL - ((d * 255UL) / denom))* intensityLDR / 255UL);
    }

    // scale colour by intensity and set all pixels
    RgbColor col = RgbColor((colour.R * intensity) / 255, (colour.G * intensity) / 255, (colour.B * intensity) / 255);
    for (uint16_t i = 0; i < NUM_PIXELS; ++i)
    {
        strip.SetPixelColor(i, col);
    }
    strip.Show();
}

void turnAllOnTest()
{
    for (uint16_t i = 0; i < NUM_PIXELS; ++i)
    {
        strip.SetPixelColor(i, RgbColor(255,255,255));
    }
    strip.Show();
}

void testRotatingPixelsAndPulse()
{
    uint8_t intensity = readLDR();
    //Serial.print(F("LDR Intensity=")); Serial.println(intensity);

    unsigned long mode = millis() %60000;

    if( mode > 30000 ) 
    {
        //rotatating pixels
        unsigned long time = millis() % 30000;
        int direction = 1;
        int speed = time / 1000; // 0-599
        if (speed > 15) 
        {
            direction = -1;
            speed = 30 - speed;
        }
//        Serial.println(speed);
        //speed = speed*2;
        RgbColor colour = RgbColor(0,255,0); // default green
        switch ((millis() %6000)/1000)
        {
            case 0:
                colour = RgbColor(0,255,0); // green
                break;
            case 1:
                colour = RgbColor(255,255,0); // yellow 
                break;
            case 2:
                colour = RgbColor(255,0,0); // red
                break;
            case 3:
                colour = RgbColor(128,0,128); // purple 
                break;
            case 4:
                colour = RgbColor(0,0,255); // blue
                break;  
            case 5:
                colour = RgbColor(0,255,255); // cyan
                break;
            default:
                colour = RgbColor(255,255,255); // white
                break;
        }
       
        // --- call the rotating pixel helper ---
        // Examples:
        // updateRotatingPixel(RgbColor(255,0,0), 100, 1);   // red, 100ms step, clockwise, 1 pixel
        // updateRotatingPixel(RgbColor(0,255,0), 200, -1, 255, 5);  // green, 200ms step, counterclockwise, intensity 255, 5 pixels

        uint16_t numPixelsLit = map( abs(intensity), 0, 255, 1, 10);
        numPixelsLit = constrain(numPixelsLit, 1, 10);

        updateRotatingPixel(colour, speed, direction, intensity, numPixelsLit);   // blue, step 'speed', 3 pixels lit per step
    }
    else 
    {
        //pulse all pixels red
        pulseAllPixels(RgbColor(255,0,0), 2000, intensity); // red, 2 second pulse
    }
}

void setup()
{
    pinMode( LED_PIN, OUTPUT);
    digitalWrite(LED_PIN, HIGH);

    Serial.begin(9600);
    Serial.println(F("SevCon Throttle Display Starting"));

	if (!g_rf69.init())
		Serial.println("rf69 init failed");
	if (!g_rf69.setFrequency(NETWORK_FREQUENCY))
		Serial.println("rf69 setFrequency failed");
	// The encryption key has to be the same as the one in the client
	uint8_t key[] = { 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
					0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08};
	g_rf69.setEncryptionKey(key);
	g_rf69.setHeaderId(BASE_JEENODE);    //doesn't matter which node as we don't transmit
    g_rf69.setIdleMode(RH_RF69_OPMODE_MODE_SLEEP);
	Serial.print(F("RF69 initialised Freq: "));Serial.print(NETWORK_FREQUENCY,1); Serial.println("MHz");
  
    memset( &g_payloadSevCon,0, sizeof(PayloadSevCon));

    strip.Begin();
    strip.Show();

    digitalWrite(LED_PIN, LOW);
}


void loop()
{
    pulseAllPixels(RgbColor(255,0,0), 2000, 255U); // red, 2 second pulse
    return;
    
    testRotatingPixelsAndPulse();
    return;

    static unsigned long lastReceivedFromSevCon = millis();

    if (g_rf69.available())
    {
        digitalWrite(LED_PIN, HIGH);
        byte len = RH_RF69_MAX_MESSAGE_LEN;
        uint8_t buf[RH_RF69_MAX_MESSAGE_LEN];
        int node_id= -1;
        
        if (g_rf69.recv(buf, &len))
        {
            node_id = g_rf69.headerId();
        }

        if (node_id == SEVCON_CAN_NODE && len == sizeof(PayloadSevCon)) // === SEVCON NODE ====
        {
            g_payloadSevCon = *(PayloadSevCon*)buf;							// get payload data
            EmonSerial::PrintSevConPayload(&g_payloadSevCon);				// print data to serial
            lastReceivedFromSevCon = millis();
        }
        digitalWrite(LED_PIN, LOW);
    }


    if( lastReceivedFromSevCon + 2000 < millis() )
    {
        // we have not received data for 2 seconds - clear display
        strip.ClearTo(RgbColor(0,0,0));
        strip.Show();
        return;
    }

    uint8_t intensity = readLDR();
 
    if( abs(g_payloadSevCon.rpm) <5 )
    {
        //pulse all the pixels if the motor is idle
        pulseAllPixels(RgbColor(255,0,0), 2000, intensity); // red, 2 second pulse
    }
    else
    {
        //Display a rotating pixel if the motor is running
        //Rotation speed is proportional to rpm
        //Rotation direction is based on sign of rpm
        //Number of pixels lit (0..10) is based on LDR intensity
        //Overall pixel intensity is based on LDR intensity
        //Colour is based on controller temperature

        int speed = map( abs(g_payloadSevCon.rpm), 0, 1800, 20, 1); // map 0-2000rpm to 50-1ms step
        speed = constrain(speed, 1, 20);
        int direction = (g_payloadSevCon.rpm >0) ? 1 : -1;
        uint16_t numPixelsLit = map( abs(intensity), 0, 255, 1, 10);
        numPixelsLit = constrain(numPixelsLit, 1, 10);
        Serial.print(F("RPM:"));Serial.print(g_payloadSevCon.rpm);Serial.print(F("Speed:"));Serial.print(speed);Serial.println();
        RgbColor colour = RgbColor(0,255,0); // default green
        switch( g_payloadSevCon.controllerTemperature )
        {
            case -40 ... 40:
                colour = RgbColor(0,255,0); // green
                break;
            case 41 ... 60:
                colour = RgbColor(255,255,0); // yellow
                break;
            case 61 ... 80:
                colour = RgbColor(255,0,0); // red
                break;
            default:
                colour = RgbColor(128,0,128); // purple
                break;
        }

        updateRotatingPixel(colour, speed, direction, intensity, numPixelsLit);
    }
}
