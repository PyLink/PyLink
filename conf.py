"""
conf.py - PyLink configuration core.

This module is used to access the configuration of the current PyLink instance.
It provides simple checks for validating and loading YAML-format configurations from arbitrary files.
"""

try:
    import yaml
except ImportError:
    raise ImportError("PyLink requires PyYAML to function; please install it and try again.")

import sys
import os.path
from collections import defaultdict

from . import world

conf = {'bot':
                {
                    'nick': 'PyLink',
                    'user': 'pylink',
                    'realname': 'PyLink Service Client',
                    'serverdesc': 'Unconfigured PyLink'
                },
        'logging':
                {
                    'stdout': 'INFO'
                },
        'servers':
                # Wildcard defaultdict! This means that
                # any network name you try will work and return
                # this basic template:
                defaultdict(lambda: {'ip': '0.0.0.0',
                                     'port': 7000,
                                     'recvpass': "unconfigured",
                                     'sendpass': "unconfigured",
                                     'protocol': "null",
                                     'hostname': "pylink.unconfigured",
                                     'sid': "000",
                                     'maxnicklen': 20,
                                     'sidrange': '0##'
                                    })
        }
confname = 'unconfigured'

def validateConf(conf, logger=None):
    """Validates a parsed configuration dict."""
    assert type(conf) == dict, "Invalid configuration given: should be type dict, not %s." % type(conf).__name__

    for section in ('bot', 'servers', 'login', 'logging'):
        assert conf.get(section), "Missing %r section in config." % section

    # Make sure at least one form of authentication is valid.
    # Also we'll warn them that login:user/login:password is deprecated
    if conf['login'].get('password') or conf['login'].get('user'):
        e = "The 'login:user' and 'login:password' options are deprecated since PyLink 1.1. " \
            "Please switch to the new 'login:accounts' format as outlined in the example config."
        if logger:
            logger.warning(e)
        else:
            # FIXME: we need a better fallback when log isn't available on first
            # start.
            print('WARNING: %s' % e)

    old_login_valid = type(conf['login'].get('password')) == type(conf['login'].get('user')) == str
    newlogins = conf['login'].get('accounts', {})
    new_login_valid = len(newlogins) >= 1
    assert old_login_valid or new_login_valid, "No accounts were set, aborting!"
    for account, block in newlogins.items():
        assert type(account) == str, "Bad username format %s" % account
        assert type(block.get('password')) == str, "Bad password %s for account %s" % (block.get('password'), account)

    assert conf['login'].get('password') != "changeme", "You have not set the login details correctly!"

    if conf['login'].get('accounts'):
        assert conf.get('permissions'), "New-style accounts enabled but no permissions block was found. You will not be able to administrate your PyLink instance!"

    return conf


def loadConf(filename, errors_fatal=True, logger=None):
    """Loads a PyLink configuration file from the filename given."""
    global confname, conf, fname
    # Note: store globally the last loaded conf filename, for REHASH in coremods/control.
    fname = filename
    # For the internal config name, strip off any .yml extensions and absolute paths
    confname = os.path.basename(filename).split('.', 1)[0]
    try:
        with open(filename, 'r') as f:
            conf = yaml.load(f)
            conf = validateConf(conf, logger=logger)
    except Exception as e:
        print('ERROR: Failed to load config from %r: %s: %s' % (filename, type(e).__name__, e), file=sys.stderr)
        print('       Users upgrading from users < 0.9-alpha1 should note that the default configuration has been renamed to *pylink.yml*, not *config.yml*', file=sys.stderr)

        if errors_fatal:
            sys.exit(4)
        raise
    else:
        return conf
