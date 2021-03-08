//------------------------------------------------------------------------------------------------------------------------------------------------
// Fazcorp_ADS1115_devboard
//-------------------------------------------------------------------------------------------------------------------------------------------------
#include <Adafruit_ADS1015.h>
#include <Time.h>

#define SEND_PERIOD  1000

const double FACTOR[6] = { 0.1875, 0.125, 0.0625, 0.03125, 0.015625, 0.0078125 };
const int GAIN_VALUE[6] = { GAIN_TWOTHIRDS, GAIN_ONE, GAIN_TWO, GAIN_FOUR, GAIN_EIGHT, GAIN_SIXTEEN };
const int32_t SAMPLES = 100;
const uint8_t LED_PIN = 9;

Adafruit_ADS1115 g_ads1115(0x48); //, 0x48,  Adafruit_ADS1115(0x49), Adafruit_ADS1115(0x4A), Adafruit_ADS1115(0x4B) };


typedef struct {
	double mean;
	double median;
	double stdDev;
} stats_t;


long readVcc()
{
	long result;
	// Read 1.1V reference against AVcc
	ADMUX = _BV(REFS0) | _BV(MUX3) | _BV(MUX2) | _BV(MUX1);
	delay(2); // Wait for Vref to settle
	ADCSRA |= _BV(ADSC); // Convert
	while (bit_is_set(ADCSRA, ADSC));
	result = ADCL;
	result |= ADCH << 8;
	result = 1126400L / result; // Back-calculate AVcc in mV
	return result;
}

stats_t GetStats(double* samples, int nSamples)
{
	const int SKIP_READINGS = 0;		//skip the first and last of the sorted sampels as these appear to be noisy!
	stats_t stats;
	double sum = 0;
	double sumOfSquares = 0;
  double samplesCopy[SAMPLES];

  for(int i=0;i<nSamples;i++)
    samplesCopy[i] = samples[i];

	//sort the samples
	for (int i = 0; i < nSamples-1; i++) 
	{ 
		bool swapped = false; 
		for (int j = 0; j < nSamples-i-1; j++) 
		{ 
			if (samplesCopy[j] > samplesCopy[j+1]) 
			{ 
				double temp = samplesCopy[j];
				samplesCopy[j]=samplesCopy[j+1];
				samplesCopy[j+1] = temp;
				swapped = true; 
			} 
		} 

		// IF no two elements were swapped by inner loop, then break 
		if (swapped == false) 
			break; 
	} 

	//skip the top and bottom readings as there is quite a bit of noise
	for (int i = SKIP_READINGS; i < nSamples-SKIP_READINGS; ++i)
	{
		sum += samplesCopy[i];
	}

	stats.mean = sum/(nSamples-2*SKIP_READINGS);
	stats.median = samplesCopy[nSamples/2];

	for(int i=SKIP_READINGS; i< nSamples-SKIP_READINGS;i++)
	{
		sumOfSquares += (samplesCopy[i] - stats.mean) * (samplesCopy[i] - stats.mean);
	}
	stats.stdDev = sqrt( sumOfSquares/(nSamples-2*SKIP_READINGS));

	return stats;
}

double Reading(uint8_t channel, double scaleFactor, bool &noisyData )
{
	g_ads1115.setGain(GAIN_TWOTHIRDS); //shouldn't be required!
	double samples[SAMPLES];

//  uint32_t millisStart = millis();
	for (int i = 0; i < SAMPLES; i++)
	{
		samples[i] = g_ads1115.readADC_SingleEnded(channel)*scaleFactor; 
	}

//	uint32_t millisTaken = millis()- millisStart; 
//	Serial.print( F("100 sample in ms,") );
//	Serial.println( millisTaken );

	stats_t stats = GetStats(samples, SAMPLES);

	//Serial.print(F("Voltage channel,"));
	Serial.print( channel);		Serial.print(F(","));
	Serial.print( stats.median,0 );	Serial.print(F(",")); 
	Serial.print( stats.mean,0 );		Serial.print(F(",")); 
	Serial.print( stats.stdDev );
	Serial.println();

	// if(stats.stdDev > 30.0) //30 = 0.3v
	// {
	// 	noisyData = true;

	// 	Serial.print(F("voltage vals,"));
	// 	for (int i = 0; i < SAMPLES; i++)
	// 	{
	// 		Serial.print(samples[i]);
	// 		Serial.print(",");
	// 	}
	// 	Serial.println();
	// }

	return stats.median;  //median removes chance of spike reading influencing the tallies
}

double ReadingDifferential(uint8_t channel, bool &noisyData)
{
	int gain;
	double samples[SAMPLES];

	for (int g = 0; g < 6; g++ )
	{
		g_ads1115.setGain((adsGain_t)GAIN_VALUE[g]);

		for (int i = 0; i < SAMPLES; i++)
		{
			if( channel == 0)
				samples[i] = g_ads1115.readADC_Differential_0_1();
			else
				samples[i] = g_ads1115.readADC_Differential_2_3();
		}

		gain = g;

		//appears to be some noisy values resulting in selecting a low gain value.
		//use mean to try and filter out the noise at this stage.
		stats_t stats = GetStats(samples, SAMPLES);
		if (abs(stats.mean) > 1000)
			break;
	}

	for (int i = 0; i < SAMPLES; i++)
	{
		if (channel == 0)
			samples[i] = g_ads1115.readADC_Differential_0_1()*FACTOR[gain];
		else
			samples[i] = g_ads1115.readADC_Differential_2_3()*FACTOR[gain];
	}
	
	//reset to default
	g_ads1115.setGain(GAIN_TWOTHIRDS);

	//print before sorting!
	// Serial.print(F("current vals,"));
	// for (int i = 0; i < SAMPLES; i++)
	// {
	// 	Serial.print(samples[i]);
	// 	Serial.print(",");
	// }
	// Serial.println();


	stats_t stats = GetStats(samples, SAMPLES);

	//Serial.println(F("current,shuntNum,gain,factor,median,mean,stdDev"));
	Serial.print(F("Current channel,"));
	Serial.print(channel);	Serial.print(F(",")); 
	Serial.print(gain);		Serial.print(F(",")); 
	Serial.print(stats.median);	Serial.print(F(",")); 
	Serial.print(stats.mean);		Serial.print(F(",")); 
	Serial.print(stats.stdDev);
	Serial.println();

	//mean seems to be the best measure. StdDev on the 30 samples is quite high! 
	//typical for 3 banks
	//gain=5 factor=0.01 median=-5.36719 mean=-5.22786 stdDev=0.48221
	//gain=5 factor=0.01 median=-3.88281 mean=-3.51432 stdDev=1.09815
	//gain=5 factor=0.01 median=-0.06250 mean=0.00781 stdDev=0.27687

	if(stats.stdDev > 4.0) //4.0
	{
		//noisyData = true;
		Serial.print(F("current vals,"));
		for (int i = 0; i < SAMPLES; i++)
		{
			Serial.print(samples[i]);
			Serial.print(",");
		}
		Serial.println();
	}

	return stats.mean;
}

void setup()
{
	digitalWrite(LED_PIN, HIGH);

	Serial.begin(9600);

	Serial.println(F("Fazcorp_ADS1115_devboard start"));
	Serial.println(F("median,mean,stdDev"));
	


	//Serial.println(F("reading,readingNum,median,mean,stdDev"));
	//Serial.println(F("current,shuntNum,gain,factor,median,mean,stdDev"));
	//Serial.println(F("shunt,#,railv,amps,power,totalOut,totalIn,pulseOut,pulseIn"));

	g_ads1115.begin();

	delay(1000);
	digitalWrite(LED_PIN, LOW);
}


void loop()
{
	uint32_t millisStart = millis();
	
	digitalWrite(LED_PIN, HIGH);

	bool noisyData = false;

	//main rail voltage, should be around 52v. Voltage divider is 10k/500 ohms
	//double currentDiffertial = ReadingDifferential(0, noisyData ); // * 150.0 / 50.0; //shunt is 150Amps for 90mV; Bank 2
	double voltage;
	voltage = Reading(0, 0.1875, noisyData );	
	//voltage = Reading(1, 1, noisyData );
	//voltage = Reading(2, 1, noisyData );
	//voltage = Reading(3, 1, noisyData );
	//double currentSingle = Reading( 3, 1,  noisyData);

	//if( noisyData )
	//{
	//	Serial.println("High std dev on a reading. Noisy data.");
	//}

	digitalWrite(LED_PIN, LOW);

	uint32_t millisTaken = millis()- millisStart; 
	//Serial.print( F("loop_ms,") );
	//Serial.println( millisTaken );

	if( millisTaken < SEND_PERIOD )
		delay( SEND_PERIOD - millisTaken);
}
