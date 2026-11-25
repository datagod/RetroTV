#!/bin/sh
# Run from a prepared Main_MiSTer source directory with Arm GNU GCC 10.2 on PATH.
set -eu
test -f Makefile
test -f retrotv_mount.cpp
make "$@"
