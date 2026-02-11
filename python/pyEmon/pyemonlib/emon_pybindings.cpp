#include <pybind11/pybind11.h>
#include <pybind11/numpy.h>

#define __linux__
#define MQTT_LIB

//Note:- may require full path when building with pyproject.toml
#include "../../../EmonShared/EmonShared.cpp"

namespace py = pybind11;

PYBIND11_MODULE(emonSuite, m) {
    m.doc() = "pybind11 plugin for EmonSuite"; // optional module docstring

    //CONSTANTS
    m.attr("MAX_SUBNODES")              = py::int_(MAX_SUBNODES);       //Maximum number of disp and temp nodes supported
    m.attr("MAX_WATER_SENSORS")         = py::int_(MAX_WATER_SENSORS); 	//Maximum number of water pulse and water height metres
    m.attr("PULSE_MAX_SENSORS")         = py::int_(PULSE_MAX_SENSORS); 	//number of pins and hence, readings on the pulse Jeenode
    m.attr("MAX_TEMPERATURE_SENSORS")   = py::int_(MAX_TEMPERATURE_SENSORS); 	//maximum number of temperature sensors on the temperature_JeeNode  
    m.attr("HWS_TEMPERATURES")          = py::int_(HWS_TEMPERATURES); 	//number of temperature readings from the hot water system
    m.attr("HWS_PUMPS")                 = py::int_(HWS_PUMPS);          //number of pumps from the hot water system
    m.attr("BATTERY_SHUNTS")            = py::int_(BATTERY_SHUNTS); 	//number of battery banks in the system. Each with a shunt for measuring current in and out
    m.attr("MAX_VOLTAGES")              = py::int_(MAX_VOLTAGES);   	//number of voltage measurements made on the battery monitoring system
    m.attr("MAX_BMS_CELLS")             = py::int_(MAX_BMS_CELLS);   	//number of cell voltages returned from the BMS

    //Relay base payload
    py::class_<PayloadRelay> payloadRelay(m, "PayloadRelay");
    payloadRelay.def_readwrite("relay", &PayloadRelay::relay, "OR of all the relay units that have transmitted this packet. 0=original node transmit");

    //PayloadRain
    py::class_<PayloadRain, PayloadRelay> payloadRain(m, "PayloadRain");
    payloadRain.def(py::init<>());
    payloadRain.def_readwrite("rainCount", &PayloadRain::rainCount, "The count from the rain gauge" );
    payloadRain.def_readwrite("transmitCount", &PayloadRain::transmitCount, "Increment for each time the rainCount is transmitted. When rainCount is changed, this value is 0");
    payloadRain.def_readwrite("temperature", &PayloadRain::temperature, "temperature in 100ths of degrees");
    payloadRain.def_readwrite("supplyV", &PayloadRain::supplyV, "supply voltage in mV");

    //PayloadDisp
    py::class_<PayloadDisp, PayloadRelay> payloadDisp(m, "PayloadDisp");
    payloadDisp.def(py::init<>());
    payloadDisp.def_readwrite("subnode", &PayloadDisp::subnode, "allow multiple Display nodes on the network" );
    payloadDisp.def_readwrite("temperature", &PayloadDisp::temperature, "temperature in 100ths of degrees");

    //PayloadPulse
    py::class_<PayloadPulse, PayloadRelay> payloadPulse(m, "PayloadPulse");
    payloadPulse.def(py::init<>());
    payloadPulse.def_readwrite("subnode", &PayloadPulse::subnode, "allow multiple Pulse nodes on the network" );
    payloadPulse.def_property("power", [](PayloadPulse &payload)->pybind11::array {
            auto dtype = pybind11::dtype(pybind11::format_descriptor<int>::format());
            return pybind11::array(dtype, { PULSE_MAX_SENSORS }, { sizeof(int) }, payload.power, nullptr);
            }, [](PayloadPulse& payload) {});	//current power reading
    payloadPulse.def_property("pulse", [](PayloadPulse &payload)->pybind11::array {
            auto dtype = pybind11::dtype(pybind11::format_descriptor<unsigned long>::format());
            return pybind11::array(dtype, { PULSE_MAX_SENSORS }, { sizeof(unsigned long) }, payload.pulse, nullptr);
            }, [](PayloadPulse& payload) {});	//cummulative pulse reading
    payloadPulse.def_readwrite("supplyV", &PayloadPulse::supplyV, "unit supply milli voltage");


    //PayloadTemperature
    py::class_<PayloadTemperature, PayloadRelay> payloadTemp(m, "PayloadTemperature");
    payloadTemp.def(py::init<>());
    payloadTemp.def_readwrite("subnode", &PayloadTemperature::subnode, "allow multiple temperature nodes on the network");
    payloadTemp.def_readwrite("supplyV", &PayloadTemperature::supplyV, "supplyV in mV" );
    payloadTemp.def_readwrite("numSensors", &PayloadTemperature::numSensors, "number of temperature sensor readings" );
    payloadTemp.def_property("temperature", [](PayloadTemperature &payload)->pybind11::array {
            auto dtype = pybind11::dtype(pybind11::format_descriptor<int>::format());
            return pybind11::array(dtype, { MAX_TEMPERATURE_SENSORS }, { sizeof(int) }, payload.temperature, nullptr);
            }, [](PayloadTemperature& payload) {});	//temperature in 100th of degrees

    //PayloadHWS
    py::class_<PayloadHWS, PayloadRelay> payloadHWS(m, "PayloadHWS");
    payloadHWS.def(py::init<>());
	payloadHWS.def_property("temperature", [](PayloadHWS &payload)->pybind11::array {
            auto dtype = pybind11::dtype(pybind11::format_descriptor<byte>::format());
            return pybind11::array(dtype, { HWS_TEMPERATURES }, { sizeof(byte) }, payload.temperature, nullptr);
            }, [](PayloadHWS& payload) {});	//temperature in 100th of degrees
	payloadHWS.def_property("pump", [](PayloadHWS &payload)->pybind11::array {
            auto dtype = pybind11::dtype(pybind11::format_descriptor<bool>::format());
            return pybind11::array(dtype, { HWS_PUMPS }, { sizeof(bool) }, payload.pump, nullptr);
            }, [](PayloadHWS& payload) {});	//temperature in 100th of degrees

    //PayloadBase
    py::class_<PayloadBase, PayloadRelay> payloadBase(m, "PayloadBase");
    payloadBase.def(py::init<>());
    payloadBase.def_readwrite("time", &PayloadBase::time, "time");

    //PayloadWater
    py::class_<PayloadWater, PayloadRelay> payloadWater(m, "PayloadWater");
    payloadWater.def(py::init<>());
    payloadWater.def_readwrite("subnode", &PayloadWater::subnode, "allow multiple water nodes on the network");
    payloadWater.def_readwrite("supplyV", &PayloadWater::supplyV, "supplyV in mV" );
    payloadWater.def_property("numFlowSensors", [](PayloadWater &payload){ return (unsigned int)(payload.numSensors & 0xF); }, [](PayloadWater& payload) {}); 
    payloadWater.def_property("numHeightSensors",[](PayloadWater &payload){ return (unsigned int)((payload.numSensors & 0xF0) >> 4); }, [](PayloadWater& payload) {}); 
    payloadWater.def_property("flowCount", [](PayloadWater &payload)->pybind11::array {
            auto dtype = pybind11::dtype(pybind11::format_descriptor<unsigned long>::format());
            return pybind11::array(dtype, { MAX_WATER_SENSORS }, { sizeof(unsigned long) }, payload.flowCount, nullptr);
            }, [](PayloadWater& payload) {});	//flowcount readings
    payloadWater.def_property("waterHeight", [](PayloadWater &payload)->pybind11::array {
            auto dtype = pybind11::dtype(pybind11::format_descriptor<int>::format());
            return pybind11::array(dtype, { MAX_WATER_SENSORS }, { sizeof(int) }, payload.waterHeight, nullptr);
            }, [](PayloadWater& payload) {});	//waterHeight readings

    //PayloadScale
    py::class_<PayloadScale, PayloadRelay> payloadScale(m, "PayloadScale");
    payloadScale.def(py::init<>());
    payloadScale.def_readwrite("subnode", &PayloadScale::subnode, "allow multiple scale nodes on the network");
    payloadScale.def_readwrite("supplyV", &PayloadScale::supplyV, "supplyV in mV" );
    payloadScale.def_readwrite("grams", &PayloadScale::grams, "grams" );

    //PayloadBattery
    py::class_<PayloadBattery, PayloadRelay> payloadBattery(m, "PayloadBattery");
    payloadBattery.def(py::init<>());
    payloadBattery.def_readwrite("subnode", &PayloadBattery::subnode, "allow multiple Battery nodes on the network");
    payloadBattery.def_property("power", [](PayloadBattery &payload)->pybind11::array {
            auto dtype = pybind11::dtype(pybind11::format_descriptor<int>::format());
            return pybind11::array(dtype, { BATTERY_SHUNTS }, { sizeof(int) }, payload.power, nullptr);
            }, [](PayloadBattery& payload) {});	//power in watts -ve and posititive
    payloadBattery.def_property("pulseIn", [](PayloadBattery &payload)->pybind11::array {
            auto dtype = pybind11::dtype(pybind11::format_descriptor<unsigned long>::format());
            return pybind11::array(dtype, { BATTERY_SHUNTS }, { sizeof(unsigned long) }, payload.pulseIn, nullptr);
            }, [](PayloadBattery& payload) {});	//total pulse in, watt hours
    payloadBattery.def_property("pulseOut", [](PayloadBattery &payload)->pybind11::array {
            auto dtype = pybind11::dtype(pybind11::format_descriptor<unsigned long>::format());
            return pybind11::array(dtype, { BATTERY_SHUNTS }, { sizeof(unsigned long) }, payload.pulseOut, nullptr);
            }, [](PayloadBattery& payload) {});	//total pulse in, watt hours
    payloadBattery.def_property("voltage", [](PayloadBattery &payload)->pybind11::array {
            auto dtype = pybind11::dtype(pybind11::format_descriptor<short>::format());
            return pybind11::array(dtype, { MAX_VOLTAGES }, { sizeof(short) }, payload.voltage, nullptr);
            }, [](PayloadBattery& payload) {});	//total pulse out, watt hours


    //PayloadInverter
    py::class_<PayloadInverter, PayloadRelay> payloadInverter(m, "PayloadInverter");
    payloadInverter.def(py::init<>());
    payloadInverter.def_readwrite("subnode", &PayloadInverter::subnode     , "allow multiple Inverter nodes on the network");
    payloadInverter.def_readwrite("activePower", &PayloadInverter::activePower     , "watts");
    payloadInverter.def_readwrite("apparentPower", &PayloadInverter::apparentPower   , "VAR");
    payloadInverter.def_readwrite("batteryVoltage", &PayloadInverter::batteryVoltage  , "0.1v");
    payloadInverter.def_readwrite("batteryDischarge", &PayloadInverter::batteryDischarge, "A");
    payloadInverter.def_readwrite("batteryCharging", &PayloadInverter::batteryCharging , "A");
    payloadInverter.def_readwrite("pvInputPower", &PayloadInverter::pvInputPower    , "watts");
    payloadInverter.def_readwrite("batteryCapacity", &PayloadInverter::batteryCapacity , "percentage");
    payloadInverter.def_readwrite("pulse", &PayloadInverter::pulse , "wH");

    //PayloadBeehive
    py::class_<PayloadBeehive, PayloadRelay> payloadBeehive(m, "PayloadBeehive");
    payloadBeehive.def(py::init<>());
    payloadBeehive.def_readwrite("subnode", &PayloadBeehive::subnode, "allow multiple Beehive nodes on the network");
    payloadBeehive.def_readwrite("beeInRate", &PayloadBeehive::beeInRate, "bees in per minute");
    payloadBeehive.def_readwrite("beeOutRate", &PayloadBeehive::beeOutRate, "bees out per minute");
    payloadBeehive.def_readwrite("beesIn", &PayloadBeehive::beesIn, "total bees in");
    payloadBeehive.def_readwrite("beesOut", &PayloadBeehive::beesOut, "A");
    payloadBeehive.def_readwrite("temperatureIn", &PayloadBeehive::temperatureIn, "Temperature inside the hive");
    payloadBeehive.def_readwrite("temperatureOut", &PayloadBeehive::temperatureOut, "Temperature outside the hive");
    payloadBeehive.def_readwrite("grams", &PayloadBeehive::grams, "current scale reading");
    payloadBeehive.def_readwrite("supplyV", &PayloadBeehive::supplyV, "unit supply voltage");


    //PayloadAirQuality
    py::class_<PayloadAirQuality, PayloadRelay> payloadAirQuality(m, "PayloadAirQuality");
    payloadAirQuality.def(py::init<>());
    payloadAirQuality.def_readwrite("subnode", &PayloadAirQuality::subnode, "allow multiple AirQuality nodes on the network");
    payloadAirQuality.def_readwrite("pm0p3", &PayloadAirQuality::pm0p3, "Particles Per Deciliter pm0.3 reading");
    payloadAirQuality.def_readwrite("pm0p5", &PayloadAirQuality::pm0p5, "Particles Per Deciliter pm0.5 reading");
    payloadAirQuality.def_readwrite("pm1p0", &PayloadAirQuality::pm1p0, "Particles Per Deciliter pm1.0 reading");
    payloadAirQuality.def_readwrite("pm2p5", &PayloadAirQuality::pm2p5, "Particles Per Deciliter pm2.5 reading");
    payloadAirQuality.def_readwrite("pm5p0", &PayloadAirQuality::pm5p0, "Particles Per Deciliter pm5.0 reading");
    payloadAirQuality.def_readwrite("pm10p0", &PayloadAirQuality::pm10p0, "Particles Per Deciliter pm10.0 reading");


    //PayloadLeaf
    py::class_<PayloadLeaf, PayloadRelay> payloadLeaf(m, "PayloadLeaf");
    payloadLeaf.def(py::init<>());
    payloadLeaf.def_readwrite("subnode", &PayloadLeaf::subnode, "allow multiple Leaf nodes on the network");
    payloadLeaf.def_readwrite("odometer", &PayloadLeaf::odometer, "Odometer reading in kilometers");
    payloadLeaf.def_readwrite("range", &PayloadLeaf::range, "Remaining range in kilometers");
    payloadLeaf.def_readwrite("batteryTemperature", &PayloadLeaf::batteryTemperature, "Battery temperature in celcius");
    payloadLeaf.def_readwrite("batterySOH", &PayloadLeaf::batterySOH, "Battery state of health in percent");
    payloadLeaf.def_readwrite("batteryWH", &PayloadLeaf::batteryWH, "Battery WH remaining");
    payloadLeaf.def_readwrite("batteryChargeBars", &PayloadLeaf::batteryChargeBars, "Battery charge bars on Dashboard (12=fully charged)");
    payloadLeaf.def_readwrite("chargeTimeRemaining", &PayloadLeaf::chargeTimeRemaining, "Battery charge time remaining in minutes");

    //PayloadGPS
    py::class_<PayloadGPS, PayloadRelay> payloadGPS(m, "PayloadGPS");
    payloadGPS.def(py::init<>());
    payloadGPS.def_readwrite("subnode", &PayloadGPS::subnode, "allow multiple GPS nodes on the network");
    payloadGPS.def_readwrite("latitude", &PayloadGPS::latitude, "GPS latitude");
    payloadGPS.def_readwrite("longitude", &PayloadGPS::longitude, "GPS longitude");
    payloadGPS.def_readwrite("course", &PayloadGPS::course, "GPS course");
    payloadGPS.def_readwrite("speed", &PayloadGPS::speed, "GPS speed");

    //PayloadPressure
    py::class_<PayloadPressure, PayloadRelay> payloadPressure(m, "PayloadPressure");
    payloadPressure.def(py::init<>());
    payloadPressure.def_readwrite("subnode", &PayloadPressure::subnode, "allow multiple Pressure nodes on the network");
    payloadPressure.def_readwrite("pressure", &PayloadPressure::pressure, "Pressure");
    payloadPressure.def_readwrite("temperature", &PayloadPressure::temperature, "Temperature");
    payloadPressure.def_readwrite("humidity", &PayloadPressure::humidity, "Humidity");

    //PayloadDalyBMS
    py::class_<PayloadDalyBMS, PayloadRelay> payloadDalyBMS(m, "PayloadDalyBMS");
    payloadDalyBMS.def(py::init<>());
    payloadDalyBMS.def_readwrite("subnode", &PayloadDalyBMS::subnode, "allow multiple Daly BMS nodes on the network");
    payloadDalyBMS.def_readwrite("batteryVoltage", &PayloadDalyBMS::batteryVoltage, "Battery voltage in 1/10th V");
    payloadDalyBMS.def_readwrite("batterySoC", &PayloadDalyBMS::batterySoC, "battery state of charge 0.1%");
    payloadDalyBMS.def_readwrite("current", &PayloadDalyBMS::current,"Current in (+) or out (-) of pack (0.1 A)");
    payloadDalyBMS.def_readwrite("resCapacity", &PayloadDalyBMS::resCapacity,"mAh");
    payloadDalyBMS.def_readwrite("temperature", &PayloadDalyBMS::temperature,"pack average temperature in degrees");
    payloadDalyBMS.def_readwrite("lifetimeCycles", &PayloadDalyBMS::lifetimeCycles,"lifetime number of charg/discharge cycles");

    payloadDalyBMS.def_property("cellmv", [](PayloadDalyBMS &payload)->pybind11::array {
            auto dtype = pybind11::dtype(pybind11::format_descriptor<short>::format());
            return pybind11::array(dtype, { MAX_BMS_CELLS }, { sizeof(short) }, payload.cellmv, nullptr);
            }, [](PayloadDalyBMS& payload) {});	// cell voltages in mv

    //PayloadSevCon
    py::class_<PayloadSevCon, PayloadRelay> payloadSevCon(m, "PayloadSevCon");
    payloadSevCon.def(py::init<>());
    payloadSevCon.def_readwrite("subnode", &PayloadSevCon::subnode, "allow multiple SevCon nodes on the network");
    payloadSevCon.def_readwrite("motorTemperature", &PayloadSevCon::motorTemperature, "Motor temperature C");
    payloadSevCon.def_readwrite("controllerTemperature", &PayloadSevCon::controllerTemperature, "Controller temperature C");
    payloadSevCon.def_readwrite("capVoltage", &PayloadSevCon::capVoltage, "Cap voltage V");
    payloadSevCon.def_readwrite("batteryCurrent", &PayloadSevCon::batteryCurrent, "Battery current A");
    payloadSevCon.def_readwrite("rpm", &PayloadSevCon::rpm, "RPM revolutions per minute");

    //PayloadAnemometer
    py::class_<PayloadAnemometer, PayloadRelay> payloadAnemometer(m, "PayloadAnemometer");
    payloadAnemometer.def(py::init<>());
    payloadAnemometer.def_readwrite("subnode", &PayloadAnemometer::subnode, "allow multiple Anemometer nodes on the network");
    payloadAnemometer.def_readwrite("windSpeed", &PayloadAnemometer::windSpeed, "Wind speed");
    payloadAnemometer.def_readwrite("windDirection", &PayloadAnemometer::windDirection, "Wind direction (relative)");
    payloadAnemometer.def_readwrite("temperature", &PayloadAnemometer::temperature, "Temperature C");

    //PayloadIMU
    py::class_<PayloadIMU, PayloadRelay> payloadIMU(m, "PayloadIMU");
    payloadIMU.def(py::init<>());
    payloadIMU.def_readwrite("subnode", &PayloadIMU::subnode, "allow multiple IMU nodes on the network");
    payloadIMU.def_property("acc", [](PayloadIMU &payload)->pybind11::array {
            auto dtype = pybind11::dtype(pybind11::format_descriptor<float>::format());
            return pybind11::array(dtype, { 3 }, { sizeof(float) }, payload.acc, nullptr);
            }, [](PayloadIMU& payload) {});	// normalised accelerometer readings
    payloadIMU.def_property("mag", [](PayloadIMU &payload)->pybind11::array {
            auto dtype = pybind11::dtype(pybind11::format_descriptor<float>::format());
            return pybind11::array(dtype, { 3 }, { sizeof(float) }, payload.mag, nullptr);
            }, [](PayloadIMU& payload) {});	// normalised magnetometer readings
    payloadIMU.def_property("gyro", [](PayloadIMU &payload)->pybind11::array {
            auto dtype = pybind11::dtype(pybind11::format_descriptor<float>::format());
            return pybind11::array(dtype, { 3 }, { sizeof(float) }, payload.gyro, nullptr);
            }, [](PayloadIMU& payload) {});	// normalised gyroscope readings
    payloadIMU.def_readwrite("heading", &PayloadIMU::heading, "Heading in degrees");


    //Parse function calls
    py::class_<EmonSerial> emonSerial(m, "EmonSerial");
    emonSerial.def_static("ParseRainPayload", &EmonSerial::ParseRainPayload, "Parses from string to RainPayload",py::arg("string"), py::arg("PayloadRain"));
    emonSerial.def_static("ParseTemperaturePayload", &EmonSerial::ParseTemperaturePayload, "Parses from string to PayloadTemperature",py::arg("string"), py::arg("PayloadTemperature"));
    emonSerial.def_static("ParseDispPayload", &EmonSerial::ParseDispPayload, "Parses from string to PayloadDisp",py::arg("string"), py::arg("PayloadDisp"));
    emonSerial.def_static("ParseHWSPayload", &EmonSerial::ParseHWSPayload, "Parses from string to PayloadHWS",py::arg("string"), py::arg("PayloadHWS"));
    emonSerial.def_static("ParseBasePayload", &EmonSerial::ParseBasePayload, "Parses from string to PayloadBase",py::arg("string"), py::arg("PayloadBase"));
    emonSerial.def_static("ParsePulsePayload", &EmonSerial::ParsePulsePayload, "Parses from string to PayloadPulse",py::arg("string"), py::arg("PayloadPulse"));
    emonSerial.def_static("ParseWaterPayload", &EmonSerial::ParseWaterPayload, "Parses from string to PayloadWater",py::arg("string"), py::arg("PayloadWater"));
    emonSerial.def_static("ParseScalePayload", &EmonSerial::ParseScalePayload, "Parses from string to PayloadScale",py::arg("string"), py::arg("PayloadScale"));
    emonSerial.def_static("ParseBatteryPayload", &EmonSerial::ParseBatteryPayload, "Parses from string to PayloadBattery",py::arg("string"), py::arg("PayloadBattery"));
    emonSerial.def_static("ParseBeehivePayload", &EmonSerial::ParseBeehivePayload, "Parses from string to PayloadBeehive",py::arg("string"), py::arg("PayloadBeehive"));
    emonSerial.def_static("ParseInverterPayload", &EmonSerial::ParseInverterPayload, "Parses from string to PayloadInverter",py::arg("string"), py::arg("PayloadInverter"));
    emonSerial.def_static("ParseAirQualityPayload", &EmonSerial::ParseAirQualityPayload, "Parses from string to PayloadAirQuality",py::arg("string"), py::arg("PayloadAirQuality"));
    emonSerial.def_static("ParseLeafPayload", &EmonSerial::ParseLeafPayload, "Parses from string to PayloadLeaf",py::arg("string"), py::arg("PayloadLeaf"));
    emonSerial.def_static("ParseGPSPayload", &EmonSerial::ParseGPSPayload, "Parses from string to PayloadGPS",py::arg("string"), py::arg("PayloadGPS"));
    emonSerial.def_static("ParsePressurePayload", &EmonSerial::ParsePressurePayload, "Parses from string to PayloadPressure",py::arg("string"), py::arg("PayloadPressure"));
    emonSerial.def_static("ParseDalyBMSPayload", &EmonSerial::ParseDalyBMSPayload, "Parses from string to PayloadDalyBMS",py::arg("string"), py::arg("PayloadDalyBMS"));
    emonSerial.def_static("ParseSevConPayload", &EmonSerial::ParseSevConPayload, "Parses from string to PayloadSevCon",py::arg("string"), py::arg("PayloadSevCon"));
    emonSerial.def_static("ParseAnemometerPayload", &EmonSerial::ParseAnemometerPayload, "Parses from string to PayloadAnemometer",py::arg("string"), py::arg("PayloadAnemometer"));
    emonSerial.def_static("ParseIMUPayload", &EmonSerial::ParseIMUPayload, "Parses from string to PayloadIMU",py::arg("string"), py::arg("PayloadIMU"));
    emonSerial.def_static("CalcCrc", &EmonSerial::CalcCrc, "Calculates Crc on payloads",py::arg("const void*"), py::arg("byte"));
}



