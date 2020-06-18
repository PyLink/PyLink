"""
utils.py - PyLink utilities module.

This module contains various utility functions related to IRC and/or the PyLink
framework.
"""

import argparse
import collections
import functools
import importlib
import ipaddress
import os
import re
import string

# Load the protocol and plugin packages.
from pylinkirc import plugins, protocols

from . import conf, structures, world
from .log import log

__all__ = ['PLUGIN_PREFIX', 'PROTOCOL_PREFIX', 'NORMALIZEWHITESPACE_RE',
           'NotAuthorizedError', 'InvalidArgumentsError', 'ProtocolError',
           'add_cmd', 'add_hook', 'expand_path', 'split_hostmask',
           'ServiceBot', 'register_service', 'unregister_service',
           'wrap_arguments', 'IRCParser', 'strip_irc_formatting',
           'remove_range', 'get_hostname_type', 'parse_duration', 'match_text',
           'merge_iterables']


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

class ProtocolError(RuntimeError):
    """
    Exception raised when a network protocol violation is encountered in some way.
    """

def add_cmd(func, name=None, **kwargs):
    """Binds an IRC command function to the given command name."""
    world.services['pylink'].add_cmd(func, name=name, **kwargs)
    return func

def add_hook(func, command, priority=100):
    """
    Binds a hook function to the given command name.

    A custom priority can also be given (defaults to 100), and hooks with
    higher priority values will be called first."""
    command = command.upper()
    world.hooks[command].append((priority, func))
    world.hooks[command].sort(key=lambda pair: pair[0], reverse=True)
    return func

def expand_path(path):
    """
    Returns a path expanded with environment variables and home folders (~) expanded, in that order."""
    return os.path.expanduser(os.path.expandvars(path))
expandpath = expand_path  # Consistency with os.path

def _reset_module_dirs():
    """
    (Re)sets custom protocol module and plugin directories to the ones specified in the config.
    """
    # Note: This assumes that the first element of the package path is the default one.
    plugins.__path__ = [plugins.__path__[0]] + [expandpath(path) for path in conf.conf['pylink'].get('plugin_dirs', [])]
    log.debug('_reset_module_dirs: new pylinkirc.plugins.__path__: %s', plugins.__path__)
    protocols.__path__ = [protocols.__path__[0]] + [expandpath(path) for path in conf.conf['pylink'].get('protocol_dirs', [])]
    log.debug('_reset_module_dirs: new pylinkirc.protocols.__path__: %s', protocols.__path__)
resetModuleDirs = _reset_module_dirs

def _load_plugin(name):
    """
    Imports and returns the requested plugin.
    """
    return importlib.import_module(PLUGIN_PREFIX + name)
loadPlugin = _load_plugin

def _get_protocol_module(name):
    """
    Imports and returns the protocol module requested.
    """
    return importlib.import_module(PROTOCOL_PREFIX + name)
getProtocolModule = _get_protocol_module

def split_hostmask(mask):
    """
    Returns a nick!user@host hostmask split into three fields: nick, user, and host.
    """
    nick, identhost = mask.split('!', 1)
    ident, host = identhost.split('@', 1)
    if not all({nick, ident, host}):
        raise ValueError("Invalid user@host %r" % mask)
    return [nick, ident, host]
splitHostmask = split_hostmask

class ServiceBot():
    """
    PyLink IRC Service class.
    """

    def __init__(self, name, default_help=True, default_list=True, manipulatable=False, default_nick=None, desc=None):
        # Service name and default nick
        self.name = name
        self.default_nick = default_nick

        # Tracks whether the bot should be manipulatable by the 'bots' plugin and other commands.
        self.manipulatable = manipulatable

        # We make the command definitions a dict of lists of functions. Multiple
        # plugins are actually allowed to bind to one function name; this just causes
        # them to be called in the order that they are bound.
        self.commands = collections.defaultdict(list)

        # This tracks the UIDs of the service bot on different networks, as they are
        # spawned.
        self.uids = {}

        # Track plugin-defined persistent channels. The bot will leave them if they're empty,
        # and rejoin whenever someone else does.
        # This is stored as a nested dictionary:
        # {"plugin1": {"net1": IRCCaseInsensitiveSet({"#a", "#b"}), "net2": ...}, ...}
        self.dynamic_channels = {}

        # Service description, used in the default help command if one is given.
        self.desc = desc

        # List of command names to "feature"
        self.featured_cmds = set()

        # Maps command aliases to the respective primary commands
        self.alias_cmds = {}

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
                irc.call_hooks([None, 'PYLINK_NEW_SERVICE', {'name': self.name}])
        else:
            raise NotImplementedError("Network specific plugins not supported yet.")

    def join(self, irc, channels, ignore_empty=None):
        """
        Joins the given service bot to the given channel(s). "channels" can be
        an iterable of channel names or the name of a single channel (type 'str').

        The ignore_empty option sets whether we should skip joining empty
        channels and join them later when we see someone else join (for channels
        marked persistent). This option is automatically *disabled* on networks
        where we cannot monitor channels that we're not in (e.g. Clientbot).

        Before PyLink 2.0-alpha3, this function implicitly marked channels it
        receives to be persistent. This behaviour is no longer the case.
        """
        uid = self.uids.get(irc.name)
        if uid is None:
            return

        if isinstance(channels, str):
            channels = [channels]

        if irc.has_cap('visible-state-only'):
            # Disable dynamic channel joining on networks where we can't monitor channels for joins.
            ignore_empty = False
        elif ignore_empty is None:
            ignore_empty = not (irc.serverdata.get('join_empty_channels',
                                                   conf.conf['pylink'].get('join_empty_channels',
                                                                           False)))

        # Specify modes to join the services bot with.
        joinmodes = irc.get_service_option(self.name, 'joinmodes', default='')
        joinmodes = ''.join([m for m in joinmodes if m in irc.prefixmodes])

        for channel in channels:
            if irc.is_channel(channel):
                if channel in irc.channels:
                    if uid in irc.channels[channel].users:
                        log.debug('(%s/%s) Skipping join to %r - we are already present', irc.name, self.name, channel)
                        continue
                elif ignore_empty:
                    log.debug('(%s/%s) Skipping joining empty channel %r', irc.name, self.name, channel)
                    continue

                log.debug('(%s/%s) Joining channel %s with modes %r', irc.name, self.name, channel, joinmodes)

                if joinmodes:  # Modes on join were specified; use SJOIN to burst our service
                    irc.sjoin(irc.sid, channel, [(joinmodes, uid)])
                else:
                    irc.join(uid, channel)

                irc.call_hooks([irc.sid, 'PYLINK_SERVICE_JOIN', {'channel': channel, 'users': [uid]}])
            else:
                log.warning('(%s/%s) Ignoring invalid channel %r', irc.name, self.name, channel)

    def part(self, irc, channels, reason=''):
        """
        Parts the given service bot from the given channel(s) if no plugins
        still register it as a persistent dynamic channel.

        "channels" can be an iterable of channel names or the name of a single
        channel (type 'str').
        """
        uid = self.uids.get(irc.name)
        if uid is None:
            return

        if isinstance(channels, str):
            channels = [channels]

        to_part = []
        persistent_channels = self.get_persistent_channels(irc)
        for channel in channels:
            if channel in irc.channels and uid in irc.channels[channel].users:
                if channel in persistent_channels:
                    log.debug('(%s/%s) Not parting %r because it is registered '
                              'as a dynamic channel: %r', irc.name, self.name, channel,
                              persistent_channels)
                    continue
                to_part.append(channel)
                irc.part(uid, channel, reason)
            else:
                log.debug('(%s/%s) Ignoring part to %r, we are not there', irc.name, self.name, channel)
                continue

        irc.call_hooks([uid, 'PYLINK_SERVICE_PART', {'channels': to_part, 'text': reason}])

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
            log.info('(%s/%s) Received unknown command %r from %s', irc.name, self.name, cmd, irc.get_hostmask(source))
            return

        log.info('(%s/%s) Calling command %r for %s', irc.name, self.name, cmd, irc.get_hostmask(source))
        for func in self.commands[cmd]:
            try:
                func(irc, source, cmd_args)
            except NotAuthorizedError as e:
                self.reply(irc, 'Error: %s' % e)
                log.warning('(%s) Denying access to command %r for %s; msg: %s', irc.name, cmd,
                            irc.get_hostmask(source), e)
            except InvalidArgumentsError as e:
                self.reply(irc, 'Error: %s' % e)
            except Exception as e:
                log.exception('Unhandled exception caught in command %r', cmd)
                self.reply(irc, 'Uncaught exception in command %r: %s: %s' % (cmd, type(e).__name__, str(e)))

    def add_cmd(self, func, name=None, featured=False, aliases=None):
        """Binds an IRC command function to the given command name."""
        if name is None:
            name = func.__name__
        name = name.lower()

        # Mark as a featured command if requested to do so.
        if featured:
            self.featured_cmds.add(name)

        # If this is an alias, store the primary command in the alias_cmds dict
        if aliases is not None:
            for alias in aliases:
                if name == alias:
                    log.error('Refusing to alias command %r (in plugin %r) to itself!', name, func.__module__)
                    continue

                self.add_cmd(func, name=alias)  # Bind the alias as well.
                self.alias_cmds[alias] = name

        self.commands[name].append(func)
        return func

    def get_nick(self, irc, fails=0):
        """
        If the 'fails' argument is set to zero, this method returns the preferred nick for this
        service bot on the given network. The following fields are checked in order:
        # 1) Network specific nick settings for this service (servers:<netname>:servicename_nick)
        # 2) Global settings for this service (servicename:nick)
        # 3) The service's hardcoded default nick.
        # 4) The literal service name.

        If the 'fails' argument is set to a non-zero value, a list of *alternate* (fallback) nicks
        will be fetched from these fields in this order:
        # 1) Network specific altnick settings for this service (servers:<netname>:servicename_altnicks)
        # 2) Global altnick settings for this service (servicename:altnicks)

        If such an alternate nicks list exists, an alternate nick will be chosen based on the value
        of the 'fails' argument:
        - If nick fetching fails once, return the 1st alternate nick from the list,
        - If nick fetching fails twice, return the 2nd alternate nick from the list, ...

        Otherwise, if the alternate nicks list doesn't exist, or if there is no corresponding value
        for the current 'fails' value, the preferred nick plus the 'fails' number of underscores (_)
        will be used instead.
        - fails=1 => preferred_nick_
        - fails=2 => preferred_nick__

        If the resulting nick is too long for the given network, ProtocolError will be raised.
        """
        sbconf = conf.conf.get(self.name, {})
        nick = irc.serverdata.get("%s_nick" % self.name) or sbconf.get('nick') or self.default_nick or self.name

        if fails >= 1:
            altnicks = irc.serverdata.get("%s_altnicks" % self.name) or sbconf.get('altnicks') or []
            try:
                nick = altnicks[fails-1]
            except IndexError:
                nick += ('_' * fails)

        if irc.maxnicklen > 0 and len(nick) > irc.maxnicklen:
            raise ProtocolError("Nick %r too long for network (maxnicklen=%s)" % (nick, irc.maxnicklen))

        assert nick
        return nick

    def get_ident(self, irc):
        """
        Returns the preferred ident for this service bot on the given network. The following fields are checked in order:
        # 1) Network specific ident settings for this service (servers:<netname>:servicename_ident)
        # 2) Global settings for this service (servicename:ident)
        # 3) The service's hardcoded default nick.
        # 4) The literal service name.
        """
        sbconf = conf.conf.get(self.name, {})
        return irc.serverdata.get("%s_ident" % self.name) or sbconf.get('ident') or self.default_nick or self.name

    def get_host(self, irc):
        """
        Returns the preferred hostname for this service bot on the given network. The following fields are checked in order:
        # 1) Network specific hostname settings for this service (servers:<netname>:servicename_host)
        # 2) Global settings for this service (servicename:host)
        # 3) The PyLink server hostname.
        """
        sbconf = conf.conf.get(self.name, {})
        return irc.serverdata.get("%s_host" % self.name) or sbconf.get('host') or irc.hostname()

    def get_realname(self, irc):
        """
        Returns the preferred real name for this service bot on the given network. The following fields are checked in order:
        # 1) Network specific realname settings for this service (servers:<netname>:servicename_realname)
        # 2) Global settings for this service (servicename:realname)
        # 3) The globally configured real name (pylink:realname).
        # 4) The literal service name.
        """
        sbconf = conf.conf.get(self.name, {})
        return irc.serverdata.get("%s_realname" % self.name) or sbconf.get('realname') or conf.conf['pylink'].get('realname') or self.name

    def add_persistent_channel(self, irc, namespace, channel, try_join=True):
        """
        Adds a persistent channel to the service bot on the given network and namespace.
        """
        namespace = self.dynamic_channels.setdefault(namespace, {})
        chanlist = namespace.setdefault(irc.name, structures.IRCCaseInsensitiveSet(irc))
        chanlist.add(channel)

        if try_join and irc.has_cap('can-manage-bot-channels'):
            self.join(irc, [channel])

    def remove_persistent_channel(self, irc, namespace, channel, try_part=True, part_reason=''):
        """
        Removes a persistent channel from the service bot on the given network and namespace.
        """
        chanlist = self.dynamic_channels[namespace][irc.name].remove(channel)

        if try_part and irc.connected.is_set() and irc.has_cap('can-manage-bot-channels'):
            self.part(irc, [channel], reason=part_reason)

    def get_persistent_channels(self, irc, namespace=None):
        """
        Returns a set of persistent channels for the IRC network, optionally filtering
        by namespace is one is given.
        """
        channels = structures.IRCCaseInsensitiveSet(irc)
        if namespace:
            chanlist = self.dynamic_channels.get(namespace, {}).get(irc.name, set())
            log.debug('(%s/%s) get_persistent_channels: adding channels '
                      '%r from namespace %r (single)', irc.name, self.name,
                      chanlist, namespace)
            channels |= chanlist
        else:
            for dch_namespace, dch_data in self.dynamic_channels.items():
                chanlist = dch_data.get(irc.name, set())
                log.debug('(%s/%s) get_persistent_channels: adding channels '
                          '%r from namespace %r', irc.name, self.name,
                          chanlist, dch_namespace)
                channels |= chanlist
        channels |= set(irc.serverdata.get(self.name+'_channels', []))
        channels |= set(irc.serverdata.get('channels', []))
        return channels

    def clear_persistent_channels(self, irc, namespace, try_part=True, part_reason=''):
        """
        Clears the persistent channels defined by a namespace.

        irc can be None to clear persistent channels for all networks in this namespace.
        """
        dch_data = self.dynamic_channels.get(namespace, {})

        if irc is not None:
            if irc.name in dch_data:
                chanlist = dch_data[irc.name]
                log.debug('(%s/%s) Clearing persistent channels %r from namespace %r',
                          irc.name, self.name, chanlist, namespace)

                del dch_data[irc.name]

                if try_part:
                    self.part(irc, chanlist, reason=part_reason)


        else:  # when irc is None
            del self.dynamic_channels[namespace]

            for netname, chanlist in dch_data.items():
                log.debug('(%s/%s) Globally clearing persistent channels %r from namespace %r',
                          netname, self.name, chanlist, namespace)
                if try_part and netname in world.networkobjects:
                    self.part(world.networkobjects[netname], chanlist,
                              reason=part_reason)


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
                        # https://github.com/jlu5/PyLink/issues/307, only double newlines (and
                        # combinations of more) have the effect of showing a new line on IRC.
                        # Single newlines are stripped so that word wrap can be applied in source
                        # code without affecting the output on IRC.
                        # (On the same topic, real line wrapping on IRC is done in irc.msg() as of
                        #  2.0-beta1)
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
                            # Show the last line.
                            _reply_format(next_line)
                else:
                    _reply("Error: Command %r doesn't offer any help." % command)

                # Regardless of whether help text is available, mention aliases.
                if not shortform:
                    if command in self.alias_cmds:
                        _reply(' ')
                        _reply('This command is an alias for \x02%s\x02.' % self.alias_cmds[command])
                    aliases = set(alias for alias, primary in self.alias_cmds.items() if primary == command)
                    if aliases:
                        _reply(' ')
                        _reply('Available aliases: \x02%s\x02' % ', '.join(aliases))

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

        # Don't show CTCP handlers or aliases in the public command list.
        cmds = sorted(cmd for cmd in self.commands.keys() if '\x01' not in cmd and cmd not in self.alias_cmds)

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

def register_service(name, *args, **kwargs):
    """Registers a service bot."""
    name = name.lower()
    if name in world.services:
        raise ValueError("Service name %s is already bound!" % name)

    # Allow disabling service spawning either globally or by service.
    elif name != 'pylink' and not (conf.conf.get(name, {}).get('spawn_service',
            conf.conf['pylink'].get('spawn_services', True))):
        return world.services['pylink']

    world.services[name] = sbot = ServiceBot(name, *args, **kwargs)
    sbot.spawn()
    return sbot
registerService = register_service

def unregister_service(name):
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

        ircobj.quit(uid, "Service unloaded.")

    del world.services[name]
unregisterService = unregister_service

def wrap_arguments(prefix, args, length, separator=' ', max_args_per_line=0):
    """
    Takes a static prefix and a list of arguments, and returns a list of strings
    with the arguments wrapped across multiple lines. This is useful for breaking up
    long SJOIN or MODE strings so they aren't cut off by message length limits.
    """
    strings = []

    assert args, "wrap_arguments: no arguments given"

    buf = prefix

    args = list(args)

    while args:
        assert len(prefix+args[0]) <= length, \
            "wrap_arguments: Argument %r is too long for the given length %s" % (args[0], length)

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
wrapArguments = wrap_arguments

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

# From http://modern.ircdocs.horse/formatting.html
_strip_color_regex = re.compile(r'\x03(\d{1,2}(,\d{1,2})?)?')
_irc_formatting_chars = "\x02\x1D\x1F\x1E\x11\x16\x0F\x03"

def strip_irc_formatting(text):
    """Returns text with IRC formatting (colors, underlines, bold, italics, reverse) removed."""
    text = _strip_color_regex.sub('', text)
    for char in _irc_formatting_chars:
        text = text.replace(char, '')
    return text

_subrange_re = re.compile(r'(?P<start>(\d+))-(?P<end>(\d+))')
def remove_range(rangestr, mylist):
    """
    Removes a range string of (one-indexed) items from the list.
    Range strings are indices or ranges of them joined together with a ",":
    e.g. "5", "2", "2-10", "1,3,5-8"

    See test/test_utils.py for more complete examples.
    """
    if None in mylist:
        raise ValueError("mylist must not contain None!")

    # Split and filter out empty subranges
    ranges = filter(None, rangestr.split(','))
    if not ranges:
        raise ValueError("Invalid range string %r" % rangestr)

    for subrange in ranges:
        match = _subrange_re.match(subrange)
        if match:
            start = int(match.group('start'))
            end = int(match.group('end'))

            if end <= start:
                raise ValueError("Range start (%d) is <= end (%d) in range string %r" %
                                 (start, end, rangestr))
            elif 0 in (end, start):
                raise ValueError("Got range index 0 in range string %r, this function is one-indexed" %
                                 rangestr)

            # For our purposes, make sure the start and end are within the list
            mylist[start-1], mylist[end-1]

            # Replace the entire range with None's
            log.debug('utils.remove_range: removing items from %s to %s: %s', start, end, mylist[start-1:end])
            mylist[start-1:end] = [None] * (end-(start-1))

        elif subrange in string.digits:
            index = int(subrange)
            if index == 0:
                raise ValueError("Got index 0 in range string %r, this function is one-indexed" %
                                 rangestr)
            log.debug('utils.remove_range: removing item %s: %s', index, mylist[index-1])
            mylist[index-1] = None

        else:
            raise ValueError("Got invalid subrange %r in range string %r" %
                             (subrange, rangestr))

    return list(filter(lambda x: x is not None, mylist))

def get_hostname_type(address):
    """
    Returns whether the given address is an IPv4 address (1), IPv6 address (2), or neither
    (0; assumed to be a hostname instead).
    """
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return 0
    else:
        if isinstance(ip, ipaddress.IPv4Address):
            return 1
        elif isinstance(ip, ipaddress.IPv6Address):
            return 2
        else:
            raise ValueError("Got unknown value %r from ipaddress.ip_address()" % address)

_duration_re = re.compile(r"^((?P<week>\d+)w)?((?P<day>\d+)d)?((?P<hour>\d+)h)?((?P<minute>\d+)m)?((?P<second>\d+)s)?$")
def parse_duration(text):
    """
    Takes in a duration string and returns the equivalent amount of seconds.

    Time strings are in the following format:
    - '123'         => 123 seconds
                       (positive integers are treated as # of seconds)
    - '1w2d3h4m5s'  => 1 week, 2 days, 3 hours, 4 minutes, and 5 seconds
                       (must be in decreasing order by unit)
    - '72h'         => 72 hours
    - '1h5s'        => 1 hour and 5 seconds
    and so on...
    """
    # If we get an already valid number, just return it
    if text.isdigit():
        return int(text)

    match = _duration_re.match(text)
    if not match:
        raise ValueError("Failed to parse duration string %r" % text)
    result = 0
    matched = 0

    if match.group('week'):
        result += int(match.group('week'))   *  7 * 24 * 60 * 60
        matched += 1
    if match.group('day'):
        result += int(match.group('day'))    * 24 * 60 * 60
        matched += 1
    if match.group('hour'):
        result += int(match.group('hour'))   * 60 * 60
        matched += 1
    if match.group('minute'):
        result += int(match.group('minute')) * 60
        matched += 1
    if match.group('second'):
        result += int(match.group('second'))
        matched += 1

    if not matched:
        raise ValueError("Failed to parse duration string %r" % text)

    return result

@functools.lru_cache(maxsize=1024)
def _glob2re(glob):
    """Converts an IRC-style glob to a regular expression."""
    patt = ['^']

    for char in glob:
        if char == '*' and patt[-1] != '*':  # Collapse ** into *
            patt.append('.*')
        elif char == '?':
            patt.append('.')
        else:
            patt.append(re.escape(char))

    patt.append('$')
    return ''.join(patt)

def match_text(glob, text, filterfunc=str.lower):
    """
    Returns whether glob matches text. If filterfunc is specified, run filterfunc on glob and text
    before preforming matches.
    """
    if filterfunc:
        glob = filterfunc(glob)
        text = filterfunc(text)

    return re.match(_glob2re(glob), text)

def merge_iterables(A, B):
    """
    Merges the values in two iterables. A and B must be of the same type, and one of the following:

    - list: items are combined as A + B
    - set:  items are combined as A | B
    - dict: items are combined as {**A, **B}
    """
    if type(A) != type(B):
        raise ValueError("inputs must be the same type")

    if isinstance(A, list):
        return A + B
    elif isinstance(A, set):
        return A | B
    elif isinstance(A, dict):
        return {**A, **B}
