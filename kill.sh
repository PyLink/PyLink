#!/usr/bin/env bash
# Script to kill PyLink quickly when running under CPUlimit, since
# it will daemonize after threads are spawned and Ctrl-C won't work.

kill $(cat pylink.pid)
echo 'Killed. Press Ctrl-C in the PyLink window to exit.'
