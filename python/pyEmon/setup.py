from setuptools import find_packages, setup
from pybind11.setup_helpers import Pybind11Extension


setup(
    name='pyemonlib',
    packages=find_packages(include=['pyemonlib']),
    version='0.1.0',
    description='Emon Python library',
    author='Me',
    license='MIT',
    install_requires=['influxdb-client[ciso]','paho-mqtt','pyyaml'],
    setup_requires=['pytest-runner'],
    tests_require=['pytest==4.4.1', 'cython', 'numpy', 'pytz'],
    test_suite='tests',
    ext_modules = [Pybind11Extension( "pyemonlib.emonSuite",['pyemonlib/emon_pybindings.cpp'])]
    #package_data={'': ['emonSuite.cpython-37m-arm-linux-gnueabihf.so']}
)