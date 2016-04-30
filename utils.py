"""
utils.py - PyLink utilities module.

This module contains various utility functions related to IRC and/or the PyLink
framework.
"""

import string
import re
import importlib
import os

from log import log
import world
import conf

class IncrementalUIDGenerator():
    """
    Incremental UID Generator module, adapted from InspIRCd source:
    https://github.com/inspircd/inspircd/blob/f449c6b296ab/src/server.cpp#L85-L156
    """

    def __init__(self, sid):
        if not (hasattr(self, 'allowedchars') and hasattr(self, 'length')):
             raise RuntimeError("Allowed characters list not defined. Subclass "
                                "%s by defining self.allowedchars and self.length "
                                "and then calling super().__init__()." % self.__class__.__name__)
        self.uidchars = [self.allowedchars[0]]*self.length
        self.sid = sid

    def increment(self, pos=None):
        """
        Increments the UID generator to the next available UID.
        """
        # Position starts at 1 less than the UID length.
        if pos is None:
            pos = self.length - 1

        # If we're at the last character in the list of allowed ones, reset
        # and increment the next level above.
        if self.uidchars[pos] == self.allowedchars[-1]:
            self.uidchars[pos] = self.allowedchars[0]
            self.increment(pos-1)
        else:
            # Find what position in the allowed characters list we're currently
            # on, and add one.
            idx = self.allowedchars.find(self.uidchars[pos])
            self.uidchars[pos] = self.allowedchars[idx+1]

    def next_uid(self):
        """
        Returns the next unused UID for the server.
        """
        uid = self.sid + ''.join(self.uidchars)
        self.increment()
        return uid

def add_cmd(func, name=None):
    """Binds an IRC command function to the given command name."""
    if name is None:
        name = func.__name__
    name = name.lower()
    world.commands[name].append(func)
    return func

def add_hook(func, command):
    """Binds a hook function to the given command name."""
    command = command.upper()
    world.hooks[command].append(func)
    return func

def toLower(irc, text):
    """Returns a lowercase representation of text based on the IRC object's
    casemapping (rfc1459 or ascii)."""
    if irc.proto.casemapping == 'rfc1459':
        text = text.replace('{', '[')
        text = text.replace('}', ']')
        text = text.replace('|', '\\')
        text = text.replace('~', '^')
    return text.lower()

_nickregex = r'^[A-Za-z\|\\_\[\]\{\}\^\`][A-Z0-9a-z\-\|\\_\[\]\{\}\^\`]*$'
def isNick(s, nicklen=None):
    """Returns whether the string given is a valid nick."""
    if nicklen and len(s) > nicklen:
        return False
    return bool(re.match(_nickregex, s))

def isChannel(s):
    """Returns whether the string given is a valid channel name."""
    return str(s).startswith('#')

def _isASCII(s):
    """Returns whether the string given is valid ASCII."""
    chars = string.ascii_letters + string.digits + string.punctuation
    return all(char in chars for char in s)

def isServerName(s):
    """Returns whether the string given is a valid IRC server name."""
    return _isASCII(s) and '.' in s and not s.startswith('.')

hostmaskRe = re.compile(r'^\S+!\S+@\S+$')
def isHostmask(text):
    """Returns whether the given text is a valid hostmask."""
    # Band-aid patch here to prevent bad bans set by Janus forwarding people into invalid channels.
    return hostmaskRe.match(text) and '#' not in text

def parseModes(irc, target, args):
    """Parses a modestring list into a list of (mode, argument) tuples.
    ['+mitl-o', '3', 'person'] => [('+m', None), ('+i', None), ('+t', None), ('+l', '3'), ('-o', 'person')]

    This method is deprecated. Use irc.parseModes() instead.
    """
    log.warning("(%s) utils.parseModes is deprecated. Use irc.parseModes() instead!", irc.name)
    return irc.parseModes(target, args)

def applyModes(irc, target, changedmodes):
    """Takes a list of parsed IRC modes, and applies them on the given target.

    The target can be either a channel or a user; this is handled automatically.

    This method is deprecated. Use irc.applyModes() instead.
    """
    log.warning("(%s) utils.applyModes is deprecated. Use irc.applyModes() instead!", irc.name)
    return irc.applyModes(target, changedmodes)

def loadModuleFromFolder(name, folder):
    """
    Imports and returns a module, if existing, from a specific folder.
    """
    fullpath = os.path.join(folder, '%s.py' % name)
    m = importlib.machinery.SourceFileLoader(name, fullpath).load_module()
    return m

def getProtocolModule(protoname):
    """
    Imports and returns the protocol module requested.
    """
    return loadModuleFromFolder(protoname, world.protocols_folder)

def getDatabaseName(dbname):
    """
    Returns a database filename with the given base DB name appropriate for the
    current PyLink instance.

    This returns '<dbname>.db' if the running config name is PyLink's default
    (config.yml), and '<dbname>-<config name>.db' for anything else. For example,
    if this is called from an instance running as './pylink testing.yml', it
    would return '<dbname>-testing.db'."""
    if conf.confname != 'pylink':
        dbname += '-%s' % conf.confname
    dbname += '.db'
    return dbname

def fullVersion(irc):
    """
    Returns a detailed version string including the PyLink daemon version,
    the protocol module in use, and the server hostname.
    """
    fullversion = 'PyLink-%s. %s :[protocol:%s]' % (world.version, irc.serverdata['hostname'], irc.protoname)
    return fullversion
