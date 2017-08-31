"""
classes.py - Base classes for PyLink IRC Services.

This module contains the base classes used by PyLink, including threaded IRC
connections and objects used to represent IRC servers, users, and channels.

Here be dragons.
"""

import threading
import time
import socket
import ssl
import hashlib
import inspect
import ipaddress
import queue
import functools
import string
import re

try:
    import ircmatch
except ImportError:
    raise ImportError("PyLink requires ircmatch to function; please install it and try again.")

from . import world, utils, structures, conf, __version__
from .log import *
from .coremods import control
from .utils import ProtocolError  # Compatibility with PyLink 1.x

### Internal classes (users, servers, channels)

class ChannelState(structures.IRCCaseInsensitiveDict):
    """
    A dictionary storing channels case insensitively. Channel objects are initialized on access.
    """
    def __getitem__(self, key):
        key = self._keymangle(key)

        if key not in self._data:
            log.debug('(%s) ChannelState: creating new channel %s in memory', self._irc.name, key)
            self._data[key] = newchan = Channel(self._irc, key)
            return newchan

        return self._data[key]

class PyLinkNetworkCore(structures.DeprecatedAttributesObject, structures.CamelCaseToSnakeCase):
    """Base IRC object for PyLink."""

    def __init__(self, netname):
        self.deprecated_attributes = {
            'conf': 'Deprecated since 1.2; consider switching to conf.conf',
            'botdata': "Deprecated since 1.2; consider switching to conf.conf['pylink']",
        }

        self.loghandlers = []
        self.name = netname
        self.conf = conf.conf
        self.sid = None
        self.serverdata = conf.conf['servers'][netname]
        self.botdata = conf.conf['pylink']
        self.protoname = self.__class__.__module__.split('.')[-1]  # Remove leading pylinkirc.protocols.
        self.proto = self.irc = self  # Backwards compat

        # Protocol stuff
        self.casemapping = 'rfc1459'
        self.hook_map = {}

        # Lists required conf keys for the server block.
        self.conf_keys = {'ip', 'port', 'hostname', 'sid', 'sidrange', 'protocol', 'sendpass',
                          'recvpass'}

        # Defines a set of PyLink protocol capabilities
        self.protocol_caps = set()

        # These options depend on self.serverdata from above to be set.
        self.encoding = None

        self.connected = threading.Event()
        self._aborted = threading.Event()
        self._reply_lock = threading.RLock()

        # Sets the multiplier for autoconnect delay (grows with time).
        self.autoconnect_active_multiplier = 1

        self.was_successful = False

        self._init_vars()

    def log_setup(self):
        """
        Initializes any channel loggers defined for the current network.
        """
        try:
            channels = conf.conf['logging']['channels'][self.name]
        except KeyError:  # Not set up; just ignore.
            return

        log.debug('(%s) Setting up channel logging to channels %r', self.name,
                  channels)

        if not self.loghandlers:
            # Only create handlers if they haven't already been set up.

            for channel, chandata in channels.items():
                # Fetch the log level for this channel block.
                level = None
                if chandata is not None:
                    level = chandata.get('loglevel')

                handler = PyLinkChannelLogger(self, channel, level=level)
                self.loghandlers.append(handler)
                log.addHandler(handler)

    def _init_vars(self):
        """
        (Re)sets an IRC object to its default state. This should be called when
        an IRC object is first created, and on every reconnection to a network.
        """
        self.encoding = self.serverdata.get('encoding') or 'utf-8'

        # Tracks the main PyLink client's UID.
        self.pseudoclient = None

        # Internal variable to set the place and caller of the last command (in PM
        # or in a channel), used by fantasy command support.
        self.called_by = None
        self.called_in = None

        # Intialize the server, channel, and user indexes to be populated by
        # our protocol module.
        self.servers = {}
        self.users = {}

        # Two versions of the channels index exist in PyLink 2.0, and they are joined together
        # - irc._channels which implicitly creates channels on access (mostly used
        #   in protocol modules)
        # - irc.channels which does not (recommended for use by plugins)
        self._channels = ChannelState(self)
        self.channels = structures.IRCCaseInsensitiveDict(self, data=self._channels._data)

        # This sets the list of supported channel and user modes: the default
        # RFC1459 modes are implied. Named modes are used here to make
        # protocol-independent code easier to write, as mode chars vary by
        # IRCd.
        # Protocol modules should add to and/or replace this with what their
        # protocol supports. This can be a hardcoded list or something
        # negotiated on connect, depending on the nature of their protocol.
        self.cmodes = {'op': 'o', 'secret': 's', 'private': 'p',
                       'noextmsg': 'n', 'moderated': 'm', 'inviteonly': 'i',
                       'topiclock': 't', 'limit': 'l', 'ban': 'b',
                       'voice': 'v', 'key': 'k',
                       # This fills in the type of mode each mode character is.
                       # A-type modes are list modes (i.e. bans, ban exceptions, etc.),
                       # B-type modes require an argument to both set and unset,
                       #   but there can only be one value at a time
                       #   (i.e. cmode +k).
                       # C-type modes require an argument to set but not to unset
                       #   (one sets "+l limit" and # "-l"),
                       # and D-type modes take no arguments at all.
                       '*A': 'b',
                       '*B': 'k',
                       '*C': 'l',
                       '*D': 'imnpst'}
        self.umodes = {'invisible': 'i', 'snomask': 's', 'wallops': 'w',
                       'oper': 'o',
                       '*A': '', '*B': '', '*C': '', '*D': 'iosw'}

        # Acting extbans such as +b m:n!u@h on InspIRCd
        self.extbans_acting = {}
        # Matching extbans such as R:account on InspIRCd and $a:account on TS6.
        self.extbans_matching = {}

        # This max nick length starts off as the config value, but may be
        # overwritten later by the protocol module if such information is
        # received. It defaults to 30.
        self.maxnicklen = self.serverdata.get('maxnicklen', 30)

        # Defines a list of supported prefix modes.
        self.prefixmodes = {'o': '@', 'v': '+'}

        # Defines the uplink SID (to be filled in by protocol module).
        self.uplink = None
        self.start_ts = int(time.time())

        # Set up channel logging for the network
        self.log_setup()

    def __repr__(self):
        return "<%s object for network %r>" % (self.__class__.__name__, self.name)

    ## Stubs
    def validate_server_conf(self):
        return

    def connect(self):
        raise NotImplementedError

    def disconnect(self):
        raise NotImplementedError

    ## General utility functions
    def call_hooks(self, hook_args):
        """Calls a hook function with the given hook args."""
        numeric, command, parsed_args = hook_args
        # Always make sure TS is sent.
        if 'ts' not in parsed_args:
            parsed_args['ts'] = int(time.time())
        hook_cmd = command
        hook_map = self.hook_map

        # If the hook name is present in the protocol module's hook_map, then we
        # should set the hook name to the name that points to instead.
        # For example, plugins will read SETHOST as CHGHOST, EOS (end of sync)
        # as ENDBURST, etc.
        if command in hook_map:
            hook_cmd = hook_map[command]

        # However, individual handlers can also return a 'parse_as' key to send
        # their payload to a different hook. An example of this is "/join 0"
        # being interpreted as leaving all channels (PART).
        hook_cmd = parsed_args.get('parse_as') or hook_cmd

        log.debug('(%s) Raw hook data: [%r, %r, %r] received from %s handler '
                  '(calling hook %s)', self.name, numeric, hook_cmd, parsed_args,
                  command, hook_cmd)

        # Iterate over registered hook functions, catching errors accordingly.
        for hook_func in world.hooks[hook_cmd]:
            try:
                log.debug('(%s) Calling hook function %s from plugin "%s"', self.name,
                          hook_func, hook_func.__module__)
                hook_func(self, numeric, command, parsed_args)
            except Exception:
                # We don't want plugins to crash our servers...
                log.exception('(%s) Unhandled exception caught in hook %r from plugin "%s"',
                              self.name, hook_func, hook_func.__module__)
                log.error('(%s) The offending hook data was: %s', self.name,
                          hook_args)
                continue

    def call_command(self, source, text):
        """
        Calls a PyLink bot command. source is the caller's UID, and text is the
        full, unparsed text of the message.
        """
        world.services['pylink'].call_cmd(self, source, text)

    def msg(self, target, text, notice=None, source=None, loopback=True):
        """Handy function to send messages/notices to clients. Source
        is optional, and defaults to the main PyLink client if not specified."""
        if not text:
            return

        if not (source or self.pseudoclient):
            # No explicit source set and our main client wasn't available; abort.
            return
        source = source or self.pseudoclient.uid

        if notice:
            self.notice(source, target, text)
            cmd = 'PYLINK_SELF_NOTICE'
        else:
            self.message(source, target, text)
            cmd = 'PYLINK_SELF_PRIVMSG'

        if loopback:
            # Determines whether we should send a hook for this msg(), to relay things like services
            # replies across relay.
            self.call_hooks([source, cmd, {'target': target, 'text': text}])

    def _reply(self, text, notice=None, source=None, private=None, force_privmsg_in_private=False,
            loopback=True):
        """
        Core of the reply() function - replies to the last caller in the right context
        (channel or PM).
        """
        if private is None:
            # Allow using private replies as the default, if no explicit setting was given.
            private = conf.conf['pylink'].get("prefer_private_replies")

        # Private reply is enabled, or the caller was originally a PM
        if private or (self.called_in in self.users):
            if not force_privmsg_in_private:
                # For private replies, the default is to override the notice=True/False argument,
                # and send replies as notices regardless. This is standard behaviour for most
                # IRC services, but can be disabled if force_privmsg_in_private is given.
                notice = True
            target = self.called_by
        else:
            target = self.called_in

        self.msg(target, text, notice=notice, source=source, loopback=loopback)

    def reply(self, *args, **kwargs):
        """
        Replies to the last caller in the right context (channel or PM).

        This function wraps around _reply() and can be monkey-patched in a thread-safe manner
        to temporarily redirect plugin output to another target.
        """
        with self._reply_lock:
            self._reply(*args, **kwargs)

    def error(self, text, **kwargs):
        """Replies with an error to the last caller in the right context (channel or PM)."""
        # This is a stub to alias error to reply
        self.reply("Error: %s" % text, **kwargs)

    ## Configuration-based lookup functions.
    def version(self):
        """
        Returns a detailed version string including the PyLink daemon version,
        the protocol module in use, and the server hostname.
        """
        fullversion = 'PyLink-%s. %s :[protocol:%s, encoding:%s]' % (__version__, self.hostname(), self.protoname, self.encoding)
        return fullversion

    def hostname(self):
        """
        Returns the server hostname used by PyLink on the given server.
        """
        return self.serverdata.get('hostname', world.fallback_hostname)

    def get_full_network_name(self):
        """
        Returns the full network name (as defined by the "netname" option), or the
        short network name if that isn't defined.
        """
        return self.serverdata.get('netname', self.name)


    def has_cap(self, capab):
        """
        Returns whether this protocol module instance has the requested capability.
        """
        return capab.lower() in self.protocol_caps

    ## Shared helper functions
    def _pre_connect(self):
        self._aborted.clear()
        self._init_vars()

        try:
            self.validate_server_conf()
        except Exception as e:
            log.error("(%s) Configuration error: %s", self.name, e)
            raise

    def _run_autoconnect(self):
        """Blocks for the autoconnect time and returns True if autoconnect is enabled."""
        autoconnect = self.serverdata.get('autoconnect')

        # Sets the autoconnect growth multiplier (e.g. a value of 2 multiplies the autoconnect
        # time by 2 on every failure, etc.)
        autoconnect_multiplier = self.serverdata.get('autoconnect_multiplier', 2)
        autoconnect_max = self.serverdata.get('autoconnect_max', 1800)
        # These values must at least be 1.
        autoconnect_multiplier = max(autoconnect_multiplier, 1)
        autoconnect_max = max(autoconnect_max, 1)

        log.debug('(%s) _run_autoconnect: Autoconnect delay set to %s seconds.', self.name, autoconnect)
        if autoconnect is not None and autoconnect >= 1:
            log.debug('(%s) _run_autoconnect: Multiplying autoconnect delay %s by %s.', self.name, autoconnect, self.autoconnect_active_multiplier)
            autoconnect *= self.autoconnect_active_multiplier
            # Add a cap on the max. autoconnect delay, so that we don't go on forever...
            autoconnect = min(autoconnect, autoconnect_max)

            log.info('(%s) _run_autoconnect: Going to auto-reconnect in %s seconds.', self.name, autoconnect)
            # Continue when either self._aborted is set or the autoconnect time passes.
            # Compared to time.sleep(), this allows us to stop connections quicker if we
            # break while while for autoconnect.
            self._aborted.clear()
            self._aborted.wait(autoconnect)

            # Store in the local state what the autoconnect multiplier currently is.
            self.autoconnect_active_multiplier *= autoconnect_multiplier

            if self not in world.networkobjects.values():
                log.debug('(%s) _run_autoconnect: Stopping stale connect loop', self.name)
                return
            return True

        else:
            log.debug('(%s) _run_autoconnect: Stopping connect loop (autoconnect value %r is < 1).', self.name, autoconnect)
            return

    def _pre_disconnect(self):
        self._aborted.set()
        self.was_successful = self.connected.is_set()
        log.debug('(%s) _pre_disconnect: got %s for was_successful state', self.name, self.was_successful)

        log.debug('(%s) _pre_disconnect: Clearing self.connected state.', self.name)
        self.connected.clear()

        log.debug('(%s) _pre_disconnect: Removing channel logging handlers due to disconnect.', self.name)
        while self.loghandlers:
            log.removeHandler(self.loghandlers.pop())

    def _post_disconnect(self):

        # Internal hook signifying that a network has disconnected.
        self.call_hooks([None, 'PYLINK_DISCONNECT', {'was_successful': self.was_successful}])

        log.debug('(%s) _post_disconnect: Clearing state via _init_vars().', self.name)
        self._init_vars()

    def _remove_client(self, numeric):
        """Internal function to remove a client from our internal state."""
        for c, v in self.channels.copy().items():
            v.remove_user(numeric)
            # Clear empty non-permanent channels.
            if not (self.channels[c].users or ((self.cmodes.get('permanent'), None) in self.channels[c].modes)):
                del self.channels[c]

        sid = self.get_server(numeric)
        log.debug('Removing client %s from self.users', numeric)
        del self.users[numeric]
        log.debug('Removing client %s from self.servers[%s].users', numeric, sid)
        self.servers[sid].users.discard(numeric)

    ## State checking functions
    def nick_to_uid(self, nick):
        """Looks up the UID of a user with the given nick, if one is present."""
        nick = self.to_lower(nick)
        for k, v in self.users.copy().items():
            if self.to_lower(v.nick) == nick:
                return k

    def is_internal_client(self, numeric):
        """
        Returns whether the given client numeric (UID) is a PyLink client.
        """
        sid = self.get_server(numeric)
        if sid and self.servers[sid].internal:
            return True
        return False

    def is_internal_server(self, sid):
        """Returns whether the given SID is an internal PyLink server."""
        return (sid in self.servers and self.servers[sid].internal)

    def get_server(self, numeric):
        """Finds the SID of the server a user is on."""
        if numeric in self.servers:  # We got a server already (lazy hack)
            return numeric

        userobj = self.users.get(numeric)
        if userobj:
            return userobj.server

    def is_manipulatable_client(self, uid):
        """
        Returns whether the given user is marked as an internal, manipulatable
        client. Usually, automatically spawned services clients should have this
        set True to prevent interactions with opers (like mode changes) from
        causing desyncs.
        """
        return self.is_internal_client(uid) and self.users[uid].manipulatable

    def get_service_bot(self, uid):
        """
        Checks whether the given UID is a registered service bot. If True,
        returns the cooresponding ServiceBot object.
        """
        userobj = self.users.get(uid)
        if not userobj:
            return False

        # Look for the "service" attribute in the User object,sname = userobj.service
        # Warn if the service name we fetched isn't a registered service.
        sname = userobj.service
        if sname is not None and sname not in world.services.keys():
            log.warning("(%s) User %s / %s had a service bot record to a service that doesn't "
                        "exist (%s)!", self.name, uid, userobj.nick, sname)
        return world.services.get(sname)

structures._BLACKLISTED_COPY_TYPES.append(PyLinkNetworkCore)

class PyLinkNetworkCoreWithUtils(PyLinkNetworkCore):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Lock for updateTS to make sure only one thread can change the channel TS at one time.
        self._ts_lock = threading.Lock()

    @staticmethod
    @functools.lru_cache(maxsize=2048)
    def _to_lower_core(text, casemapping='rfc1459'):
        if casemapping == 'rfc1459':
            text = text.replace('{', '[')
            text = text.replace('}', ']')
            text = text.replace('|', '\\')
            text = text.replace('~', '^')
        # Encode the text as bytes first, and then lowercase it so that only ASCII characters are
        # changed. Unicode in channel names, etc. *is* case sensitive!
        return text.encode().lower().decode()

    def to_lower(self, text):
        """Returns a lowercase representation of text based on the IRC object's
        casemapping (rfc1459 or ascii)."""
        return self._to_lower_core(text, casemapping=self.casemapping)

    _NICK_REGEX = r'^[A-Za-z\|\\_\[\]\{\}\^\`][A-Z0-9a-z\-\|\\_\[\]\{\}\^\`]*$'
    @classmethod
    def is_nick(cls, s, nicklen=None):
        """Returns whether the string given is a valid IRC nick."""

        if nicklen and len(s) > nicklen:
            return False
        return bool(re.match(cls._NICK_REGEX, s))

    @staticmethod
    def is_channel(s):
        """Returns whether the string given is a valid IRC channel name."""
        return str(s).startswith('#')

    @staticmethod
    def _isASCII(s):
        """Returns whether the given string only contains non-whitespace ASCII characters."""
        chars = string.ascii_letters + string.digits + string.punctuation
        return all(char in chars for char in s)

    @classmethod
    def is_server_name(cls, s):
        """Returns whether the string given is a valid IRC server name."""
        return cls._isASCII(s) and '.' in s and not s.startswith('.')

    _HOSTMASK_RE = re.compile(r'^\S+!\S+@\S+$')
    @classmethod
    def is_hostmask(cls, text):
        """Returns whether the given text is a valid IRC hostmask (nick!user@host)."""
        # Band-aid patch here to prevent bad bans set by Janus forwarding people into invalid channels.
        return bool(cls._HOSTMASK_RE.match(text) and '#' not in text)

    def parse_modes(self, target, args):
        """Parses a modestring list into a list of (mode, argument) tuples.
        ['+mitl-o', '3', 'person'] => [('+m', None), ('+i', None), ('+t', None), ('+l', '3'), ('-o', 'person')]
        """
        # http://www.irc.org/tech_docs/005.html
        # A = Mode that adds or removes a nick or address to a list. Always has a parameter.
        # B = Mode that changes a setting and always has a parameter.
        # C = Mode that changes a setting and only has a parameter when set.
        # D = Mode that changes a setting and never has a parameter.

        if isinstance(args, str):
            # If the modestring was given as a string, split it into a list.
            args = args.split()

        assert args, 'No valid modes were supplied!'
        usermodes = not self.is_channel(target)
        prefix = ''
        modestring = args[0]
        args = args[1:]
        if usermodes:
            log.debug('(%s) Using self.umodes for this query: %s', self.name, self.umodes)

            if target not in self.users:
                log.debug('(%s) Possible desync! Mode target %s is not in the users index.', self.name, target)
                return []  # Return an empty mode list

            supported_modes = self.umodes
            oldmodes = self.users[target].modes
        else:
            log.debug('(%s) Using self.cmodes for this query: %s', self.name, self.cmodes)

            supported_modes = self.cmodes
            oldmodes = self._channels[target].modes
        res = []
        for mode in modestring:
            if mode in '+-':
                prefix = mode
            else:
                if not prefix:
                    prefix = '+'
                arg = None
                log.debug('Current mode: %s%s; args left: %s', prefix, mode, args)
                try:
                    if mode in self.prefixmodes and not usermodes:
                        # We're setting a prefix mode on someone (e.g. +o user1)
                        log.debug('Mode %s: This mode is a prefix mode.', mode)
                        arg = args.pop(0)
                        # Convert nicks to UIDs implicitly; most IRCds will want
                        # this already.
                        arg = self.nick_to_uid(arg) or arg
                        if arg not in self.users:  # Target doesn't exist, skip it.
                            log.debug('(%s) Skipping setting mode "%s %s"; the '
                                      'target doesn\'t seem to exist!', self.name,
                                      mode, arg)
                            continue
                    elif mode in (supported_modes['*A'] + supported_modes['*B']):
                        # Must have parameter.
                        log.debug('Mode %s: This mode must have parameter.', mode)
                        arg = args.pop(0)
                        if prefix == '-':
                            if mode in supported_modes['*B'] and arg == '*':
                                # Charybdis allows unsetting +k without actually
                                # knowing the key by faking the argument when unsetting
                                # as a single "*".
                                # We'd need to know the real argument of +k for us to
                                # be able to unset the mode.
                                oldarg = dict(oldmodes).get(mode)
                                if oldarg:
                                    # Set the arg to the old one on the channel.
                                    arg = oldarg
                                    log.debug("Mode %s: coersing argument of '*' to %r.", mode, arg)

                            log.debug('(%s) parse_modes: checking if +%s %s is in old modes list: %s', self.name, mode, arg, oldmodes)

                            if (mode, arg) not in oldmodes:
                                # Ignore attempts to unset bans that don't exist.
                                log.debug("(%s) parse_modes(): ignoring removal of non-existent list mode +%s %s", self.name, mode, arg)
                                continue

                    elif prefix == '+' and mode in supported_modes['*C']:
                        # Only has parameter when setting.
                        log.debug('Mode %s: Only has parameter when setting.', mode)
                        arg = args.pop(0)
                except IndexError:
                    log.warning('(%s/%s) Error while parsing mode %r: mode requires an '
                                'argument but none was found. (modestring: %r)',
                                self.name, target, mode, modestring)
                    continue  # Skip this mode; don't error out completely.
                res.append((prefix + mode, arg))
        return res

    def apply_modes(self, target, changedmodes):
        """Takes a list of parsed IRC modes, and applies them on the given target.

        The target can be either a channel or a user; this is handled automatically."""
        usermodes = not self.is_channel(target)

        try:
            if usermodes:
                old_modelist = self.users[target].modes
                supported_modes = self.umodes
            else:
                old_modelist = self._channels[target].modes
                supported_modes = self.cmodes
        except KeyError:
            log.warning('(%s) Possible desync? Mode target %s is unknown.', self.name, target)
            return

        modelist = set(old_modelist)
        log.debug('(%s) Applying modes %r on %s (initial modelist: %s)', self.name, changedmodes, target, modelist)
        for mode in changedmodes:
            # Chop off the +/- part that parse_modes gives; it's meaningless for a mode list.
            try:
                real_mode = (mode[0][1], mode[1])
            except IndexError:
                real_mode = mode

            if not usermodes:
                # We only handle +qaohv for now. Iterate over every supported mode:
                # if the IRCd supports this mode and it is the one being set, add/remove
                # the person from the corresponding prefix mode list (e.g. c.prefixmodes['op']
                # for ops).
                for pmode, pmodelist in self._channels[target].prefixmodes.items():
                    if pmode in self.cmodes and real_mode[0] == self.cmodes[pmode]:
                        log.debug('(%s) Initial prefixmodes list: %s', self.name, pmodelist)
                        if mode[0][0] == '+':
                            pmodelist.add(mode[1])
                        else:
                            pmodelist.discard(mode[1])

                        log.debug('(%s) Final prefixmodes list: %s', self.name, pmodelist)

                if real_mode[0] in self.prefixmodes:
                    # Don't add prefix modes to Channel.modes; they belong in the
                    # prefixmodes mapping handled above.
                    log.debug('(%s) Not adding mode %s to Channel.modes because '
                              'it\'s a prefix mode.', self.name, str(mode))
                    continue

            if mode[0][0] != '-':
                # We're adding a mode
                existing = [m for m in modelist if m[0] == real_mode[0] and m[1] != real_mode[1]]
                if existing and real_mode[1] and real_mode[0] not in self.cmodes['*A']:
                    # The mode we're setting takes a parameter, but is not a list mode (like +beI).
                    # Therefore, only one version of it can exist at a time, and we must remove
                    # any old modepairs using the same letter. Otherwise, we'll get duplicates when,
                    # for example, someone sets mode "+l 30" on a channel already set "+l 25".
                    log.debug('(%s) Old modes for mode %r exist on %s, removing them: %s',
                              self.name, real_mode, target, str(existing))
                    [modelist.discard(oldmode) for oldmode in existing]
                modelist.add(real_mode)
                log.debug('(%s) Adding mode %r on %s', self.name, real_mode, target)
            else:
                log.debug('(%s) Removing mode %r on %s', self.name, real_mode, target)
                # We're removing a mode
                if real_mode[1] is None:
                    # We're removing a mode that only takes arguments when setting.
                    # Remove all mode entries that use the same letter as the one
                    # we're unsetting.
                    for oldmode in modelist.copy():
                        if oldmode[0] == real_mode[0]:
                            modelist.discard(oldmode)
                else:
                    modelist.discard(real_mode)
        log.debug('(%s) Final modelist: %s', self.name, modelist)
        try:
            if usermodes:
                self.users[target].modes = modelist
            else:
                self._channels[target].modes = modelist
        except KeyError:
            log.warning("(%s) Invalid MODE target %s (usermodes=%s)", self.name, target, usermodes)

    @staticmethod
    def _flip(mode):
        """Flips a mode character."""
        # Make it a list first, strings don't support item assignment
        mode = list(mode)
        if mode[0] == '-':  # Query is something like "-n"
            mode[0] = '+'  # Change it to "+n"
        elif mode[0] == '+':
            mode[0] = '-'
        else:  # No prefix given, assume +
            mode.insert(0, '-')
        return ''.join(mode)

    def reverse_modes(self, target, modes, oldobj=None):
        """Reverses/Inverts the mode string or mode list given.

        Optionally, an oldobj argument can be given to look at an earlier state of
        a channel/user object, e.g. for checking the op status of a mode setter
        before their modes are processed and added to the channel state.

        This function allows both mode strings or mode lists. Example uses:
            "+mi-lk test => "-mi+lk test"
            "mi-k test => "-mi+k test"
            [('+m', None), ('+r', None), ('+l', '3'), ('-o', 'person')
             => {('-m', None), ('-r', None), ('-l', None), ('+o', 'person')})
            {('s', None), ('+o', 'whoever') => {('-s', None), ('-o', 'whoever')})
        """
        origstring = isinstance(modes, str)

        # If the query is a string, we have to parse it first.
        if origstring:
            modes = self.parse_modes(target, modes.split(" "))
        # Get the current mode list first.
        if self.is_channel(target):
            c = oldobj or self._channels[target]
            oldmodes = c.modes.copy()
            possible_modes = self.cmodes.copy()
            # For channels, this also includes the list of prefix modes.
            possible_modes['*A'] += ''.join(self.prefixmodes)
            for name, userlist in c.prefixmodes.items():
                try:
                    oldmodes.update([(self.cmodes[name], u) for u in userlist])
                except KeyError:
                    continue
        else:
            oldmodes = self.users[target].modes
            possible_modes = self.umodes
        newmodes = []
        log.debug('(%s) reverse_modes: old/current mode list for %s is: %s', self.name,
                   target, oldmodes)
        for char, arg in modes:
            # Mode types:
            # A = Mode that adds or removes a nick or address to a list. Always has a parameter.
            # B = Mode that changes a setting and always has a parameter.
            # C = Mode that changes a setting and only has a parameter when set.
            # D = Mode that changes a setting and never has a parameter.
            mchar = char[-1]
            if mchar in possible_modes['*B'] + possible_modes['*C']:
                # We need to find the current mode list, so we can reset arguments
                # for modes that have arguments. For example, setting +l 30 on a channel
                # that had +l 50 set should give "+l 30", not "-l".
                oldarg = [m for m in oldmodes if m[0] == mchar]
                if oldarg:  # Old mode argument for this mode existed, use that.
                    oldarg = oldarg[0]
                    mpair = ('+%s' % oldarg[0], oldarg[1])
                else:  # Not found, flip the mode then.
                    # Mode takes no arguments when unsetting.
                    if mchar in possible_modes['*C'] and char[0] != '-':
                        arg = None
                    mpair = (self._flip(char), arg)
            else:
                mpair = (self._flip(char), arg)
            if char[0] != '-' and (mchar, arg) in oldmodes:
                # Mode is already set.
                log.debug("(%s) reverse_modes: skipping reversing '%s %s' with %s since we're "
                          "setting a mode that's already set.", self.name, char, arg, mpair)
                continue
            elif char[0] == '-' and (mchar, arg) not in oldmodes and mchar in possible_modes['*A']:
                # We're unsetting a prefixmode that was never set - don't set it in response!
                # Charybdis lacks verification for this server-side.
                log.debug("(%s) reverse_modes: skipping reversing '%s %s' with %s since it "
                          "wasn't previously set.", self.name, char, arg, mpair)
                continue
            newmodes.append(mpair)

        log.debug('(%s) reverse_modes: new modes: %s', self.name, newmodes)
        if origstring:
            # If the original query is a string, send it back as a string.
            return self.join_modes(newmodes)
        else:
            return set(newmodes)

    @staticmethod
    def join_modes(modes, sort=False):
        """Takes a list of (mode, arg) tuples in parse_modes() format, and
        joins them into a string.

        See testJoinModes in tests/test_utils.py for some examples."""
        prefix = '+'  # Assume we're adding modes unless told otherwise
        modelist = ''
        args = []

        # Sort modes alphabetically like a conventional IRCd.
        if sort:
            modes = sorted(modes)

        for modepair in modes:
            mode, arg = modepair
            assert len(mode) in (1, 2), "Incorrect length of a mode (received %r)" % mode
            try:
                # If the mode has a prefix, use that.
                curr_prefix, mode = mode
            except ValueError:
                # If not, the current prefix stays the same; move on to the next
                # modepair.
                pass
            else:
                # If the prefix of this mode isn't the same as the last one, add
                # the prefix to the modestring. This prevents '+nt-lk' from turning
                # into '+n+t-l-k' or '+ntlk'.
                if prefix != curr_prefix:
                    modelist += curr_prefix
                    prefix = curr_prefix
            modelist += mode
            if arg is not None:
                args.append(arg)
        if not modelist.startswith(('+', '-')):
            # Our starting mode didn't have a prefix with it. Assume '+'.
            modelist = '+' + modelist
        if args:
            # Add the args if there are any.
            modelist += ' %s' % ' '.join(args)
        return modelist

    @classmethod
    def wrap_modes(cls, modes, limit, max_modes_per_msg=0):
        """
        Takes a list of modes and wraps it across multiple lines.
        """
        strings = []

        # This process is slightly trickier than just wrapping arguments, because modes create
        # positional arguments that can't be separated from its character.
        queued_modes = []
        total_length = 0

        last_prefix = '+'
        orig_modes = modes.copy()
        modes = list(modes)
        while modes:
            # PyLink mode lists come in the form [('+t', None), ('-b', '*!*@someone'), ('+l', 3)]
            # The +/- part is optional depending on context, and should either:
            # 1) The prefix of the last mode.
            # 2) + (adding modes), if no prefix was ever given
            next_mode = modes.pop(0)

            modechar, arg = next_mode
            prefix = modechar[0]
            if prefix not in '+-':
                prefix = last_prefix
                # Explicitly add the prefix to the mode character to prevent
                # ambiguity when passing it to join_modes().
                modechar = prefix + modechar
                # XXX: because tuples are immutable, we have to replace the entire modepair..
                next_mode = (modechar, arg)

            # Figure out the length that the next mode will add to the buffer. If we're changing
            # from + to - (setting to removing modes) or vice versa, we'll need two characters
            # ("+" or "-") plus the mode char itself.
            next_length = 1
            if prefix != last_prefix:
                next_length += 1

            # Replace the last_prefix with the current one for the next iteration.
            last_prefix = prefix

            if arg:
                # This mode has an argument, so add the length of that and a space.
                next_length += 1
                next_length += len(arg)

            assert next_length <= limit, \
                "wrap_modes: Mode %s is too long for the given length %s" % (next_mode, limit)

            # Check both message length and max. modes per msg if enabled.
            if (next_length + total_length) <= limit and ((not max_modes_per_msg) or len(queued_modes) < max_modes_per_msg):
                # We can fit this mode in the next message; add it.
                total_length += next_length
                log.debug('wrap_modes: Adding mode %s to queued modes', str(next_mode))
                queued_modes.append(next_mode)
                log.debug('wrap_modes: queued modes: %s', queued_modes)
            else:
                # Otherwise, create a new message by joining the previous queue.
                # Then, add our current mode.
                strings.append(cls.join_modes(queued_modes))
                queued_modes.clear()

                log.debug('wrap_modes: cleared queue (length %s) and now adding %s', limit, str(next_mode))
                queued_modes.append(next_mode)
                total_length = next_length
        else:
            # Everything fit in one line, so just use that.
            strings.append(cls.join_modes(queued_modes))

        log.debug('wrap_modes: returning %s for %s', strings, orig_modes)
        return strings

    def get_hostmask(self, user, realhost=False, ip=False):
        """
        Returns the hostmask of the given user, if present. If the realhost option
        is given, return the real host of the user instead of the displayed host.
        If the ip option is given, return the IP address of the user (this overrides
        realhost)."""
        userobj = self.users.get(user)

        try:
            nick = userobj.nick
        except AttributeError:
            nick = '<unknown-nick>'

        try:
            ident = userobj.ident
        except AttributeError:
            ident = '<unknown-ident>'

        try:
            if ip:
                host = userobj.ip
            elif realhost:
                host = userobj.realhost
            else:
                host = userobj.host
        except AttributeError:
            host = '<unknown-host>'

        return '%s!%s@%s' % (nick, ident, host)

    def get_friendly_name(self, entityid):
        """
        Returns the friendly name of a SID or UID (server name for SIDs, nick for UID).
        """
        if entityid in self.servers:
            return self.servers[entityid].name
        elif entityid in self.users:
            return self.users[entityid].nick
        else:
            raise KeyError("Unknown UID/SID %s" % entityid)

    def is_oper(self, uid, allowAuthed=True, allowOper=True):
        """
        Returns whether the given user has operator status on PyLink. This can be achieved
        by either identifying to PyLink as admin (if allowAuthed is True),
        or having user mode +o set (if allowOper is True). At least one of
        allowAuthed or allowOper must be True for this to give any meaningful
        results.
        """
        if uid in self.users:
            if allowOper and ("o", None) in self.users[uid].modes:
                return True
            elif allowAuthed and self.users[uid].account:
                return True
        return False

    def check_authenticated(self, uid, allowAuthed=True, allowOper=True):
        """
        Checks whether the given user has operator status on PyLink, raising
        NotAuthorizedError and logging the access denial if not.
        """
        log.warning("(%s) check_authenticated() is deprecated as of PyLink 1.2 and may be "
                    "removed in a future relase. Consider migrating to the PyLink Permissions API.",
                    self.name)
        lastfunc = inspect.stack()[1][3]
        if not self.is_oper(uid, allowAuthed=allowAuthed, allowOper=allowOper):
            log.warning('(%s) Access denied for %s calling %r', self.name,
                        self.get_hostmask(uid), lastfunc)
            raise utils.NotAuthorizedError("You are not authenticated!")
        return True

    def match_host(self, glob, target, ip=True, realhost=True):
        """
        Checks whether the given host, or given UID's hostmask matches the given nick!user@host
        glob.

        If the target given is a UID, and the 'ip' or 'realhost' options are True, this will also
        match against the target's IP address and real host, respectively.

        This function respects IRC casemappings (rfc1459 and ascii). If the given target is a UID,
        and the 'ip' option is enabled, the host portion of the glob is also matched as a CIDR
        range.
        """
        # Get the corresponding casemapping value used by ircmatch.
        if self.casemapping == 'rfc1459':
            casemapping = 0
        else:
            casemapping = 1

        # Try to convert target into a UID. If this fails, it's probably a hostname.
        target = self.nick_to_uid(target) or target

        # Allow queries like !$exttarget to invert the given match.
        invert = glob.startswith('!')
        if invert:
            glob = glob.lstrip('!')

        def match_host_core():
            """
            Core processor for match_host(), minus the inversion check.
            """
            # Work with variables in the match_host() scope, from
            # http://stackoverflow.com/a/8178808
            nonlocal glob

            # Prepare a list of hosts to check against.
            if target in self.users:

                if not self.is_hostmask(glob):
                    for specialchar in '$:()':
                        # XXX: we should probably add proper rules on what's a valid account name
                        if specialchar in glob:
                            break
                    else:
                        # Implicitly convert matches for *sane* account names to "$pylinkacc:accountname".
                        log.debug('(%s) Using target $pylinkacc:%s instead of raw string %r', self.name, glob, glob)
                        glob = '$pylinkacc:' + glob

                if glob.startswith('$'):
                    # Exttargets start with $. Skip regular ban matching and find the matching ban handler.
                    glob = glob.lstrip('$')
                    exttargetname = glob.split(':', 1)[0]
                    handler = world.exttarget_handlers.get(exttargetname)

                    if handler:
                        # Handler exists. Return what it finds.
                        result = handler(self, glob, target)
                        log.debug('(%s) Got %s from exttarget %s in match_host() glob $%s for target %s',
                                  self.name, result, exttargetname, glob, target)
                        return result
                    else:
                        log.debug('(%s) Unknown exttarget %s in match_host() glob $%s', self.name,
                                  exttargetname, glob)
                        return False

                hosts = {self.get_hostmask(target)}

                if ip:
                    hosts.add(self.get_hostmask(target, ip=True))

                    # HACK: support CIDR hosts in the hosts portion
                    try:
                        header, cidrtarget = glob.split('@', 1)
                        # Try to parse the host portion as a CIDR range
                        network = ipaddress.ip_network(cidrtarget)

                        real_ip = self.users[target].ip
                        if ipaddress.ip_address(real_ip) in network:
                            # If the CIDR matches, hack around the host matcher by pretending that
                            # the lookup target was the IP and not the CIDR range!
                            glob = '@'.join((header, real_ip))
                            log.debug('(%s) Found matching CIDR %s for %s, replacing target glob with IP %s', self.name,
                                      cidrtarget, target, real_ip)
                    except ValueError:
                        pass

                if realhost:
                    hosts.add(self.get_hostmask(target, realhost=True))

            else:  # We were given a host, use that.
                hosts = [target]

            # Iterate over the hosts to match using ircmatch.
            for host in hosts:
                if ircmatch.match(casemapping, glob, host):
                    return True

            return False

        result = match_host_core()
        if invert:
            result = not result
        return result

    def match_all(self, banmask, channel=None):
        """
        Returns all users matching the target hostmask/exttarget. Users can also be filtered by channel.
        """
        if channel:
            banmask = "$and:(%s+$channel:%s)" % (banmask, channel)

        for uid, userobj in self.users.copy().items():
            if self.match_host(banmask, uid) and uid in self.users:
                yield uid

    def match_all_re(self, re_mask, channel=None):
        """
        Returns all users whose "nick!user@host [gecos]" mask matches the given regular expression. Users can also be filtered by channel.
        """
        regexp = re.compile(re_mask)
        for uid, userobj in self.users.copy().items():
            target = '%s [%s]' % (self.get_hostmask(uid), userobj.realname)
            if regexp.fullmatch(target) and ((not channel) or channel in userobj.channels):
                yield uid

    def make_channel_ban(self, uid, ban_type='ban'):
        """Creates a hostmask-based ban for the given user.

        Ban exceptions, invite exceptions quiets, and extbans are also supported by setting ban_type
        to the appropriate PyLink named mode (e.g. "ban", "banexception", "invex", "quiet", "ban_nonick")."""
        assert uid in self.users, "Unknown user %s" % uid

        # FIXME: verify that this is a valid mask.
        # XXX: support slicing hosts so things like *!ident@*.isp.net are possible. This is actually
        #      more annoying to do than it appears because of vHosts using /, IPv6 addresses
        #      (cloaked and uncloaked), etc.
        ban_style = self.serverdata.get('ban_style') or conf.conf['pylink'].get('ban_style') or \
            '*!*@$host'

        template = string.Template(ban_style)
        banhost = template.safe_substitute(ban_style, **self.users[uid].__dict__)
        assert self.is_hostmask(banhost), "Ban mask %r is not a valid hostmask!" % banhost

        if ban_type in self.cmodes:
            return ('+%s' % self.cmodes[ban_type], banhost)
        elif ban_type in self.extbans_acting:  # Handle extbans, which are generally "+b prefix:banmask"
            return ('+%s' % self.cmodes['ban'], self.extbans_acting[ban_type]+banhost)
        else:
            raise ValueError("ban_type %r is not available on IRCd %r" % (ban_type, self.protoname))

    def updateTS(self, sender, channel, their_ts, modes=None):
        """
        Merges modes of a channel given the remote TS and a list of modes.
        """

        # Okay, so the situation is that we have 6 possible TS/sender combinations:

        #                       | our TS lower | TS equal | their TS lower
        # mode origin is us     |   OVERWRITE  |   MERGE  |    IGNORE
        # mode origin is uplink |    IGNORE    |   MERGE  |   OVERWRITE

        if modes is None:
            modes = []

        def _clear():
            log.debug("(%s) Clearing local modes from channel %s due to TS change", self.name,
                      channel)
            self._channels[channel].modes.clear()
            for p in self._channels[channel].prefixmodes.values():
                for user in p.copy():
                    if not self.is_internal_client(user):
                        p.discard(user)

        def _apply():
            if modes:
                log.debug("(%s) Applying modes on channel %s (TS ok)", self.name,
                          channel)
                self.apply_modes(channel, modes)

        # Use a lock so only one thread can change a channel's TS at once: this prevents race
        # conditions that would otherwise desync channel modes.
        with self._ts_lock:
            our_ts = self._channels[channel].ts
            assert isinstance(our_ts, int), "Wrong type for our_ts (expected int, got %s)" % type(our_ts)
            assert isinstance(their_ts, int), "Wrong type for their_ts (expected int, got %s)" % type(their_ts)

            # Check if we're the mode sender based on the UID / SID given.
            our_mode = self.is_internal_client(sender) or self.is_internal_server(sender)

            log.debug("(%s/%s) our_ts: %s; their_ts: %s; is the mode origin us? %s", self.name,
                      channel, our_ts, their_ts, our_mode)

            if their_ts == our_ts:
                log.debug("(%s/%s) remote TS of %s is equal to our %s; mode query %s",
                          self.name, channel, their_ts, our_ts, modes)
                # Their TS is equal to ours. Merge modes.
                _apply()

            elif (their_ts < our_ts):
                if their_ts < 750000:
                    log.warning('(%s) Possible desync? Not setting bogus TS %s on channel %s', self.name, their_ts, channel)
                else:
                    log.debug('(%s) Resetting channel TS of %s from %s to %s (remote has lower TS)',
                              self.name, channel, our_ts, their_ts)
                    self._channels[channel].ts = their_ts

                # Remote TS was lower and we're receiving modes. Clear the modelist and apply theirs.

                _clear()
                _apply()

    def _check_nick_collision(self, nick):
        """
        Nick collision checker.
        """
        uid = self.nick_to_uid(nick)
        # If there is a nick collision, we simply alert plugins. Relay will purposely try to
        # lose fights and tag nicks instead, while other plugins can choose how to handle this.
        if uid:
            log.info('(%s) Nick collision on %s/%s, forwarding this to plugins', self.name,
                     uid, nick)
            self.call_hooks([self.sid, 'SAVE', {'target': uid}])

    def _expandPUID(self, uid):
        """
        Returns the nick or server name for the given UID/SID. This method helps support protocol
        modules that use PUIDs internally, as they must convert them to talk with the uplink.
        """
        # TODO: stop hardcoding @ as separator
        if '@' in uid:
            if uid in self.users:
                # UID exists and has a @ in it, meaning it's a PUID (orignick@counter style).
                # Return this user's nick accordingly.
                nick = self.users[uid].nick
                log.debug('(%s) Mangling target PUID %s to nick %s', self.name, uid, nick)
                return nick
            elif uid in self.servers:
                # Ditto for servers
                sname = self.servers[uid].name
                log.debug('(%s) Mangling target PSID %s to server name %s', self.name, uid, sname)
                return sname
        return uid  # Regular UID, no change

utils._proto_utils_class = PyLinkNetworkCoreWithUtils  # Used by compatibility wrappers

class IRCNetwork(PyLinkNetworkCoreWithUtils):
    S2S_BUFSIZE = 510

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._connection_thread = None
        self._queue = None
        self._ping_timer = None
        self._socket = None

    def _init_vars(self, *args, **kwargs):
        super()._init_vars(*args, **kwargs)

        # Set IRC specific variables for ping checking and queuing
        self.lastping = time.time()
        self.pingfreq = self.serverdata.get('pingfreq') or 90
        self.pingtimeout = self.pingfreq * 3

        self.maxsendq = self.serverdata.get('maxsendq', 4096)
        self._queue = queue.Queue(self.maxsendq)

    def _schedule_ping(self):
        """Schedules periodic pings in a loop."""
        self._ping_uplink()

        self._ping_timer = threading.Timer(self.pingfreq, self._schedule_ping)
        self._ping_timer.daemon = True
        self._ping_timer.name = 'Ping timer loop for %s' % self.name
        self._ping_timer.start()

        log.debug('(%s) Ping scheduled at %s', self.name, time.time())

    def _log_connection_error(self, *args, **kwargs):
        # Log connection errors to ERROR unless were shutting down (in which case,
        # the given text goes to DEBUG).
        if self._aborted.is_set() or control.tried_shutdown:
            log.debug(*args, **kwargs)
        else:
            log.error(*args, **kwargs)

    def _connect(self):
        """
        Runs the connect loop for the IRC object. This is usually called by
        __init__ in a separate thread to allow multiple concurrent connections.
        """
        while True:
            self._pre_connect()

            ip = self.serverdata["ip"]
            port = self.serverdata["port"]
            checks_ok = True
            try:
                # Set the socket type (IPv6 or IPv4).
                stype = socket.AF_INET6 if self.serverdata.get("ipv6") else socket.AF_INET

                # Creat the socket.
                self._socket = socket.socket(stype)
                self._socket.setblocking(0)

                # Set the socket bind if applicable.
                if 'bindhost' in self.serverdata:
                    self._socket.bind((self.serverdata['bindhost'], 0))

                # Set the connection timeouts. Initial connection timeout is a
                # lot smaller than the timeout after we've connected; this is
                # intentional.
                self._socket.settimeout(self.pingfreq)

                # Resolve hostnames if it's not an IP address already.
                old_ip = ip
                ip = socket.getaddrinfo(ip, port, stype)[0][-1][0]
                log.debug('(%s) Resolving address %s to %s', self.name, old_ip, ip)

                # Enable SSL if set to do so.
                self.ssl = self.serverdata.get('ssl')
                if self.ssl:
                    log.info('(%s) Attempting SSL for this connection...', self.name)
                    certfile = self.serverdata.get('ssl_certfile')
                    keyfile = self.serverdata.get('ssl_keyfile')

                    context = ssl.SSLContext(ssl.PROTOCOL_SSLv23)
                    # Disable SSLv2 and SSLv3 - these are insecure
                    context.options |= ssl.OP_NO_SSLv2
                    context.options |= ssl.OP_NO_SSLv3

                    # Cert and key files are optional, load them if specified.
                    if certfile and keyfile:
                        try:
                            context.load_cert_chain(certfile, keyfile)
                        except OSError:
                             log.exception('(%s) Caught OSError trying to '
                                           'initialize the SSL connection; '
                                           'are "ssl_certfile" and '
                                           '"ssl_keyfile" set correctly?',
                                           self.name)
                             checks_ok = False

                    self._socket = context.wrap_socket(self._socket)

                log.info("Connecting to network %r on %s:%s", self.name, ip, port)
                self._socket.connect((ip, port))
                self._socket.settimeout(self.pingtimeout)

                # If SSL was enabled, optionally verify the certificate
                # fingerprint for some added security. I don't bother to check
                # the entire certificate for validity, since most IRC networks
                # self-sign their certificates anyways.
                if self.ssl and checks_ok:
                    peercert = self._socket.getpeercert(binary_form=True)

                    # Hash type is configurable using the ssl_fingerprint_type
                    # value, and defaults to sha256.
                    hashtype = self.serverdata.get('ssl_fingerprint_type', 'sha256').lower()

                    try:
                        hashfunc = getattr(hashlib, hashtype)
                    except AttributeError:
                        log.error('(%s) Unsupported SSL certificate fingerprint type %r given, disconnecting...',
                                  self.name, hashtype)
                        checks_ok = False
                    else:
                        fp = hashfunc(peercert).hexdigest()
                        expected_fp = self.serverdata.get('ssl_fingerprint')

                        if expected_fp and checks_ok:
                            if fp != expected_fp:
                                # SSL Fingerprint doesn't match; break.
                                log.error('(%s) Uplink\'s SSL certificate '
                                          'fingerprint (%s) does not match the '
                                          'one configured: expected %r, got %r; '
                                          'disconnecting...', self.name, hashtype,
                                          expected_fp, fp)
                                checks_ok = False
                            else:
                                log.info('(%s) Uplink SSL certificate fingerprint '
                                         '(%s) verified: %r', self.name, hashtype,
                                         fp)
                        else:
                            log.info('(%s) Uplink\'s SSL certificate fingerprint (%s) '
                                     'is %r. You can enhance the security of your '
                                     'link by specifying this in a "ssl_fingerprint"'
                                     ' option in your server block.', self.name,
                                     hashtype, fp)

                if checks_ok:

                    self._queue_thread = threading.Thread(name="Queue thread for %s" % self.name,
                                                         target=self._process_queue, daemon=True)
                    self._queue_thread.start()

                    self.sid = self.serverdata.get("sid")
                    # All our checks passed, get the protocol module to connect and run the listen
                    # loop. This also updates any SID values should the protocol module do so.
                    self.post_connect()

                    log.info('(%s) Enumerating our own SID %s', self.name, self.sid)
                    host = self.hostname()

                    self.servers[self.sid] = Server(self, None, host, internal=True,
                                                    desc=self.serverdata.get('serverdesc')
                                                    or conf.conf['pylink']['serverdesc'])

                    log.info('(%s) Starting ping schedulers....', self.name)
                    self._schedule_ping()
                    log.info('(%s) Server ready; listening for data.', self.name)
                    self.autoconnect_active_multiplier = 1  # Reset any extra autoconnect delays
                    self._run_irc()
                else:  # Configuration error :(
                    log.error('(%s) A configuration error was encountered '
                              'trying to set up this connection. Please check'
                              ' your configuration file and try again.',
                              self.name)
            # _run_irc() or the protocol module it called raised an exception, meaning we've disconnected!
            # Note: socket.error, ConnectionError, IOError, etc. are included in OSError since Python 3.3,
            # so we don't need to explicitly catch them here.
            # We also catch SystemExit here as a way to abort out connection threads properly, and stop the
            # IRC connection from freezing instead.
            except (OSError, RuntimeError, SystemExit) as e:
                self._log_connection_error('(%s) Disconnected from IRC:', self.name, exc_info=True)

            self.disconnect()
            if not self._run_autoconnect():
                return

    def connect(self):
        log.debug('(%s) calling _connect() (world.testing=%s)', self.name, world.testing)
        if world.testing:
            # HACK: Don't thread if we're running tests.
            self._connect()
        else:
            if self._connection_thread and self._connection_thread.is_alive():
                raise RuntimeError("Refusing to start multiple connection threads for network %r!" % self.name)

            self._connection_thread = threading.Thread(target=self._connect,
                                                      name="Listener for %s" %
                                                      self.name)
            self._connection_thread.start()

    def disconnect(self):
        """Handle disconnects from the remote server."""
        self._pre_disconnect()

        if self._socket is not None:
            try:
                log.debug('(%s) disconnect: Shutting down socket.', self.name)
                self._socket.shutdown(socket.SHUT_RDWR)
            except Exception as e:  # Socket timed out during creation; ignore
                log.debug('(%s) error on socket shutdown: %s: %s', self.name, type(e).__name__, e)

            self._socket.close()

        # Stop the queue thread.
        if self._queue:
            # XXX: queue.Queue.queue isn't actually documented, so this is probably not reliable in the long run.
            self._queue.queue.appendleft(None)

        # Stop the ping timer.
        if self._ping_timer:
            log.debug('(%s) Canceling pingTimer at %s due to disconnect() call', self.name, time.time())
            self._ping_timer.cancel()
        self._post_disconnect()

    def handle_events(self, line):
        raise NotImplementedError

    def parse_irc_command(self, line):
        """Sends a command to the protocol module."""
        log.debug("(%s) <- %s", self.name, line)
        try:
            hook_args = self.handle_events(line)
        except Exception:
            log.exception('(%s) Caught error in handle_events, disconnecting!', self.name)
            log.error('(%s) The offending line was: <- %s', self.name, line)
            self.disconnect()
            return
        # Only call our hooks if there's data to process. Handlers that support
        # hooks will return a dict of parsed arguments, which can be passed on
        # to plugins and the like. For example, the JOIN handler will return
        # something like: {'channel': '#whatever', 'users': ['UID1', 'UID2',
        # 'UID3']}, etc.
        if hook_args is not None:
            self.call_hooks(hook_args)

        return hook_args

    def _run_irc(self):
        """Main IRC loop which listens for messages."""
        buf = b""
        data = b""
        while not self._aborted.is_set():

            try:
                data = self._socket.recv(2048)
            except OSError:
                # Suppress socket read warnings from lingering recv() calls if
                # we've been told to shutdown.
                if self._aborted.is_set():
                    return
                raise

            buf += data
            if not data:
                self._log_connection_error('(%s) Connection lost, disconnecting.', self.name)
                return
            elif (time.time() - self.lastping) > self.pingtimeout:
                self._log_connection_error('(%s) Connection timed out.', self.name)
                return

            while b'\n' in buf:
                line, buf = buf.split(b'\n', 1)
                line = line.strip(b'\r')
                line = line.decode(self.encoding, "replace")
                self.parse_irc_command(line)

    def _send(self, data):
        """Sends raw text to the uplink server."""
        # Safeguard against newlines in input!! Otherwise, each line gets
        # treated as a separate command, which is particularly nasty.
        data = data.replace('\n', ' ')
        encoded_data = data.encode(self.encoding, 'replace')
        if self.S2S_BUFSIZE > 0:  # Apply message cutoff as needed
            encoded_data = encoded_data[:self.S2S_BUFSIZE]
        encoded_data += b"\r\n"

        log.debug("(%s) -> %s", self.name, data)

        try:
            self._socket.send(encoded_data)
        except (OSError, AttributeError):
            log.exception("(%s) Failed to send message %r; did the network disconnect?", self.name, data)

    def send(self, data, queue=True):
        """send() wrapper with optional queueing support."""
        if self._aborted.is_set():
            log.debug('(%s) refusing to queue data %r as self._aborted is set', self.name, data)
            return
        if queue:
            # XXX: we don't really know how to handle blocking queues yet, so
            # it's better to not expose that yet.
            self._queue.put_nowait(data)
        else:
            self._send(data)

    def _process_queue(self):
        """Loop to process outgoing queue data."""
        while True:
            throttle_time = self.serverdata.get('throttle_time', 0.005)
            if not self._aborted.wait(throttle_time):
                data = self._queue.get()
                if data is None:
                    log.debug('(%s) Stopping queue thread due to getting None as item', self.name)
                    break
                elif self not in world.networkobjects.values():
                    log.debug('(%s) Stopping stale queue thread; no longer matches world.networkobjects', self.name)
                    break
                elif data:
                    self._send(data)
            else:
                break

Irc = IRCNetwork

class User():
    """PyLink IRC user class."""
    def __init__(self, irc, nick, ts, uid, server, ident='null', host='null',
                 realname='PyLink dummy client', realhost='null',
                 ip='0.0.0.0', manipulatable=False, opertype='IRC Operator'):
        self.nick = nick
        self.ts = ts
        self.uid = uid
        self.ident = ident
        self.host = host
        self.realhost = realhost
        self.ip = ip
        self.realname = realname
        self.modes = set()  # Tracks user modes
        self.server = server
        self._irc = irc

        # Tracks PyLink identification status
        self.account = ''

        # Tracks oper type (for display only)
        self.opertype = opertype

        # Tracks external services identification status
        self.services_account = ''

        # Tracks channels the user is in
        self.channels = structures.IRCCaseInsensitiveSet(self._irc)

        # Tracks away message status
        self.away = ''

        # This sets whether the client should be marked as manipulatable.
        # Plugins like bots.py's commands should take caution against
        # manipulating these "protected" clients, to prevent desyncs and such.
        # For "serious" service clients, this should always be False.
        self.manipulatable = manipulatable

        # Cloaked host for IRCds that use it
        self.cloaked_host = None

        # Stores service bot name if applicable
        self.service = None

    def __repr__(self):
        return 'User(%s/%s)' % (self.uid, self.nick)
IrcUser = User

class Server():
    """PyLink IRC server class.

    irc: the protocol/network object this Server instance is attached to.
    uplink: The SID of this Server instance's uplink. This is set to None
            for **both** the main PyLink server and our uplink.
    name: The name of the server.
    internal: Boolean, whether the server is an internal PyLink server.
    desc: Sets the server description if relevant.
    """

    def __init__(self, irc, uplink, name, internal=False, desc="(None given)"):
        self.uplink = uplink
        self.users = set()
        self.internal = internal
        self.name = name.lower()
        self.desc = desc
        self._irc = irc

        # Has the server finished bursting yet?
        self.has_eob = False

    def __repr__(self):
        return 'Server(%s)' % self.name

IrcServer = Server

class Channel(structures.DeprecatedAttributesObject, structures.CamelCaseToSnakeCase, structures.CopyWrapper):
    """PyLink IRC channel class."""

    def __init__(self, irc, name=None):
        # Initialize variables, such as the topic, user list, TS, who's opped, etc.
        self.users = set()
        self.modes = set()
        self.topic = ''
        self.ts = int(time.time())
        self.prefixmodes = {'op': set(), 'halfop': set(), 'voice': set(),
                            'owner': set(), 'admin': set()}
        self._irc = irc

        # Determines whether a topic has been set here or not. Protocol modules
        # should set this.
        self.topicset = False

        # Saves the channel name (may be useful to plugins, etc.)
        self.name = name

        self.deprecated_attributes = {'removeuser': 'Deprecated in 2.0; use remove_user() instead!'}

    def __repr__(self):
        return 'Channel(%s)' % self.name

    def remove_user(self, target):
        """Removes a user from a channel."""
        for s in self.prefixmodes.values():
            s.discard(target)
        self.users.discard(target)
    removeuser = remove_user

    def is_voice(self, uid):
        """Returns whether the given user is voice in the channel."""
        return uid in self.prefixmodes['voice']

    def is_halfop(self, uid):
        """Returns whether the given user is halfop in the channel."""
        return uid in self.prefixmodes['halfop']

    def is_op(self, uid):
        """Returns whether the given user is op in the channel."""
        return uid in self.prefixmodes['op']

    def is_admin(self, uid):
        """Returns whether the given user is admin (&) in the channel."""
        return uid in self.prefixmodes['admin']

    def is_owner(self, uid):
        """Returns whether the given user is owner (~) in the channel."""
        return uid in self.prefixmodes['owner']

    def is_voice_plus(self, uid):
        """Returns whether the given user is voice or above in the channel."""
        # If the user has any prefix mode, it has to be voice or greater.
        return bool(self.getPrefixModes(uid))

    def is_halfop_plus(self, uid):
        """Returns whether the given user is halfop or above in the channel."""
        for mode in ('halfop', 'op', 'admin', 'owner'):
            if uid in self.prefixmodes[mode]:
                return True
        return False

    def is_op_plus(self, uid):
        """Returns whether the given user is op or above in the channel."""
        for mode in ('op', 'admin', 'owner'):
            if uid in self.prefixmodes[mode]:
                return True
        return False

    @staticmethod
    def sort_prefixes(key):
        """
        Implements a sorted()-compatible sorter for prefix modes, giving each one a
        numeric value.
        """
        values = {'owner': 100, 'admin': 10, 'op': 5, 'halfop': 4, 'voice': 3}

        # Default to highest value (1000) for unknown modes, should we choose to
        # support them.
        return values.get(key, 1000)

    def get_prefix_modes(self, uid, prefixmodes=None):
        """Returns a list of all named prefix modes the given user has in the channel.

        Optionally, a prefixmodes argument can be given to look at an earlier state of
        the channel's prefix modes mapping, e.g. for checking the op status of a mode
        setter before their modes are processed and added to the channel state.
        """

        if uid not in self.users:
            raise KeyError("User %s does not exist or is not in the channel" % uid)

        result = []
        prefixmodes = prefixmodes or self.prefixmodes

        for mode, modelist in prefixmodes.items():
            if uid in modelist:
                result.append(mode)

        return sorted(result, key=self.sort_prefixes)
IrcChannel = Channel

class PUIDGenerator():
    """
    Pseudo UID Generator module, using a prefix and a simple counter.
    """

    def __init__(self, prefix, start=0):
        self.prefix = prefix
        self.counter = start

    def next_uid(self, prefix=''):
        """
        Generates the next PUID.
        """
        uid = '%s@%s' % (prefix or self.prefix, self.counter)
        self.counter += 1
        return uid
    next_sid = next_uid
