void print_glcd_setup()
{
  Serial.print(F("Node: ")); 
  Serial.print(MYNODE); 
  Serial.print(F(" Freq: ")); 
  if (freq == RF12_433MHZ) Serial.print(F("433Mhz"));
  if (freq == RF12_868MHZ) Serial.print(F("868Mhz"));
  if (freq == RF12_915MHZ) Serial.print(F("915Mhz")); 
  Serial.print(" Network: "); 
  Serial.println(group);

}

void print_emontx_setup()
{
  Serial.println(F("emontx: power pulse ct1 supplyV temperature raingauge | ms_since_last_pkt")); 
}

void print_emontx_payload()
{
  Serial.print(F("emonRx "));
  Serial.print(emontx.power);
  Serial.print(F(" "));
  Serial.print(emontx.pulse);
  Serial.print(F(" "));
  Serial.print(emontx.ct1);
  Serial.print(F(" "));
  Serial.print(emontx.supplyV);
  Serial.print(F(" "));
  Serial.print(emontx.temperature);
  Serial.print(F(" "));
  Serial.print(emontx.rainGauge);
  Serial.print(F(" | "));
  Serial.println(millis()-last_emontx);
}

void print_rain_payload(unsigned long timeSinceLast)
{
	Serial.print(F("rainTx: "));
	Serial.print(rainTx.rainCount);
	Serial.print(F(" "));
	Serial.print(rainTx.transmitCount);
	Serial.print(F(" "));
	Serial.print(rainTx.supplyV);
	Serial.print(F(" | "));
	Serial.println(timeSinceLast);
}
