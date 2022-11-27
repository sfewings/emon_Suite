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

# define NUM_FONTS 3

const byte digits[NUM_FONTS][10][5]=
{
    {   //5*8 font
                            {0x3E,0x51,0x49,0x45,0x3E}, //0
                            {0x00,0x01,0x7F,0x21,0x00}, //1
                            {0x31,0x49,0x45,0x43,0x21}, //2
                            {0x46,0x69,0x51,0x41,0x42}, //3
                            {0x04,0x7F,0x24,0x14,0x0C}, //4
                            {0x4E,0x51,0x51,0x51,0x72}, //5
                            {0x06,0x49,0x49,0x29,0x1E}, //6
                            {0x60,0x50,0x48,0x47,0x40}, //7
                            {0x36,0x49,0x49,0x49,0x36}, //8
                            {0x3C,0x4A,0x49,0x49,0x30} //9    
    },
    {  //5*8 but one pixel higher
                            {0x7C,0xA2,0x92,0x8A,0x7C}, //0
                            {0x00,0x02,0xFE,0x42,0x00}, //1
                            {0x62,0x92,0x8A,0x86,0x42}, //2
                            {0x8C,0xD2,0xA2,0x82,0x84}, //3
                            {0x08,0xFE,0x48,0x28,0x18}, //4
                            {0x9C,0xA2,0xA2,0xA2,0xE4}, //5
                            {0x0C,0x92,0x92,0x52,0x3C}, //6
                            {0xC0,0xA0,0x90,0x8E,0x80}, //7
                            {0x6C,0x92,0x92,0x92,0x6C}, //8
                            {0x78,0x94,0x92,0x92,0x60} //9        
    },
    {   //4*8 font
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
                    0b01100100}
                  } 
};

const uint8_t g_fontWidth[NUM_FONTS] = {5,5,4};

// Singleton instance of the radio driver
RH_RF69 g_rf69;
PayloadPulse pulsePayload;


const uint8_t LDR_PIN = A0;
const uint8_t PIXEL_PIN = 3;
const uint16_t NUM_PIXELS = 256; //512 
const float MaxLightness = 0.4f; // max lightness at the head of the tail (0.5f is full bright)
const uint8_t LED_PIN = A3;  //Pin 17
const uint8_t NUM_BUTTONS = 2;
const uint8_t  g_buttons[NUM_BUTTONS] = { A1, A2 };	//pin number for each input A1, A2.  Pins 15 & 16

volatile unsigned long	g_lastButtonPush[NUM_BUTTONS]	= { 0,0 };		//millis() value at last pulse

RgbColor g_colour = RgbColor(255, 255, 255);
volatile int g_value = 0;

volatile uint8_t g_buttonPin = 0;
volatile bool g_invertText = false;
volatile uint8_t g_fontIndex = 0;

NeoPixelBus<NeoGrbFeature, Neo800KbpsMethod> strip(NUM_PIXELS,PIXEL_PIN);


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
    unsigned long msSinceLastButton = millis()- g_lastButtonPush[button];
    g_lastButtonPush[button] = millis();

    if(msSinceLastButton <20)
        return;     //button debounce

    if( button == 0)
    {
        g_fontIndex = ((g_fontIndex+1) % NUM_FONTS);
    }

    if( button == 1)
    {
        g_colour = RgbColor(random(255),random(255),random(255) );
        if(msSinceLastButton <250)
            g_invertText = !g_invertText;
    }
}



void bannerDigit(int digit, int offset, RgbColor colour)
{
    if(digit <0 || digit>9)
        return;

    for(int i=0; i <5;i++)
    {
        if(offset+i >= 0 )
        {
            int index = (offset+i)*8;
            for(int b=0; b<8;b++)
            {
                RgbColor onColour = g_invertText? RgbColor(0, 0, 0) : colour;
                RgbColor offColour = g_invertText? colour : RgbColor(0, 0, 0);
                RgbColor pixelColour;
                if( (offset+i) %2 == 0)
                    pixelColour = digits[g_fontIndex][digit][i] & 1<<b ? onColour : offColour;
                else
                    pixelColour = digits[g_fontIndex][digit][i] & 1<<(7-b) ? onColour : offColour;

                strip.SetPixelColor(index+b, pixelColour);
            }
        }
    }
}

void printValue(int value, int offset = 0, uint8_t intensity = 255)
{
    RgbColor colour = RgbColor(g_colour.R*intensity/255,g_colour.G*intensity/255,g_colour.B*intensity/255);

    for(uint16_t pixel=0; pixel <NUM_PIXELS; pixel++)
    {
        strip.SetPixelColor(pixel, (g_invertText?colour:RgbColor(0, 0, 0)));
    }

    offset += g_fontWidth[g_fontIndex]+1;
	int places = log10(abs(value));
	for (int i = 0; i <= places; i++)
    {
        int digit = value % 10;
		bannerDigit(digit, offset, colour);
        value = value/10;
        offset += g_fontWidth[g_fontIndex]+1;
    }
    strip.Show();
}

void testBanner()
{

    for(int digit=0; digit<10;digit++)
    {
        for(int offset=0;offset<NUM_PIXELS/8;offset++)
        {
            bannerDigit( digit, offset, readLDR() );
            strip.Show();
            delay(20);
        }
    }

    for(int offset = 0; offset<NUM_PIXELS/8;offset++)
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

    pinMode( LED_PIN, OUTPUT);
    digitalWrite(LED_PIN, LOW);


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
	//--------------------------------------------------------------------------------------------
	// 1. On RF recieve
	//--------------------------------------------------------------------------------------------	
	volatile uint8_t *data = NULL;
	uint8_t buf[66];
	int node_id= -1;
	byte len = 0;

	if (g_rf69.available())
	{
        digitalWrite(LED_PIN, HIGH);
        
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
    digitalWrite(LED_PIN, LOW);

    printValue((unsigned int) pulsePayload.power[2], 0, readLDR());
    delay(10);
}
