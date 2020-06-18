"""
conf.py - PyLink configuration core.

This module is used to access the configuration of the current PyLink instance.
It provides simple checks for validating and loading YAML-format configurations from arbitrary files.
"""

try:
    import yaml
except ImportError:
    raise ImportError("PyLink requires PyYAML to function; please install it and try again.")

import logging
import os.path
import sys
from collections import defaultdict

from . import world

__all__ = ['ConfigurationError', 'conf', 'confname', 'validate', 'load_conf',
           'get_database_name']


class ConfigurationError(RuntimeError):
    """Error when config conditions aren't met."""

conf = {'bot':
                {
                    'nick': 'PyLink',
                    'user': 'pylink',
                    'realname': 'PyLink Service Client',
                    'serverdesc': 'Unconfigured PyLink'
                },
        'logging':
                {
                    'console': 'INFO'
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
conf['pylink'] = conf['bot']
confname = 'unconfigured'

def validate(condition, errmsg):
    """Raises ConfigurationError with errmsg unless the given condition is met."""
    if not condition:
        raise ConfigurationError(errmsg)

def _log(level, text, *args, logger=None, **kwargs):
    if logger:
        logger.log(level, text, *args, **kwargs)
    else:
        world._log_queue.append((level, text))

def _validate_conf(conf, logger=None):
    """Validates a parsed configuration dict."""
    validate(isinstance(conf, dict),
            "Invalid configuration given: should be type dict, not %s."
            % type(conf).__name__)

    if 'pylink' in conf and 'bot' in conf:
        _log(logging.WARNING, "Since PyLink 1.2, the 'pylink:' and 'bot:' configuration sections have been condensed "
             "into one. You should merge any options under these sections into one 'pylink:' block.", logger=logger)

        new_block = conf['bot'].copy()
        new_block.update(conf['pylink'])
        conf['bot'] = conf['pylink'] = new_block
    elif 'pylink' in conf:
        conf['bot'] = conf['pylink']
    elif 'bot' in conf:
        conf['pylink'] = conf['bot']
        # TODO: add a migration warning in the next release.

    for section in ('pylink', 'servers', 'login', 'logging'):
        validate(conf.get(section), "Missing %r section in config." % section)

    # Make sure at least one form of authentication is valid.
    # Also we'll warn them that login:user/login:password is deprecated
    if conf['login'].get('password') or conf['login'].get('user'):
        _log(logging.WARNING, "The 'login:user' and 'login:password' options are deprecated since PyLink 1.1. "
             "Please switch to the new 'login:accounts' format as outlined in the example config.", logger=logger)

    old_login_valid = isinstance(conf['login'].get('password'), str) and isinstance(conf['login'].get('user'), str)
    newlogins = conf['login'].get('accounts', {})

    validate(old_login_valid or newlogins, "No accounts were set, aborting!")
    for account, block in newlogins.items():
        validate(isinstance(account, str), "Bad username format %s" % account)
        validate(isinstance(block.get('password'), str), "Bad password %s for account %s" % (block.get('password'), account))

    validate(conf['login'].get('password') != "changeme", "You have not set the login details correctly!")

    if newlogins and not old_login_valid:
        validate(conf.get('permissions'), "New-style accounts enabled but no permissions block was found. You will not be able to administrate your PyLink instance!")

    if conf['logging'].get('stdout'):
         _log(logging.WARNING, 'The log:stdout option is deprecated since PyLink 1.2 in favour of '
                               '(a more correctly named) log:console. Please update your '
                               'configuration accordingly!', logger=logger)

    return conf

def load_conf(filename, errors_fatal=True, logger=None):
    """Loads a PyLink configuration file from the filename given."""
    global confname, conf, fname
    # Note: store globally the last loaded conf filename, for REHASH in coremods/control.
    fname = filename
    # For the internal config name, strip off any .yml extensions and absolute paths
    confname = os.path.splitext(os.path.basename(filename))[0]
    try:
        with open(filename, 'r') as f:
            conf = yaml.safe_load(f)
            conf = _validate_conf(conf, logger=logger)
    except Exception as e:
        e = 'Failed to load config from %r: %s: %s' % (filename, type(e).__name__, e)

        if logger:  # Prefer using the Python logger when available
            logger.exception(e)
        else:  # Otherwise, fall back to a print() call.
            print('ERROR: %s' % e, file=sys.stderr)

        if errors_fatal:
            sys.exit(1)

        raise
    else:
        return conf

def get_database_name(dbname):
    """
    Returns a database filename with the given base DB name appropriate for the
    current PyLink instance.

    This returns '<dbname>.db' if the running config name is PyLink's default
    (pylink.yml), and '<dbname>-<config name>.db' for anything else. For example,
    if this is called from an instance running as 'pylink testing.yml', it
    would return '<dbname>-testing.db'."""
    if confname != 'pylink':
        dbname += '-%s' % confname
    dbname += '.db'
    return dbname
