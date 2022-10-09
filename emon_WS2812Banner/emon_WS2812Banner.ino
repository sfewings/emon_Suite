// NeoPixelFunLoop
// This example will move a trail of light around a series of pixels.  
// A ring formation of pixels looks best.  
// The trail will have a slowly fading tail.
// 
// This will demonstrate the use of the RotateRight method.
//

#include <NeoPixelBus.h>


const uint16_t PixelCount = 512; //241; // make sure to set this to the number of pixels in your strip
const uint16_t PixelPin = 2;  // make sure to set this to the correct pin, ignored for Esp8266
const float MaxLightness = 0.4f; // max lightness at the head of the tail (0.5f is full bright)

NeoPixelBus<NeoGrbFeature, Neo800KbpsMethod> strip(PixelCount,PixelPin);

void drawDigitOne(int digit, int offset)
{
byte digits[10][5]={
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
                  };

    RgbColor color = RgbColor(random(255),random(255),random(255));
    for(int i=0; i <5;i++)
    {
        if(offset+i >= 0 )
        {
            int index = (offset+i)*8;
            for(int b=0; b<8;b++)
            {
                RgbColor pixelColour;
                if( (offset+i) %2 == 0)
                    pixelColour = digits[digit][i] & 1<<b ? color : RgbColor(0, 0, 0);
                else
                    pixelColour = digits[digit][i] & 1<<(7-b) ? color : RgbColor(0, 0, 0);

                strip.SetPixelColor(index+b, pixelColour);
            }
        }
    }
}


void setup()
{
    strip.Begin();
    strip.Show();
}


void loop()
{
    for(int digit=0; digit<10;digit++)
    {
        for(int offset=0;offset<PixelCount/8;offset++)
        {
            drawDigitOne( digit, offset );
            strip.Show();
            delay(20);
        }
    }

    for(int offset = 0; offset<PixelCount/8;offset++)
    {  drawDigitOne( 0, offset+0);
        drawDigitOne( 1, offset+5);
        drawDigitOne( 2, offset+10);
        drawDigitOne( 3, offset+15 );
        drawDigitOne( 4, offset+20 );
        drawDigitOne( 5, offset+25 );
        drawDigitOne( 6, offset+30 );
        drawDigitOne( 7, offset+35 );
        drawDigitOne( 8, offset+40 );
        drawDigitOne( 9, offset+45 );
        strip.Show();
        delay(20);
    }
}
