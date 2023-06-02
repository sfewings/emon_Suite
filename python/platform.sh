#!/bin/bash

# Used in Docker build to set platform dependent variables

case $TARGETARCH in

    "amd64")
	echo "pyemonlib-0.1.0-cp39-cp39m-linux_x86_64.whl" > /.platform_whl
	;;
    "arm64") 
	echo "wheel_not_created" > /.platform_whl
	;;
    "arm")
	echo "pyemonlib-0.1.0-cp39-cp39m-linux_x86_64.whl" > /.platform_whl
	;;
esac