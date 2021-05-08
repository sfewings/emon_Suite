#include <pybind11/pybind11.h>
#define __linux__
#define MQTT_LIB

#include "../EmonShared/EmonShared.cpp"

namespace py = pybind11;

PYBIND11_MODULE(emonSuite, m) {
    m.doc() = "pybind11 plugin for EmonSuite"; // optional module docstring

    py::class_<PayloadRelay> payloadRelay(m, "PayloadRelay");
    payloadRelay.def_readwrite("relay", &PayloadRelay::relay);

    py::class_<PayloadRain, PayloadRelay> payloadRain(m, "PayloadRain");
    payloadRain.def(py::init<>());
    payloadRain.def_readwrite("rainCount", &PayloadRain::rainCount);                //The count from the rain gauge
    payloadRain.def_readwrite("transmitCount", &PayloadRain::transmitCount);        //Increment for each time the rainCount is transmitted. When rainCount is changed, this value is 0 
    payloadRain.def_readwrite("temperature", &PayloadRain::temperature);        //temperature in 100ths of degrees
    payloadRain.def_readwrite("supplyV", &PayloadRain::supplyV);

    py::class_<EmonSerial> emonSerial(m, "EmonSerial");
    emonSerial.def_static("ParseRainPayload", &EmonSerial::ParseRainPayload, py::return_value_policy::take_ownership, "Parses from string to RainPayload   ");
}



