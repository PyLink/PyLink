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

level = conf['bot'].get('loglevel') or 'DEBUG'
try:
    level = getattr(logging, level.upper())
except AttributeError:
    print('ERROR: Invalid log level %r specified in config.' % level)
    sys.exit(3)

curdir = os.path.dirname(os.path.realpath(__file__))
logdir = os.path.join(curdir, 'log')
# Make sure our log/ directory exists
os.makedirs(logdir, exist_ok=True)

_format = '%(asctime)s [%(levelname)s] %(message)s'
logging.basicConfig(level=level, format=_format)

# Set log file to $CURDIR/log/pylink
logformat = logging.Formatter(_format)
logfile = logging.FileHandler(os.path.join(logdir, '%s.log' % confname), mode='w')
logfile.setFormatter(logformat)

global log
log = logging.getLogger()
log.addHandler(logfile)

class PyLinkChannelLogger(logging.Handler):
    """
    Log handler to log to channels in PyLink.
    """
    def __init__(self, irc, channels):
        super(PyLinkChannelLogger, self).__init__()
        self.irc = irc
        self.channels = channels

        # Use a slightly simpler message formatter - logging to IRC doesn't need
        # logging the time.
        formatter = logging.Formatter('[%(levelname)s] %(message)s')
        self.setFormatter(formatter)

        # Log level has to be at least 20 (INFO) to prevent loops due
        # to outgoing messages being logged
        loglevel = max(log.getEffectiveLevel(), 20)
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

