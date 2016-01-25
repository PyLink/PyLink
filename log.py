"""
log.py - PyLink logging module.

This module contains the logging portion of the PyLink framework. Plugins can
access the global logger object by importing "log" from this module
(from log import log).
"""

import logging
import sys
import os

from conf import conf, confname

stdout_level = conf['logging'].get('stdout') or 'INFO'

# Set the logging directory to $CURDIR/log, creating it if it doesn't
# already exist
curdir = os.path.dirname(os.path.realpath(__file__))
logdir = os.path.join(curdir, 'log')
os.makedirs(logdir, exist_ok=True)

# Basic logging setup, set up here on first import, logs to STDOUT based
# on the log level configured.
_format = '%(asctime)s [%(levelname)s] %(message)s'
logformatter = logging.Formatter(_format)
logging.basicConfig(level=stdout_level, format=_format)

# Get the main logger object; plugins can import this variable for convenience.
log = logging.getLogger()

def makeFileLogger(filename, level=None):
    """
    Initializes a file logging target with the given filename and level.
    """
    # Use log names specific to the current instance, to prevent multiple
    # PyLink instances from overwriting each others' log files.
    target = os.path.join(logdir, '%s-%s.log' % (confname, filename))

    filelogger = logging.FileHandler(target, mode='w')
    filelogger.setFormatter(logformatter)

    if level:  # Custom log level was defined, use that instead.
        filelogger.setLevel(level)

    log.addHandler(filelogger)

    return filelogger

# Set up file logging now, creating a file logger for each block.
files = conf['logging'].get('files')
if files:
    for filename, config in files.items():
        makeFileLogger(filename, config.get('loglevel'))

class PyLinkChannelLogger(logging.Handler):
    """
    Log handler to log to channels in PyLink.
    """
    def __init__(self, irc, channels, level=None):
        super(PyLinkChannelLogger, self).__init__()
        self.irc = irc
        self.channels = channels

        # Use a slightly simpler message formatter - logging to IRC doesn't need
        # logging the time.
        formatter = logging.Formatter('[%(levelname)s] %(message)s')
        self.setFormatter(formatter)

        # Log level has to be at least 20 (INFO) to prevent loops due
        # to outgoing messages being logged
        level = level or log.getEffectiveLevel()
        loglevel = max(level, 20)
        self.setLevel(loglevel)

    def emit(self, record):
        """
        Logs a record to the configured channels for the network given.
        """
        # Only start logging if we're finished bursting
        if hasattr(self.irc, 'pseudoclient') and self.irc.connected.is_set():
            msg = self.format(record)
            for channel in self.channels:
                self.irc.msg(channel, msg)

