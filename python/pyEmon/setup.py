import os

from setuptools import find_packages, setup
from pybind11.setup_helpers import Pybind11Extension

# emon_pybindings.cpp includes EmonShared.cpp, the Arduino-side payload definitions, so
# the C++ in the extension and the C++ on the nodes are the same source. It lives
# outside this package, two directories up at the repository root.
#
# Resolved here and handed to the compiler as an include directory, rather than reached
# with "../../.." from inside the .cpp. That path was relative to the source file, so
# the extension could only be built with the whole repository laid out around it;
# building from a copy of python/pyEmon failed with a bare "compilation terminated".
# Now only this one line knows where EmonShared is, and EMON_SHARED_DIR overrides it
# for a build somewhere else.
HERE = os.path.dirname(os.path.abspath(__file__))
EMON_SHARED_DIR = os.environ.get(
    "EMON_SHARED_DIR", os.path.abspath(os.path.join(HERE, os.pardir, os.pardir, "EmonShared")))

if not os.path.isfile(os.path.join(EMON_SHARED_DIR, "EmonShared.cpp")):
    raise SystemExit(
        f"EmonShared.cpp not found in {EMON_SHARED_DIR}.\n"
        "The extension needs the EmonShared sources from the repository root. Build "
        "from a full checkout, or set EMON_SHARED_DIR to where EmonShared lives.")


setup(
    name='pyemonlib',
    packages=find_packages(include=['pyemonlib']),
    version='0.1.0',
    description='Emon Python library',
    author='Me',
    license='MIT',
    install_requires=['influxdb-client[ciso]','paho-mqtt','pyyaml'],
    setup_requires=['pytest-runner'],
    tests_require=['pytest==9.0.3', 'cython', 'numpy', 'pytz'],
    test_suite='tests',
    ext_modules = [Pybind11Extension("pyemonlib.emonSuite",
                                     ['pyemonlib/emon_pybindings.cpp'],
                                     include_dirs=[EMON_SHARED_DIR])]
    #package_data={'': ['emonSuite.cpython-37m-arm-linux-gnueabihf.so']}
)