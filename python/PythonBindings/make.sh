#!/bin/bash
c++ -O3 -Wall -shared -std=c++11 -fPIC $(python3-config --includes) -I../../extern/pybind11/include emon_pybindings.cpp -o ../pyEmon/pyemonlib/emonSuite$(python3-config --extension-suffix)