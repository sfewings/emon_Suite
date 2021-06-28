To create python bindings
=========================
1. To create python bindings using pybind11  https://pybind11.readthedocs.io/
    pybind11 is included as a git submodule of emon_suite
        git submodule add -b stable ../../pybind/pybind11 extern/pybind11
        git submodule update --init
2. Build python .so 
    run ./make.sh
3. Copy emonSuite.cpython-37m-arm-linux-gnueabihf.so to the pyEmon/pyemonlib
    
To create pyemonlib
===================
Instructions as from https://medium.com/analytics-vidhya/how-to-create-a-python-library-7d5aea80cc3f 
1. Create a virtual environment to contain the python setup
    > python3 -m venv venv
    > source venv/bin/activate
2. Install the libraries required for setup
    > pip install wheel
    > pip install setuptools
    > pip install twine
3. Run all the tests in tests folder
    > python setup.py pytest
3. Run setup
    > python setup.py bdist_wheel
4. Copy the wheel from dist and install
    > pip install ./dist/pyemonlib-0.1.0-py3-none-any.whl

To create and enable python environment
=======================================
1. Create environment named venv 
    python3 -m venv venv
2. Activate the environment
    source venv/bin/activate

To drop the sensor database from influx and create a new one
============================================================
1. exec influx inside the influx container
    docker exec -it 999fca3ed0cd sh
2. start the influx cli
    influx
3. drop the existing sensors database 
    DROP DATABASE sensors
4. Create a new sensors database
    CREATE DATABASE sensors
