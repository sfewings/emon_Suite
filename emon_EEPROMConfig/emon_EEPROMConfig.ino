//simple configuration utility for setting the EEPROM for new nodes
//sets the relay number and the subnode
#include <EmonEEPROM.h>

#define VERSION "[Emon_EEPROMConfig.1]\n"           // keep in sync with the above
#define LED_PIN     13
#define STACK_SIZE  10


static void activityLed (byte on) 
{
    pinMode(LED_PIN, OUTPUT);
    digitalWrite(LED_PIN, !on);
}

static void printOneChar (char c) 
{
    Serial.print(c);
}

static void showString (PGM_P s) {
    for (;;) {
        char c = pgm_read_byte(s++);
        if (c == 0)
            break;
        if (c == '\n')
            printOneChar('\r');
        printOneChar(c);
    }
}

static void displayVersion () {
    showString(PSTR(VERSION));
}

static EEPROMSettings settings;
static char cmd;
static word value;
static byte stack[STACK_SIZE + 4], top, sendLen, dest;
static byte testCounter;


// - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

const char helpText1[] PROGMEM =
	"\n"
	"Available commands:\n"
	"  <nn> r     - set relay number (0..8.  0 is no relay)\n"
	"  <n> s      - set subnode number for nodes with multiple subnodes (disp and temp)\n"
	"  <nn> a     - add node <nn> to list of nodes to relay\n"
	"  <nn> d     - delete node <nn> from list of nodes to relay\n"
	"  n          - print node IDs\n"
	"  p          - print current settings\n"
	"  x          - reset all\n"
	"  <n> l      - turn LED pin 13 on/off\n"
;

static void showHelp () 
{
    showString(helpText1);
}

static void handleInput (char c) {
    if ('0' <= c && c <= '9') {
        value = 10 * value + c - '0';
        return;
    }

    if (c == ',') {
        if (top < sizeof stack)
            stack[top++] = value; // truncated to 8 bits
        value = 0;
        return;
    }

    if ('a' <= c && c <= 'z') {
        showString(PSTR("> "));
        for (byte i = 0; i < top; ++i) {
            Serial.print((word) stack[i]);
            printOneChar(',');
        }
        Serial.print(value);
        Serial.println(c);
    }

    switch (c)
		{

      case 'r': // set relay number
				if (value > 8)
						Serial.println("Invalid relay number. Set 0..8");
					else
					{
						settings.relayNumber = value;
						EmonEEPROM::WriteEEPROMSettings(settings);
						EmonEEPROM::PrintEEPROMSettings(Serial, settings);
					}
					break;

      case 's': // set subnode number
				if (value > MAX_SUBNODES)
				{
					Serial.print("Invalid subnode number. Set 0..");
					Serial.println(MAX_SUBNODES);
				}
				else
				{
					settings.subnode = value;
					EmonEEPROM::WriteEEPROMSettings(settings);
					EmonEEPROM::PrintEEPROMSettings(Serial, settings);
					break;
				}

			case 'a': // add node to list of nodes to relay
				settings.relayNodes |= ((long)1) << value;
				EmonEEPROM::WriteEEPROMSettings(settings);
				EmonEEPROM::PrintEEPROMSettings(Serial, settings);
				break;

			case 'd': // delete node from list of nodes to relay
				settings.relayNodes &= ~((long)1 << value);
				EmonEEPROM::WriteEEPROMSettings(settings);
				EmonEEPROM::PrintEEPROMSettings(Serial, settings);
				break;

			case 'n': //print node IDs
			{
				for (long l = 0; l < 32; l++)
				{
					if (EmonEEPROM::PrintNode(Serial, l))
					{
						Serial.print("=");
						Serial.print(l);
						Serial.println();
					}
				}
				break;
			}
			case 'x': // reset all
				memset(&settings, 0, sizeof(settings));
				EmonEEPROM::WriteEEPROMSettings(settings);
				EmonEEPROM::PrintEEPROMSettings(Serial, settings);
				break;


      case 'p': // print the current settings
					EmonEEPROM::ReadEEPROMSettings(settings);
					EmonEEPROM::PrintEEPROMSettings(Serial, settings);
          break;

      case 'l': // turn activity LED on or off
          activityLed(value);
          break;

      default:
          showHelp();
      }

    value = top = 0;
}

static void displayASCII (const byte* data, byte count) {
    for (byte i = 0; i < count; ++i) {
        printOneChar(' ');
        char c = (char) data[i];
        printOneChar(c < ' ' || c > '~' ? '.' : c);
    }
    Serial.println();
}

void setup () 
{
    Serial.begin(9600);
    Serial.println();
    displayVersion();

		if(! EmonEEPROM::ReadEEPROMSettings(settings))
		{
			Serial.println(F("No EEPROM settings found. Defaults set."));
			EmonEEPROM::WriteEEPROMSettings(settings);
		}
		EmonEEPROM::PrintEEPROMSettings(Serial, settings);

    showHelp();
}

void loop () 
{
    if (Serial.available())
        handleInput(Serial.read());
}
