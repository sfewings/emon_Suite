// NeoPixelFunLoop
// This example will move a trail of light around a series of pixels.  
// A ring formation of pixels looks best.  
// The trail will have a slowly fading tail.
// 
// This will demonstrate the use of the RotateRight method.
//
#include <EmonShared.h>

#include <SPI.h>
#include <RH_RF69.h>

#include <NeoPixelBus.h>
#include <PinChangeInt.h>


const byte digits[12][5]={
                    //0
                   {0b00000000, 
                    0b01111100,
                    0b10000010, 
                    0b10000010, 
                    0b01111100},
                    //1
                   {0b00000000,
                    0b00000010, 
                    0b11111110, 
                    0b01000010, 
                    0b00000000},
                    //2
                   {0b00000000,
                    0b01100010,
                    0b10010010, 
                    0b10001010, 
                    0b01000110},
                    //3
                   {0b00000000,
                    0b01101100, 
                    0b10010010, 
                    0b10010010, 
                    0b01000100},
                    //4
                   {0b00000000,
                    0b00001000, 
                    0b11111110, 
                    0b01001000, 
                    0b00111000},
                    //5
                   {0b00000000,
                    0b10001100, 
                    0b10010010, 
                    0b10010010, 
                    0b11110010},
                    //6
                   {0b00000000,
                    0b01001100, 
                    0b10010010, 
                    0b10010010, 
                    0b01111100},
                    //7
                   {0b00000000,
                    0b11000000, 
                    0b10110000, 
                    0b10001100, 
                    0b10000010},
                    //8
                   {0b00000000,
                    0b01101100, 
                    0b10010010, 
                    0b10010010, 
                    0b01101100},
                    //9
                   {0b00000000,
                    0b01111100, 
                    0b10010010, 
                    0b10010010, 
                    0b01100100},
                    //on
                   {0b11111111,
                    0b11111111, 
                    0b11111111, 
                    0b11111111, 
                    0b11111111},
                    //off
                   {0b00000000,
                    0b00000000, 
                    0b00000000, 
                    0b00000000, 
                    0b00000000},
                  };

// Singleton instance of the radio driver
RH_RF69 g_rf69;
PayloadPulse pulsePayload;


const uint8_t LDR_PIN = A0;
const uint8_t PIXEL_PIN = 3;
const uint16_t PixelCount = 256; //512 
const float MaxLightness = 0.4f; // max lightness at the head of the tail (0.5f is full bright)

const uint8_t NUM_BUTTONS = 3;
const uint8_t  g_buttons[NUM_BUTTONS] = { 15, 19, 16 };	//pin number for each input A1, A2, A6
volatile unsigned long	g_lastButtonPush[NUM_BUTTONS]	= { 0,0,0 };		//millis() value at last pulse

RgbColor g_colour = RgbColor(255, 255, 255);
volatile int g_value = 59;

volatile uint8_t g_buttonPin = 0;
volatile bool g_invertText = false;

NeoPixelBus<NeoGrbFeature, Neo800KbpsMethod> strip(PixelCount,PIXEL_PIN);


uint8_t readLDR()
{
    const int NUM_LOOPS = 10;
    long l = 0;
    for(int i=0; i <NUM_LOOPS; i++)
        l += analogRead( LDR_PIN );
    float value = l/NUM_LOOPS;
    uint8_t intensity = (uint8_t) sqrt(62.5*value);
    //Serial.print(value);Serial.print(", ");Serial.println(intensity);
    return intensity;    
}

// routine called when external interrupt is triggered
void interruptHandlerIR() 
{
    /* Pin to interrupt map, ATmega328:
    * D0-D7 = PCINT 16-23 = PCIR2 = PD = PCIE2 = pcmsk2
    * D8-D13 = PCINT 0-5 = PCIR0 = PB = PCIE0 = pcmsk0
    * A0-A5 (D14-D19) = PCINT 8-13 = PCIR1 = PC = PCIE1 = pcmsk1
    */

    g_buttonPin = PCintPort::arduinoPin;

    uint8_t button = 0;
    while(g_buttons[button] != PCintPort::arduinoPin)
    {
        if( ++button == NUM_BUTTONS)
            return;		// we only support 3 buttons though we could get an interrupt for more!
    }
    g_lastButtonPush[button] = millis();

    if( button == 0)
    {
        g_colour = RgbColor(random(255),random(255),random(255) );
        g_invertText = !g_invertText;
    }

    if( button == 1)
        g_value++;
    if( button == 2)
        g_value--;
}



void bannerDigit(int digit, int offset, uint8_t intensity = 255)
{
    RgbColor colour = RgbColor(g_colour.R*intensity/255,g_colour.G*intensity/255,g_colour.B*intensity/255);
    for(int i=0; i <5;i++)
    {
        if(offset+i >= 0 )
        {
            int index = (offset+i)*8;
            for(int b=0; b<8;b++)
            {
                RgbColor onColour = g_invertText? colour : RgbColor(0, 0, 0);
                RgbColor offColour = g_invertText? RgbColor(0, 0, 0) : colour;
                RgbColor pixelColour;

                if( (offset+i) %2 == 0)
                    pixelColour = digits[digit][i] & 1<<b ? onColour : offColour;
                else
                    pixelColour = digits[digit][i] & 1<<(7-b) ? onColour : offColour;

                strip.SetPixelColor(index+b, pixelColour);
            }
        }
    }
}

void printValue(int value, int offset = 0, uint8_t intensity = 255)
{
    bannerDigit(11, offset, intensity);
    offset += 5;
	int places = log10(abs(value));
	for (int i = 0; i <= places; i++)
    {
        int digit = value % 10;
		bannerDigit(digit, offset, intensity);
        value = value/10;
        offset += 5;
    }
    bannerDigit(11, offset, intensity);
    strip.Show();
}

void testBanner()
{

    for(int digit=0; digit<10;digit++)
    {
        for(int offset=0;offset<PixelCount/8;offset++)
        {
            bannerDigit( digit, offset, readLDR() );
            strip.Show();
            delay(20);
        }
    }

    for(int offset = 0; offset<PixelCount/8;offset++)
    {  bannerDigit( 0, offset+0, readLDR());
        bannerDigit( 1, offset+5, readLDR());
        bannerDigit( 2, offset+10, readLDR());
        bannerDigit( 3, offset+15, readLDR() );
        bannerDigit( 4, offset+20, readLDR() );
        bannerDigit( 5, offset+25, readLDR() );
        bannerDigit( 6, offset+30, readLDR() );
        bannerDigit( 7, offset+35, readLDR() );
        bannerDigit( 8, offset+40, readLDR() );
        bannerDigit( 9, offset+45, readLDR() );
        strip.Show();
        delay(20);
    }
}

void setup()
{
    Serial.begin(9600);

	if (!g_rf69.init())
		Serial.println("rf69 init failed");
	if (!g_rf69.setFrequency(915.0))
		Serial.println("rf69 setFrequency failed");
	// The encryption key has to be the same as the one in the client
	uint8_t key[] = { 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
					0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08};
	g_rf69.setEncryptionKey(key);
	g_rf69.setHeaderId(DISPLAY_NODE);

	Serial.print("RF69 initialise node: ");
	Serial.print(DISPLAY_NODE);
	Serial.println(" Freq: 915MHz");
	EmonSerial::PrintPulsePayload(NULL);
    memset(&pulsePayload, 0, sizeof(PayloadPulse));

    strip.Begin();
    strip.Show();

    for(uint8_t button = 0; button < NUM_BUTTONS; button++)
    {
        attachPinChangeInterrupt(g_buttons[button], interruptHandlerIR, RISING);
    }
}


void loop()
{
    // if(millis()-g_lastButtonPush[0] < 100)
    // {
        
    // }

	//--------------------------------------------------------------------------------------------
	// 1. On RF recieve
	//--------------------------------------------------------------------------------------------	
	volatile uint8_t *data = NULL;
	uint8_t buf[66];
	int node_id= -1;
	byte len = 0;

	if (g_rf69.available())
	{
		len = RH_RF69_MAX_MESSAGE_LEN;  //ASSERT( len <= sizeof(buf));
		if (g_rf69.recv(buf, &len))
		{
			node_id = g_rf69.headerId();
		}
	}

	if( node_id != -1)
	{
		if (node_id == PULSE_JEENODE && len == sizeof(PayloadPulse)) // === PULSE NODE ====
		{
			pulsePayload = *(PayloadPulse*)buf;							// get payload data

			EmonSerial::PrintPulsePayload(&pulsePayload);				// print data to serial
		}
    }

    printValue((unsigned int) pulsePayload.power[2], 0, readLDR());
    //printValue(pulsePayload.power[1], 32*8, readLDR());
    
    
    delay(10);
    //printValue(g_value,3, readLDR());
    //Serial.println(g_value);Serial.print(","); Serial.println(g_buttonPin);
}
