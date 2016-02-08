"""
conf.py - PyLink configuration core.

This module is used to access the complete configuration for the current
PyLink instance. It will load the config on first import, taking the
configuration file name from the first command-line argument, but defaulting
to 'config.yml' if this isn't given.

If world.testing is set to True, it will return a preset testing configuration
instead.

This module also provides simple checks for validating and loading YAML-format
configurations from arbitrary files.
"""

import yaml
import sys
from collections import defaultdict

import world

global testconf
testconf = {'bot':
                {
                    'nick': 'PyLink',
                    'user': 'pylink',
                    'realname': 'PyLink Service Client',
                    # Suppress logging in the test output for the most part.
                    'loglevel': 'CRITICAL',
                    'serverdesc': 'PyLink unit tests'
                },
            'servers':
                # Wildcard defaultdict! This means that
                # any network name you try will work and return
                # this basic template:
                defaultdict(lambda: {
                        'ip': '0.0.0.0',
                        'port': 7000,
                        'recvpass': "abcd",
                        'sendpass': "chucknorris",
                        'protocol': "null",
                        'hostname': "pylink.unittest",
                        'sid': "9PY",
                        'channels': ["#pylink"],
                        'maxnicklen': 20,
                        'sidrange': '8##'
                    })
           }

def validateConf(conf):
    """Validates a parsed configuration dict."""
    assert type(conf) == dict, "Invalid configuration given: should be type dict, not %s." % type(conf).__name__

    for section in ('bot', 'servers', 'login', 'logging'):
        assert conf.get(section), "Missing %r section in config." % section

    for netname, serverblock in conf['servers'].items():
        for section in ('ip', 'port', 'recvpass', 'sendpass', 'hostname',
                        'sid', 'sidrange', 'protocol', 'maxnicklen'):
            assert serverblock.get(section), "Missing %r in server block for %r." % (section, netname)

        assert type(serverblock.get('channels')) == list, "'channels' option in " \
            "server block for %s must be a list, not %s." % (netname, type(serverblock['channels']).__name__)

    assert type(conf['login'].get('password')) == type(conf['login'].get('user')) == str and \
        conf['login']['password'] != "changeme", "You have not set the login details correctly!"

    return conf

def loadConf(fname, errors_fatal=True):
    """Loads a PyLink configuration file from the filename given."""
    with open(fname, 'r') as f:
        try:
            conf = yaml.load(f)
        except Exception as e:
            print('ERROR: Failed to load config from %r: %s: %s' % (fname, type(e).__name__, e))
            if errors_fatal:
                sys.exit(4)
            raise
        else:
            return conf

if world.testing:
    conf = testconf
    confname = 'testconf'
    fname = None
else:
    try:
        # Get the config name from the command line, falling back to config.yml
        # if not given.
        fname = sys.argv[1]
        confname = fname.split('.', 1)[0]
    except IndexError:
        # confname is used for logging and PID writing, so that each
        # instance uses its own files. fname is the actual name of the file
        # we load.
        confname = 'pylink'
        fname = 'config.yml'
    conf = validateConf(loadConf(fname))
