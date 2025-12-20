#include <Adafruit_GFX.h>
#include <Adafruit_GrayOLED.h>
#include <Adafruit_SPITFT_Macros.h>
#include <Adafruit_SPITFT.h>
#include <gfxfont.h>

#include <Adafruit_SSD1306.h>
#include <splash.h>



// #include <SPI.h>

// #include <Wire.h>

// #include <Adafruit_GFX.h>

// #include <Adafruit_SSD1306.h>
#define SCREEN_WIDTH 128 // OLED display width, in pixels
#define SCREEN_HEIGHT 32 // OLED display height, in pixels
//#define SCREEN_WIDTH 128 // OLED display width, in pixels
//#define SCREEN_HEIGHT 64 // OLED display height, in pixels
// Declaration for SSD1306 display connected using I2C

#define OLED_RESET     -1 // Reset pin # (or -1 if sharing Arduino reset pin)

#define SCREEN_ADDRESS 0x3C

Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, OLED_RESET);
// Declaration for SSD1306 display connected using software SPI:

//#define OLED_MOSI   9

//#define OLED_CLK   10

//#define OLED_DC    11

//#define OLED_CS    12

//#define OLED_RESET 13

//Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, OLED_MOSI, OLED_CLK, OLED_DC, OLED_RESET, OLED_CS);

// Add font headers from the Adafruit GFX "Fonts" folder.
// If these headers are not present in your installation adjust the paths/names
#include <Fonts/FreeSans9pt7b.h>
#include <Fonts/FreeSans12pt7b.h>
//#include <Fonts/FreeMono9pt7b.h>
#include <Fonts/FreeMono12pt7b.h>
#include <Fonts/FreeSerif9pt7b.h>
//#include <Fonts/FreeSerif12pt7b.h>
#include <Fonts/FreeSerif24pt7b.h>
// ...existing code...

void setContrast(Adafruit_SSD1306 *display, uint8_t contrast)
{
    display->ssd1306_command(SSD1306_SETCONTRAST);
    display->ssd1306_command(contrast);
    Serial.println(contrast);
}

// New helper to cycle and display different fonts
void testFonts()
{
    struct FontInfo { const GFXfont* font; const char* name; };
    const FontInfo fonts[] = {
        { &FreeSans9pt7b,  "FreeSans9pt7b"  },
        { &FreeSans12pt7b, "FreeSans12pt7b" },
 //       { &FreeMono9pt7b,  "FreeMono9pt7b"  },
        { &FreeMono12pt7b, "FreeMono12pt7b" },
        { &FreeSerif9pt7b, "FreeSerif9pt7b" },
        //{ &FreeSerif12pt7b,"FreeSerif12pt7b"},
        { &FreeSerif24pt7b,"FreeSerif24pt7b"}
    };
    const size_t count = sizeof(fonts) / sizeof(fonts[0]);

    // Example sample text to show glyph coverage and spacing
    const char* sample = "Hello 12345";

    for (size_t i = 0; i < count; ++i)
    {
        setContrast(&display, 255 - 256/count * i);

        display.clearDisplay();
        display.setTextSize(1);          // keep text size at 1 when using GFX fonts
        display.setTextColor(WHITE);
        display.setFont(fonts[i].font);
        // show font name on top using default font (revert temporarily)
        display.setCursor(0,12);
        display.setFont(NULL);
        display.println(fonts[i].name);
        // show sample using the test font beneath
        display.setFont(fonts[i].font);
        display.setCursor(0, 30);
        display.println(sample);
        display.display();
        delay(1500);
    }

    // restore default font
    display.setFont(NULL);
}

void setup()
{

    Serial.begin(9600);

    // initialize the OLED object

    if(!display.begin(SSD1306_SWITCHCAPVCC, SCREEN_ADDRESS)) 
    {
       Serial.println(F("SSD1306 allocation failed"));
       for(;;); // Don't proceed, loop forever
    }
// Uncomment this if you are using SPI

 //if(!display.begin(SSD1306_SWITCHCAPVCC)) {

 //  Serial.println(F("SSD1306 allocation failed"));

 //  for(;;); // Don't proceed, loop forever

 //}
}

void loop()
{
    display.setRotation(2); //upside down
    
    display.setTextSize(1);
    display.setFont(&FreeSerif24pt7b);
    for(int i=0; i<256; i++) 
    {
        display.clearDisplay();
        display.setTextColor(WHITE);
        setContrast(&display, i);
        display.setCursor(0, 30);
        display.print("C:"); display.print(i);
        display.display();
        delay(50);
    }

return;

    testFonts();

    // Clear the buffer.
 
    for(int i=1; i<5; i++) 
    {
        display.clearDisplay();
        display.setTextColor(WHITE);
        display.setTextSize(i);
        display.setCursor(0, 0);
        display.println("Hello");
        display.display();
        delay(2000);
    }

    return;

    // Display Text
 display.setTextSize(1);

 display.setTextColor(WHITE);

 display.setCursor(0, 28);

 display.println("Hello world!");

 display.display();

 delay(2000);

 display.clearDisplay();
// Display Inverted Text

 display.setTextColor(BLACK, WHITE); // 'inverted' text

 display.setCursor(0, 28);

 display.println("Hello world!");

 display.display();

 delay(2000);

 display.clearDisplay();
// Changing Font Size

 display.setTextColor(WHITE);

 display.setCursor(0, 24);

 display.setTextSize(2);

 display.println("Hello!");

 display.display();

 delay(2000);

 display.clearDisplay();

 // Display Numbers

 display.setTextSize(1);

 display.setCursor(0, 28);

 display.println(123456789);

 display.display();

 delay(2000);

 display.clearDisplay();
// Specifying Base For Numbers

 display.setCursor(0, 28);

 display.print("0x"); display.print(0xFF, HEX);

 display.print("(HEX) = ");

 display.print(0xFF, DEC);

 display.println("(DEC)");

 display.display();

 delay(2000);

 display.clearDisplay();
// Display ASCII Characters

 display.setCursor(0, 24);

 display.setTextSize(2);

 display.write(1);

 display.display();

 delay(2000);

 display.clearDisplay();
// Scroll full screen

 display.setCursor(0, 0);

 display.setTextSize(1);

 display.println("Full");

 display.println("screen");

 display.println("scrolling!");

 display.display();

 display.startscrollright(0x00, 0x07);

 delay(4500);

 display.stopscroll();

 delay(1000);

 display.startscrollleft(0x00, 0x07);

 delay(4500);

 display.stopscroll();

 delay(1000);

 display.startscrolldiagright(0x00, 0x07);

 delay(4500);

 display.startscrolldiagleft(0x00, 0x07);

 delay(4500);

 display.stopscroll();

 display.clearDisplay();
//draw rectangle

 display.setTextSize(1);

 display.setTextColor(WHITE);

 display.setCursor(0, 0);

 display.println("Rectangle");

 display.drawRect(0, 15, 60, 40, WHITE);

 display.display();

 delay(2000);

 display.clearDisplay();
//draw filled rectangle

 display.setCursor(0, 0);

 display.println("Filled Rectangle");

 display.fillRect(0, 15, 60, 40, WHITE);

 display.display();

 delay(2000);

 display.clearDisplay();
//draw rectangle with rounded corners

 display.setCursor(0, 0);

 display.println("Round Rectangle");

 display.drawRoundRect(0, 15, 60, 40, 8, WHITE);

 display.display();

 delay(2000);

 display.clearDisplay();
//draw circle

 display.setCursor(0, 0);

 display.println("Circle");

 display.drawCircle(20, 35, 20, WHITE);

 display.display();

 delay(2000);

 display.clearDisplay();
//draw filled circle

 display.setCursor(0, 0);

 display.println("Filled Circle");

 display.fillCircle(20, 35, 20, WHITE);

 display.display();

 delay(2000);

 display.clearDisplay();
//draw triangle

 display.setCursor(0, 0);

 display.println("Triangle");

 display.drawTriangle(30, 15, 0, 60, 60, 60, WHITE);

 display.display();

 delay(2000);

 display.clearDisplay();
//draw filled triangle

 display.setCursor(0, 0);

 display.println("Filled Triangle");

 display.fillTriangle(30, 15, 0, 60, 60, 60, WHITE);

 display.display();

 delay(2000);

 display.clearDisplay();

}





