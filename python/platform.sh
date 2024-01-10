#!/bin/bash

# Used in Docker build to set platform dependent variables

case $TARGETARCH in

    "amd64")
	echo "pyemonlib-0.1.0-cp37-cp37m-linux_x86_64.whl" > /.platform_whl
	;;
    "arm64") 
	echo "pyemonlib-0.1.0-cp311-cp311-linux_aarch64.whl" > /.platform_whl
	;;
    "arm")
	echo "pyemonlib-0.1.0-cp311-cp311-linux_armv7l.whl" > /.platform_whl
	;;
esac