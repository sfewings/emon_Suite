from setuptools import find_packages, setup

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
    package_data={'': ['emonSuite.cpython-37m-arm-linux-gnueabihf.so']},
)