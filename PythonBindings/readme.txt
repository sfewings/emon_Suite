1. To create python bindings using pybind11  https://pybind11.readthedocs.io/
    pybind11 is included as a git submodule of emon_suite
        git submodule add -b stable ../../pybind/pybind11 extern/pybind11
        git submodule update --init
2. Build python .so 
    run ./make.sh
3. Copy emonSuite.cpython-37m-arm-linux-gnueabihf.so to the python source folder.
    Note. This can be made into a python installable

To drop the sensor database from influx and create a new one
1. exec influx inside the influx container
    docker exec -it 999fca3ed0cd sh
2. start the influx cli
    influx
3. drop the existing sensors database 
    DROP DATABASE sensors
4. Create a new sensors database
    CREATE DATABASE sensors
