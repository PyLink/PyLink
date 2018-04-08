"""
utils.py - PyLink utilities module.

This module contains various utility functions related to IRC and/or the PyLink
framework.
"""

import string
import re
import importlib
import os
import collections
import argparse

from .log import log
from . import world, conf

# Load the protocol and plugin packages.
from pylinkirc import protocols, plugins

PLUGIN_PREFIX = plugins.__name__ + '.'
PROTOCOL_PREFIX = protocols.__name__ + '.'
NORMALIZEWHITESPACE_RE = re.compile(r'\s+')

class NotAuthorizedError(Exception):
    """
    Exception raised by the PyLink permissions system when a user fails access requirements.
    """
    pass

class InvalidArgumentsError(TypeError):
    """
    Exception raised (by IRCParser and potentially others) when a bot command is given invalid arguments.
    """

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
        self.sid = str(sid)

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

class PUIDGenerator():
    """
    Pseudo UID Generator module, using a prefix and a simple counter.
    """

    def __init__(self, prefix):
        self.prefix = prefix
        self.counter = 0

    def next_uid(self, prefix=''):
        """
        Generates the next PUID.
        """
        uid = '%s@%s' % (prefix or self.prefix, self.counter)
        self.counter += 1
        return uid
    next_sid = next_uid

def add_cmd(func, name=None, **kwargs):
    """Binds an IRC command function to the given command name."""
    world.services['pylink'].add_cmd(func, name=name, **kwargs)
    return func

def add_hook(func, command):
    """Binds a hook function to the given command name."""
    command = command.upper()
    world.hooks[command].append(func)
    return func

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

def expandpath(path):
    """
    Returns a path expanded with environment variables and home folders (~) expanded, in that order."""
    return os.path.expanduser(os.path.expandvars(path))

def resetModuleDirs():
    """
    (Re)sets custom protocol module and plugin directories to the ones specified in the config.
    """
    # Note: This assumes that the first element of the package path is the default one.
    plugins.__path__ = [plugins.__path__[0]] + [expandpath(path) for path in conf.conf['bot'].get('plugin_dirs', [])]
    log.debug('resetModuleDirs: new pylinkirc.plugins.__path__: %s', plugins.__path__)
    protocols.__path__ = [protocols.__path__[0]] + [expandpath(path) for path in conf.conf['bot'].get('protocol_dirs', [])]
    log.debug('resetModuleDirs: new pylinkirc.protocols.__path__: %s', protocols.__path__)

def loadPlugin(name):
    """
    Imports and returns the requested plugin.
    """
    return importlib.import_module(PLUGIN_PREFIX + name)

def getProtocolModule(name):
    """
    Imports and returns the protocol module requested.
    """
    return importlib.import_module(PROTOCOL_PREFIX + name)

def getDatabaseName(dbname):
    """
    Returns a database filename with the given base DB name appropriate for the
    current PyLink instance.

    This returns '<dbname>.db' if the running config name is PyLink's default
    (pylink.yml), and '<dbname>-<config name>.db' for anything else. For example,
    if this is called from an instance running as './pylink testing.yml', it
    would return '<dbname>-testing.db'."""
    if conf.confname != 'pylink':
        dbname += '-%s' % conf.confname
    dbname += '.db'
    return dbname

def splitHostmask(mask):
    """
    Returns a nick!user@host hostmask split into three fields: nick, user, and host.
    """
    nick, identhost = mask.split('!', 1)
    ident, host = identhost.split('@', 1)
    return [nick, ident, host]

class ServiceBot():
    """
    PyLink IRC Service class.
    """

    def __init__(self, name, default_help=True, default_list=True,
                 nick=None, ident=None, manipulatable=False, desc=None):
        # Service name
        self.name = name

        # TODO: validate nick, ident, etc. on runtime as well
        assert isNick(name), "Invalid service name %r" % name

        # Nick/ident to take. Defaults to the same as the service name if not given.
        self.nick = nick
        self.ident = ident

        # Tracks whether the bot should be manipulatable by the 'bots' plugin and other commands.
        self.manipulatable = manipulatable

        # We make the command definitions a dict of lists of functions. Multiple
        # plugins are actually allowed to bind to one function name; this just causes
        # them to be called in the order that they are bound.
        self.commands = collections.defaultdict(list)

        # This tracks the UIDs of the service bot on different networks, as they are
        # spawned.
        self.uids = {}

        # Track what channels other than those defined in the config
        # that the bot should join by default.
        self.extra_channels = collections.defaultdict(set)

        # Service description, used in the default help command if one is given.
        self.desc = desc

        # List of command names to "feature"
        self.featured_cmds = set()

        if default_help:
            self.add_cmd(self.help)

        if default_list:
            self.add_cmd(self.listcommands, 'list')

    def spawn(self, irc=None):
        """
        Spawns instances of this service on all connected networks.
        """
        # Spawn the new service by calling the PYLINK_NEW_SERVICE hook,
        # which is handled by coreplugin.
        if irc is None:
            for irc in world.networkobjects.values():
                irc.callHooks([None, 'PYLINK_NEW_SERVICE', {'name': self.name}])
        else:
            raise NotImplementedError("Network specific plugins not supported yet.")

    def join(self, irc, channels, autojoin=True):
        """
        Joins the given service bot to the given channel(s).
        """

        if type(irc) == str:
            netname = irc
        else:
            netname = irc.name

        # Ensure type safety: pluralize strings if only one channel was given, then convert to set.
        if type(channels) == str:
            channels = [channels]
        channels = set(channels)

        if autojoin:
            log.debug('(%s/%s) Adding channels %s to autojoin', netname, self.name, channels)
            self.extra_channels[netname] |= channels

        # If the network was given as a string, look up the Irc object here.
        try:
            irc = world.networkobjects[netname]
        except KeyError:
            log.debug('(%s/%s) Skipping join(), IRC object not initialized yet', netname, self.name)
            return

        try:
            u = self.uids[irc.name]
        except KeyError:
            log.debug('(%s/%s) Skipping join(), UID not initialized yet', irc.name, self.name)
            return

        # Specify modes to join the services bot with.
        joinmodes = irc.serverdata.get("%s_joinmodes" % self.name) or conf.conf.get(self.name, {}).get('joinmodes') or ''
        joinmodes = ''.join([m for m in joinmodes if m in irc.prefixmodes])

        for chan in channels:
            if isChannel(chan):
                if u in irc.channels[chan].users:
                    log.debug('(%s) Skipping join of services %s to channel %s - it is already present', irc.name, self.name, chan)
                    continue
                log.debug('(%s) Joining services %s to channel %s with modes %r', irc.name, self.name, chan, joinmodes)
                if joinmodes:  # Modes on join were specified; use SJOIN to burst our service
                    irc.proto.sjoin(irc.sid, chan, [(joinmodes, u)])
                else:
                    irc.proto.join(u, chan)

                irc.callHooks([irc.sid, 'PYLINK_SERVICE_JOIN', {'channel': chan, 'users': [u]}])
            else:
                log.warning('(%s) Ignoring invalid autojoin channel %r.', irc.name, chan)

    def reply(self, irc, text, notice=None, private=None):
        """Replies to a message as the service in question."""
        servuid = self.uids.get(irc.name)
        if not servuid:
            log.warning("(%s) Possible desync? UID for service %s doesn't exist!", irc.name, self.name)
            return

        irc.reply(text, notice=notice, source=servuid, private=private)

    def error(self, irc, text, notice=None, private=None):
        """Replies with an error, as the service in question."""
        servuid = self.uids.get(irc.name)
        if not servuid:
            log.warning("(%s) Possible desync? UID for service %s doesn't exist!", irc.name, self.name)
            return

        irc.error(text, notice=notice, source=servuid, private=private)

    def call_cmd(self, irc, source, text, called_in=None):
        """
        Calls a PyLink bot command. source is the caller's UID, and text is the
        full, unparsed text of the message.
        """
        irc.called_in = called_in or source
        irc.called_by = source

        cmd_args = text.strip().split(' ')
        cmd = cmd_args[0].lower()
        cmd_args = cmd_args[1:]
        if cmd not in self.commands:
            # XXX: we really need abstraction for this kind of config fetching...
            show_unknown_cmds = irc.serverdata.get('%s_show_unknown_commands' % self.name,
                                                   conf.conf.get(self.name, {}).get('show_unknown_commands',
                                                   conf.conf['pylink'].get('show_unknown_commands', True)))

            if cmd and show_unknown_cmds and not cmd.startswith('\x01'):
                # Ignore empty commands and invalid command errors from CTCPs.
                self.reply(irc, 'Error: Unknown command %r.' % cmd)
            log.info('(%s/%s) Received unknown command %r from %s', irc.name, self.name, cmd, irc.getHostmask(source))
            return

        log.info('(%s/%s) Calling command %r for %s', irc.name, self.name, cmd, irc.getHostmask(source))
        for func in self.commands[cmd]:
            try:
                func(irc, source, cmd_args)
            except NotAuthorizedError as e:
                self.reply(irc, 'Error: %s' % e)
                log.warning('(%s) Denying access to command %r for %s; msg: %s', irc.name, cmd,
                            irc.getHostmask(source), e)
            except InvalidArgumentsError as e:
                self.reply(irc, 'Error: %s' % e)
            except Exception as e:
                log.exception('Unhandled exception caught in command %r', cmd)
                self.reply(irc, 'Uncaught exception in command %r: %s: %s' % (cmd, type(e).__name__, str(e)))

    def add_cmd(self, func, name=None, featured=False):
        """Binds an IRC command function to the given command name."""
        if name is None:
            name = func.__name__
        name = name.lower()

        # Mark as a featured command if requested to do so.
        if featured:
            self.featured_cmds.add(name)

        self.commands[name].append(func)
        return func

    def _show_command_help(self, irc, command, private=False, shortform=False):
        """
        Shows help for the given command.
        """
        def _reply(text):
            """
            reply() wrapper to handle the private argument.
            """
            self.reply(irc, text, private=private)

        def _reply_format(next_line):
            """
            Formats and outputs the given line.
            """
            next_line = next_line.strip()
            next_line = NORMALIZEWHITESPACE_RE.sub(' ', next_line)
            _reply(next_line)

        if command not in self.commands:
            _reply('Error: Unknown command %r.' % command)
            return
        else:
            funcs = self.commands[command]
            if len(funcs) > 1:
                _reply('The following \x02%s\x02 plugins bind to the \x02%s\x02 command: %s'
                       % (len(funcs), command, ', '.join([func.__module__ for func in funcs])))
            for func in funcs:
                doc = func.__doc__
                mod = func.__module__
                if doc:
                    lines = doc.splitlines()
                    # Bold the first line, which usually just tells you what
                    # arguments the command takes.
                    args_desc = '\x02%s %s\x02' % (command, lines[0])

                    _reply(args_desc.strip())
                    if not shortform:
                        # Note: we handle newlines in docstrings a bit differently. Per
                        # https://github.com/GLolol/PyLink/issues/307, only double newlines (and
                        # combinations of more) have the effect of showing a new line on IRC.
                        # Single newlines are stripped so that word wrap can be applied in source
                        # code without affecting the output on IRC.
                        # TODO: we should probably verify that the output line doesn't exceed IRC
                        # line length limits...
                        next_line = ''
                        for linenum, line in enumerate(lines[1:], 1):
                            stripped_line = line.strip()
                            log.debug("_show_command_help: Current line (%s): %r", linenum, stripped_line)
                            log.debug("_show_command_help: Last line (%s-1=%s): %r", linenum, linenum-1, lines[linenum-1].strip())

                            if stripped_line:
                                # If this line has content, join it with the previous one.
                                next_line += line.rstrip()
                                next_line += ' '
                            elif linenum > 0 and not lines[linenum-1].strip():
                                # The line before us was empty, so treat this one as a legitimate
                                # newline/break.
                                log.debug("_show_command_help: Adding an extra break...")
                                _reply(' ')
                            else:
                                # Otherwise, output it to IRC.
                                _reply_format(next_line)
                                next_line = ''  # Reset the next line buffer
                        else:
                            _reply_format(next_line)
                else:
                    _reply("Error: Command %r doesn't offer any help." % command)
                    return

    def help(self, irc, source, args):
        """<command>

        Gives help for <command>, if it is available."""
        try:
            command = args[0].lower()
        except IndexError:
            # No argument given: show service description (if present), 'list' output, and a list
            # of featured commands.
            if self.desc:
                self.reply(irc, self.desc)
                self.reply(irc, " ")  # Extra newline to unclutter the output text

            self.listcommands(irc, source, args)
            return
        else:
            self._show_command_help(irc, command)

    def listcommands(self, irc, source, args):
        """[<plugin name>]

        Returns a list of available commands this service has to offer. The optional
        plugin name argument also allows you to filter commands by plugin (case
        insensitive)."""

        try:
            plugin_filter = args[0].lower()
        except IndexError:
            plugin_filter = None

        # Don't show CTCP handlers in the public command list.
        cmds = sorted(cmd for cmd in self.commands.keys() if '\x01' not in cmd)

        if plugin_filter is not None:
            # Filter by plugin, if the option was given.
            new_cmds = []

            # Add the pylinkirc.plugins prefix to the module name, so it can be used for matching.
            plugin_module = PLUGIN_PREFIX + plugin_filter

            for cmd_definition in cmds:
                for cmdfunc in self.commands[cmd_definition]:
                    if cmdfunc.__module__.lower() == plugin_module:
                        new_cmds.append(cmd_definition)

            # Replace the old command list.
            cmds = new_cmds

        if cmds:
            self.reply(irc, 'Available commands include: %s' % ', '.join(cmds))
            self.reply(irc, 'To see help on a specific command, type \x02help <command>\x02.')
        elif not plugin_filter:
            self.reply(irc, 'This service doesn\'t provide any public commands.')
        else:
            self.reply(irc, 'This service doesn\'t provide any public commands from the plugin %s.' % plugin_filter)

        # If there are featured commands, list them by showing the help for each.
        # These definitions are sent in private to prevent flooding in channels.
        if self.featured_cmds and not plugin_filter:
            self.reply(irc, " ", private=True)
            self.reply(irc, 'Featured commands include:', private=True)
            for cmd in sorted(self.featured_cmds):
                if cmd in cmds:
                    # Only show featured commands that are both defined and loaded.
                    # TODO: perhaps plugin unload should remove unused featured command
                    # definitions automatically?
                    self._show_command_help(irc, cmd, private=True, shortform=True)
            self.reply(irc, 'End of command listing.', private=True)

def registerService(name, *args, **kwargs):
    """Registers a service bot."""
    name = name.lower()
    if name in world.services:
        raise ValueError("Service name %s is already bound!" % name)

    # Allow disabling service spawning either globally or by service.
    elif name != 'pylink' and not (conf.conf.get(name, {}).get('spawn_service',
            conf.conf['bot'].get('spawn_services', True))):
        return world.services['pylink']

    world.services[name] = sbot = ServiceBot(name, *args, **kwargs)
    sbot.spawn()
    return sbot

def unregisterService(name):
    """Unregisters an existing service bot."""
    name = name.lower()

    if name not in world.services:
        # Service bot doesn't exist; ignore.
        return

    sbot = world.services[name]
    for ircnet, uid in sbot.uids.items():
        ircobj = world.networkobjects[ircnet]
        # Special case for the main PyLink client. If we're unregistering that,
        # clear the irc.pseudoclient entry.
        if name == 'pylink':
            ircobj.pseudoclient = None

        ircobj.proto.quit(uid, "Service unloaded.")

    del world.services[name]

def wrapArguments(prefix, args, length, separator=' ', max_args_per_line=0):
    """
    Takes a static prefix and a list of arguments, and returns a list of strings
    with the arguments wrapped across multiple lines. This is useful for breaking up
    long SJOIN or MODE strings so they aren't cut off by message length limits.
    """
    strings = []

    assert args, "wrapArguments: no arguments given"

    buf = prefix

    args = list(args)

    while args:
        assert len(prefix+args[0]) <= length, \
            "wrapArguments: Argument %r is too long for the given length %s" % (args[0], length)

        # Add arguments until our buffer is up to the length limit.
        if (len(buf + args[0]) + 1) <= length and ((not max_args_per_line) or len(buf.split(' ')) < max_args_per_line):
            if buf != prefix:  # Only add a separator if this isn't the first argument of a line
                buf += separator
            buf += args.pop(0)
        else:
            # Once this is full, add the string to the list and reset the buffer.
            strings.append(buf)
            buf = prefix
    else:
        strings.append(buf)

    return strings

class IRCParser(argparse.ArgumentParser):
    """
    Wrapper around argparse.ArgumentParser, without quitting on usage errors.
    """
    REMAINDER = argparse.REMAINDER

    def print_help(self, *args, **kwargs):
        # XXX: find a way to somehow route this through IRC
        raise InvalidArgumentsError("Use help <commandname> to receive help for PyLink commands.")

    def error(self, message, *args, **kwargs):
        raise InvalidArgumentsError(message)
    _print_message = error  # XXX: ugly

    def exit(self, *args):
        return

class DeprecatedAttributesObject():
    """
    Object implementing deprecated attributes and warnings on access.
    """
    def __init__(self):
        self.deprecated_attributes = {}

    def __getattribute__(self, attr):
        # Note: "self.deprecated_attributes" calls this too, so the != check is
        # needed to prevent a recursive loop!
        if attr != 'deprecated_attributes' and attr in self.deprecated_attributes:
            log.warning('Attribute %s.%s is deprecated: %s' % (self.__class__.__name__, attr,
                        self.deprecated_attributes.get(attr)))

        return object.__getattribute__(self, attr)
