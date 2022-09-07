"""
classes.py - Base classes for PyLink IRC Services.

This module contains the base classes used by PyLink, including threaded IRC
connections and objects used to represent IRC servers, users, and channels.

Here be dragons.
"""

import collections
import collections.abc
import functools
import hashlib
import ipaddress
import queue
import re
import socket
import ssl
import string
import textwrap
import threading
import time

from . import __version__, conf, selectdriver, structures, utils, world
from .log import log, PyLinkChannelLogger
from .utils import ProtocolError  # Compatibility with PyLink 1.x

__all__ = ['ChannelState', 'User', 'UserMapping', 'PyLinkNetworkCore',
           'PyLinkNetworkCoreWithUtils', 'IRCNetwork', 'Server', 'Channel',
           'PUIDGenerator', 'ProtocolError']

QUEUE_FULL = queue.Full


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

class TSObject():
    """Base class for classes containing a type-normalized timestamp."""
    def __init__(self, *args, **kwargs):
        self._ts = int(time.time())

    @property
    def ts(self):
        return self._ts

    @ts.setter
    def ts(self, value):
        if (not isinstance(value, int)) and (not isinstance(value, float)):
            log.warning('TSObject: Got bad type for TS, converting from %s to int',
                        type(value), stack_info=True)
            value = int(value)
        self._ts = value

class User(TSObject):
    """PyLink IRC user class."""
    def __init__(self, irc, nick, ts, uid, server, ident='null', host='null',
                 realname='PyLink dummy client', realhost='null',
                 ip='0.0.0.0', manipulatable=False, opertype='IRC Operator'):
        super().__init__()
        self._nick = nick
        self.lower_nick = irc.to_lower(nick)

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

        # Whether the user is using SSL/TLS (None = unknown)
        self.ssl = None

    @property
    def nick(self):
        return self._nick

    @nick.setter
    def nick(self, newnick):
        oldnick = self.lower_nick
        self._nick = newnick
        self.lower_nick = self._irc.to_lower(newnick)

        # Update the irc.users bynick index:
        if oldnick in self._irc.users.bynick:
            # Remove existing value -> key mappings.
            self._irc.users.bynick[oldnick].remove(self.uid)

            # Remove now-empty keys as well.
            if not self._irc.users.bynick[oldnick]:
                del self._irc.users.bynick[oldnick]

        # Update the new nick.
        self._irc.users.bynick.setdefault(self.lower_nick, []).append(self.uid)

    def get_fields(self):
        """
        Returns all template/substitution-friendly fields for the User object in a read-only dictionary.
        """
        fields = self.__dict__.copy()

        # These don't really make sense in text substitutions
        for field in ('manipulatable', '_irc', 'channels', 'modes'):
            del fields[field]

        # Swap SID and server name for convenience
        fields['sid'] = self.server
        try:
            fields['server'] = self._irc.get_friendly_name(self.server)
        except KeyError:
            pass  # Keep it as is (i.e. as the SID) if grabbing the server name fails

        # Network name
        fields['netname'] = self._irc.name

        # Add the nick attribute; this isn't in __dict__ because it's a property
        fields['nick'] = self._nick

        return fields

    def __repr__(self):
        return 'User(%s/%s)' % (self.uid, self.nick)
IrcUser = User

# Bidirectional dict based off https://stackoverflow.com/a/21894086
class UserMapping(collections.abc.MutableMapping, structures.CopyWrapper):
    """
    A mapping storing User objects by UID, as well as UIDs by nick via
    the 'bynick' attribute
    """
    def __init__(self, irc, data=None):
        if data is not None:
            assert isinstance(data, dict)
            self._data = data
        else:
            self._data = {}
        self.bynick = collections.defaultdict(list)
        self._irc = irc

    def __getitem__(self, key):
        return self._data[key]

    def __setitem__(self, key, userobj):
        assert hasattr(userobj, 'lower_nick'), "Cannot add object without lower_nick attribute to UserMapping"
        if key in self._data:
            log.warning('(%s) Attempting to replace User object for %r: %r -> %r', self._irc.name,
                        key, self._data.get(key), userobj)

        self._data[key] = userobj
        self.bynick.setdefault(userobj.lower_nick, []).append(key)

    def __delitem__(self, key):
        # Remove this entry from the bynick index
        if self[key].lower_nick in self.bynick:
            self.bynick[self[key].lower_nick].remove(key)

            if not self.bynick[self[key].lower_nick]:
                del self.bynick[self[key].lower_nick]

        del self._data[key]

    # Generic container methods. XXX: consider abstracting this out in structures?
    def __repr__(self):
        return "%s(%s)" % (self.__class__.__name__, self._data)

    def __iter__(self):
        return iter(self._data)

    def __len__(self):
        return len(self._data)

    def __contains__(self, key):
        return self._data.__contains__(key)

    def __copy__(self):
        return self.__class__(self._irc, data=self._data.copy())

class PyLinkNetworkCore(structures.CamelCaseToSnakeCase):
    """Base IRC object for PyLink."""

    def __init__(self, netname):

        self.loghandlers = []
        self.name = netname
        self.conf = conf.conf
        if not hasattr(self, 'sid'):
            self.sid = None
        # serverdata may be overridden as a property on some protocols
        if netname in conf.conf['servers'] and not hasattr(self, 'serverdata'):
            self.serverdata = conf.conf['servers'][netname]

        self.protoname = self.__class__.__module__.split('.')[-1]  # Remove leading pylinkirc.protocols.

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
        self._aborted_send = threading.Event()
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
        except (KeyError, TypeError):  # Not set up; just ignore.
            return

        log.debug('(%s) Setting up channel logging to channels %r', self.name,
                  channels)

        # Only create handlers if they haven't already been set up.
        if not self.loghandlers:
            if not isinstance(channels, dict):
                log.warning('(%s) Got invalid channel logging configuration %r; are your indentation '
                            'and block commenting consistent?', self.name, channels)
                return

            for channel, chandata in channels.items():
                # Fetch the log level for this channel block.
                level = None
                if isinstance(chandata, dict):
                    level = chandata.get('loglevel')
                else:
                    log.warning('(%s) Got invalid channel logging pair %r: %r; are your indentation '
                                'and block commenting consistent?', self.name, channel, chandata)

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
        self.users = UserMapping(self)

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
        for hook_pair in world.hooks[hook_cmd].copy():
            hook_func = hook_pair[1]
            try:
                log.debug('(%s) Calling hook function %s from plugin "%s"', self.name,
                          hook_func, hook_func.__module__)
                retcode = hook_func(self, numeric, command, parsed_args)

                if retcode is False:
                    log.debug('(%s) Stopping hook loop for %r (command=%r)', self.name,
                              hook_func, command)
                    break

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

    def msg(self, target, text, notice=None, source=None, loopback=True, wrap=True):
        """Handy function to send messages/notices to clients. Source
        is optional, and defaults to the main PyLink client if not specified."""
        if not text:
            return

        if not (source or self.pseudoclient):
            # No explicit source set and our main client wasn't available; abort.
            return
        source = source or self.pseudoclient.uid

        def _msg(text):
            if notice:
                self.notice(source, target, text)
                cmd = 'PYLINK_SELF_NOTICE'
            else:
                self.message(source, target, text)
                cmd = 'PYLINK_SELF_PRIVMSG'

            # Determines whether we should send a hook for this msg(), to forward things like services
            # replies across relay.
            if loopback:
                self.call_hooks([source, cmd, {'target': target, 'text': text}])

        # Optionally wrap the text output.
        if wrap:
            for line in self.wrap_message(source, target, text):
                _msg(line)
        else:
            _msg(text)

    def _reply(self, text, notice=None, source=None, private=None, force_privmsg_in_private=False,
            loopback=True, wrap=True):
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

        self.msg(target, text, notice=notice, source=source, loopback=loopback, wrap=wrap)

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

    def get_service_option(self, servicename, option, default=None, global_option=None):
        """
        Returns the value of the requested service bot option on the current network, or the
        global value if it is not set for this network. This function queries and returns:

        1) If present, the value of the config option servers::<NETNAME>::<SERVICENAME>_<OPTION>
        2) If present, the value of the config option <SERVICENAME>::<GLOBAL_OPTION>, where
           <GLOBAL_OPTION> is either the 'global_option' keyword argument or <OPTION>.
        3) The default value given in the 'keyword' argument.

        While service bot and config option names can technically be uppercase or mixed case,
        the convention is to define them in all lowercase characters.
        """
        netopt = self.serverdata.get('%s_%s' % (servicename, option))
        if netopt is not None:
            return netopt

        if global_option is not None:
            option = global_option
        globalopt = conf.conf.get(servicename, {}).get(option)
        if globalopt is not None:
            return globalopt

        return default

    def get_service_options(self, servicename: str, option: str, itertype: type, global_option=None):
        """
        Returns a merged copy of the requested service bot option. This includes:

        1) If present, the value of the config option servers::<NETNAME>::<SERVICENAME>_<OPTION> (netopt)
        2) If present, the value of the config option <SERVICENAME>::<GLOBAL_OPTION>, where
           <GLOBAL_OPTION> is either the 'global_option' keyword value or <OPTION> (globalopt)

        For itertype, the following types are allowed:
            - list: items are combined as globalopt + netopt
            - dict: items are combined as {**globalopt, **netopt}
        """
        netopt = self.serverdata.get('%s_%s' % (servicename, option)) or itertype()
        globalopt = conf.conf.get(servicename, {}).get(global_option or option) or itertype()
        return utils.merge_iterables(globalopt, netopt)

    def has_cap(self, capab):
        """
        Returns whether this protocol module instance has the requested capability.
        """
        return capab.lower() in self.protocol_caps

    ## Shared helper functions
    def _pre_connect(self):
        """
        Implements triggers called before a network connects.
        """
        self._aborted_send.clear()
        self._aborted.clear()
        self._init_vars()

        try:
            self.validate_server_conf()
        except Exception as e:
            log.error("(%s) Configuration error: %s", self.name, e)
            raise

    def _run_autoconnect(self):
        """Blocks for the autoconnect time and returns True if autoconnect is enabled."""
        if world.shutting_down.is_set():
            log.debug('(%s) _run_autoconnect: aborting autoconnect attempt since we are shutting down.', self.name)
            return

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
        """
        Implements triggers called before a network disconnects.
        """
        self._aborted.set()
        self.was_successful = self.connected.is_set()
        log.debug('(%s) _pre_disconnect: got %s for was_successful state', self.name, self.was_successful)

        log.debug('(%s) _pre_disconnect: Clearing self.connected state.', self.name)
        self.connected.clear()

        log.debug('(%s) _pre_disconnect: Removing channel logging handlers due to disconnect.', self.name)
        while self.loghandlers:
            log.removeHandler(self.loghandlers.pop())

    def _post_disconnect(self):
        """
        Implements triggers called after a network disconnects.
        """
        # Internal hook signifying that a network has disconnected.
        self.call_hooks([None, 'PYLINK_DISCONNECT', {'was_successful': self.was_successful}])

        # Clear the to_lower cache.
        self.to_lower.cache_clear()

    def _remove_client(self, numeric):
        """
        Internal function to remove a client from our internal state.

        If the removal was successful, return the User object for the given numeric (UID)."""
        for c, v in self.channels.copy().items():
            v.remove_user(numeric)
            # Clear empty non-permanent channels.
            if not (self.channels[c].users or ((self.cmodes.get('permanent'), None) in self.channels[c].modes)):
                del self.channels[c]

        sid = self.get_server(numeric)
        try:
            userobj = self.users[numeric]
            del self.users[numeric]
            self.servers[sid].users.discard(numeric)
        except KeyError:
            log.debug('(%s) Skipping removing client %s that no longer exists', self.name, numeric,
                      exc_info=True)
        else:
            log.debug('(%s) Removing client %s from user + server state', self.name, numeric)
            return userobj

    ## State checking functions
    def nick_to_uid(self, nick, multi=False, filterfunc=None):
        """Looks up the UID of a user with the given nick, or return None if no such nick exists.

        If multi is given, return all matches for nick instead of just the last result. (Return an empty list if no matches)
        If filterfunc is given, filter matched users by the given function first."""
        nick = self.to_lower(nick)

        uids = self.users.bynick.get(nick, [])

        if filterfunc:
            uids = list(filter(filterfunc, uids))

        if multi:
            return uids
        else:
            if len(uids) > 1:
                log.warning('(%s) Multiple UIDs found for nick %r: %r; using the last one!', self.name, nick, uids)
            try:
                return uids[-1]
            except IndexError:
                return None

    def is_internal_client(self, uid):
        """
        Returns whether the given UID is a PyLink client.

        This returns False if the numeric doesn't exist.
        """
        sid = self.get_server(uid)
        if sid and self.servers[sid].internal:
            return True
        return False

    def is_internal_server(self, sid):
        """Returns whether the given SID is an internal PyLink server."""
        return (sid in self.servers and self.servers[sid].internal)

    def get_server(self, uid):
        """Finds the ID of the server a user is on. Return None if the user does not exist."""
        userobj = self.users.get(uid)
        if userobj:
            return userobj.server

    def is_manipulatable_client(self, uid):
        """
        Returns whether the given client is marked manipulatable for interactions
        such as force-JOIN.
        """
        return self.is_internal_client(uid) and self.users[uid].manipulatable

    def get_service_bot(self, uid):
        """
        Checks whether the given UID exists and is a registered service bot.

        If True, returns the corresponding ServiceBot object.
        Otherwise, return False.
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

    @functools.lru_cache(maxsize=8192)
    def to_lower(self, text):
        """
        Returns the lowercase representation of text. This respects IRC casemappings defined by the protocol module.
        """
        if (not text) or (not isinstance(text, str)):
            return text
        if self.casemapping == 'rfc1459':
            text = text.replace('{', '[')
            text = text.replace('}', ']')
            text = text.replace('|', '\\')
            text = text.replace('~', '^')
        # Encode the text as bytes first, and then lowercase it so that only ASCII characters are
        # changed. Unicode in channel names, etc. *is* case sensitive!
        # Interesting, a quick emperical test found that this method is actually faster than str.translate()?!
        return text.encode().lower().decode()

    _NICK_REGEX = r'^[A-Za-z\|\\_\[\]\{\}\^\`][A-Z0-9a-z\-\|\\_\[\]\{\}\^\`]*$'
    @classmethod
    def is_nick(cls, s, nicklen=None):
        """
        Returns whether the string given is a valid nick.

        Other platforms SHOULD redefine this if their definition of a valid nick is different."""

        if nicklen and len(s) > nicklen:
            return False
        return bool(re.match(cls._NICK_REGEX, s))

    @staticmethod
    def is_channel(obj):
        """
        Returns whether the item given is a valid channel (for a mapping key).

        For IRC, this checks if the item's name starts with a "#".

        Other platforms SHOULD redefine this if they track channels by some other format (e.g. numerical IDs).
        """
        return str(obj).startswith('#')


    # Modified from https://stackoverflow.com/a/106223 (RFC 1123):
    # - Allow hostnames that end in '.'
    # - Require at least one '.' in the hostname
    _HOSTNAME_RE = re.compile(r'^(([a-zA-Z0-9]|[a-zA-Z0-9][a-zA-Z0-9\-]*[a-zA-Z0-9])\.)+'
                              r'([A-Za-z0-9]|[A-Za-z0-9][A-Za-z0-9\-]*[A-Za-z0-9])*$')
    @classmethod
    def is_server_name(cls, text):
        """Returns whether the string given is a valid server name."""
        return bool(cls._HOSTNAME_RE.match(text))

    _HOSTMASK_RE = re.compile(r'^\S+!\S+@\S+$')
    @classmethod
    def is_hostmask(cls, text):
        """
        Returns whether the given text is a valid hostmask (nick!user@host)

        Other protocols may redefine this to meet their definition of hostmask
        (i.e. some unique identifier for a user).
        """
        # Band-aid patch here to prevent bad bans set by Janus forwarding people into invalid channels.
        return bool(cls._HOSTMASK_RE.match(text) and '#' not in text)

    # TODO: these wrappers really need to be standardized
    def _get_SID(self, sname):
        """Returns the SID of a server with the given name, if present."""
        name = sname.lower()

        if name in self.servers:
            return name

        for k, v in self.servers.items():
            if v.name.lower() == name:
                return k
        else:
            return sname  # Fall back to given text instead of None

    def _get_UID(self, target):
        """
        Converts a nick argument to its matching UID. This differs from nick_to_uid()
        in that it returns the original text instead of None if no matching nick is found.

        Subclasses like Clientbot may override this to tweak the nick lookup behaviour,
        e.g. by filtering virtual clients out.
        """

        if target in self.users:
            return target

        target = self.nick_to_uid(target) or target
        return target

    def _squit(self, numeric, command, args):
        """Handles incoming SQUITs."""

        split_server = self._get_SID(args[0])

        # Normally we'd only need to check for our SID as the SQUIT target, but Nefarious
        # actually uses the uplink server as the SQUIT target.
        # <- ABAAE SQ nefarious.midnight.vpn 0 :test
        if split_server in (self.sid, self.uplink):
            raise ProtocolError('SQUIT received: (reason: %s)' % args[-1])

        affected_users = []
        affected_servers = [split_server]
        affected_nicks = collections.defaultdict(list)
        log.debug('(%s) Splitting server %s (reason: %s)', self.name, split_server, args[-1])

        if split_server not in self.servers:
            log.warning("(%s) Tried to split a server (%s) that didn't exist!", self.name, split_server)
            return

        # Prevent RuntimeError: dictionary changed size during iteration
        old_servers = self.servers.copy()
        old_channels = self._channels.copy()

        # Cycle through our list of servers. If any server's uplink is the one that is being SQUIT,
        # remove them and all their users too.
        for sid, data in old_servers.items():
            if data.uplink == split_server:
                log.debug('Server %s also hosts server %s, removing those users too...', split_server, sid)
                # Recursively run SQUIT on any other hubs this server may have been connected to.
                args = self._squit(sid, 'SQUIT', [sid, "0",
                                   "PyLink: Automatically splitting leaf servers of %s" % sid])
                affected_users += args['users']
                affected_servers += args['affected_servers']

        for user in self.servers[split_server].users.copy():
            affected_users.append(user)
            nick = self.users[user].nick

            # Nicks affected is channel specific for SQUIT:. This makes Clientbot's SQUIT relaying
            # much easier to implement.
            for name, cdata in old_channels.items():
                if user in cdata.users:
                    affected_nicks[name].append(nick)

            log.debug('Removing client %s (%s)', user, nick)
            self._remove_client(user)

        serverdata = self.servers[split_server]
        sname = serverdata.name
        uplink = serverdata.uplink

        del self.servers[split_server]
        log.debug('(%s) Netsplit affected users: %s', self.name, affected_users)

        return {'target': split_server, 'users': affected_users, 'name': sname,
                'uplink': uplink, 'nicks': affected_nicks, 'serverdata': serverdata,
                'channeldata': old_channels, 'affected_servers': affected_servers}

    @staticmethod
    def _log_debug_modes(*args, **kwargs):
        """
        Log debug info related to mode parsing if enabled.
        """
        if conf.conf['pylink'].get('log_mode_parsers'):
            log.debug(*args, **kwargs)

    def _parse_modes(self, args, existing, supported_modes, is_channel=False, prefixmodes=None,
                     ignore_missing_args=False):
        """
        parse_modes() core.

        args: A mode string or a mode string split by space (type list)
        existing: A set or iterable of existing modes
        supported_modes: a dict of PyLink supported modes (mode names mapping
                         to mode chars, with *ABCD keys)
        prefixmodes: a dict of prefix modes (irc.prefixmodes style)
        """
        prefix = ''
        if isinstance(args, str):
            # If the modestring was given as a string, split it into a list.
            args = args.split()

        assert args, 'No valid modes were supplied!'
        modestring = args[0]
        args = args[1:]

        existing = set(existing)
        existing_casemap = {}
        for modepair in existing:
            arg = modepair[1]
            if arg is not None:
                existing_casemap[(modepair[0], self.to_lower(arg))] = modepair
            else:
                existing_casemap[modepair] = modepair

        res = []
        for mode in modestring:
            if mode in '+-':
                prefix = mode
            else:
                if not prefix:
                    prefix = '+'
                arg = None
                self._log_debug_modes('Current mode: %s%s; args left: %s', prefix, mode, args)
                try:
                    if prefixmodes and mode in self.prefixmodes:
                        # We're setting a prefix mode on someone (e.g. +o user1)
                        self._log_debug_modes('Mode %s: This mode is a prefix mode.', mode)
                        arg = args.pop(0)
                        # Convert nicks to UIDs implicitly
                        arg = self._get_UID(arg)
                        if arg not in self.users:  # Target doesn't exist, skip it.
                            self._log_debug_modes('(%s) Skipping setting mode "%s %s"; the '
                                                  'target doesn\'t seem to exist!', self.name,
                                                  mode, arg)
                            continue
                    elif mode in (supported_modes['*A'] + supported_modes['*B']):
                        # Must have parameter.
                        self._log_debug_modes('Mode %s: This mode must have parameter.', mode)
                        arg = args.pop(0)
                        if prefix == '-':
                            if mode in supported_modes['*B'] and arg == '*':
                                # Charybdis allows unsetting +k without actually
                                # knowing the key by faking the argument when unsetting
                                # as a single "*".
                                # We'd need to know the real argument of +k for us to
                                # be able to unset the mode.
                                oldarg = dict(existing).get(mode)
                                if oldarg:
                                    # Set the arg to the old one on the channel.
                                    arg = oldarg
                                    self._log_debug_modes("Mode %s: coersing argument of '*' to %r.", mode, arg)

                            self._log_debug_modes('(%s) parse_modes: checking if +%s %s is in old modes list: %s; existing_casemap=%s', self.name, mode, arg, existing, existing_casemap)

                            arg = self.to_lower(arg)
                            casefolded_modepair = existing_casemap.get((mode, arg))  # Case fold arguments as needed
                            if casefolded_modepair not in existing:
                                # Ignore attempts to unset parameter modes that don't exist.
                                self._log_debug_modes("(%s) parse_modes: ignoring removal of non-existent list mode +%s %s; casefolded_modepair=%s", self.name, mode, arg, casefolded_modepair)
                                continue
                            arg = casefolded_modepair[1]

                    elif prefix == '+' and mode in supported_modes['*C']:
                        # Only has parameter when setting.
                        self._log_debug_modes('Mode %s: Only has parameter when setting.', mode)
                        arg = args.pop(0)
                except IndexError:
                    logfunc = self._log_debug_modes if ignore_missing_args else log.warning
                    logfunc('(%s) Error while parsing mode %r: mode requires an '
                            'argument but none was found. (modestring: %r)',
                            self.name, mode, modestring)
                    continue  # Skip this mode; don't error out completely.
                newmode = (prefix + mode, arg)
                res.append(newmode)

                # Tentatively apply the new mode to the "existing" mode list. This is so queries
                # like +b-b *!*@example.com *!*@example.com behave correctly
                # (we can't rely on the original mode list to check whether a mode currently exists)
                existing = self._apply_modes(existing, [newmode], is_channel=is_channel)

                lowered_mode = (newmode[0][-1], self.to_lower(newmode[1]) if newmode[1] else newmode[1])
                if prefix == '+' and lowered_mode not in existing_casemap:
                    existing_casemap[lowered_mode] = (mode, arg)
                elif prefix == '-' and lowered_mode in existing_casemap:
                    del existing_casemap[lowered_mode]
        return res

    def parse_modes(self, target, args, ignore_missing_args=False):
        """Parses a modestring list into a list of (mode, argument) tuples.
        ['+mitl-o', '3', 'person'] => [('+m', None), ('+i', None), ('+t', None), ('+l', '3'), ('-o', 'person')]
        """
        # http://www.irc.org/tech_docs/005.html
        # A = Mode that adds or removes a nick or address to a list. Always has a parameter.
        # B = Mode that changes a setting and always has a parameter.
        # C = Mode that changes a setting and only has a parameter when set.
        # D = Mode that changes a setting and never has a parameter.

        is_channel = self.is_channel(target)
        if not is_channel:
            self._log_debug_modes('(%s) Using self.umodes for this query: %s', self.name, self.umodes)

            if target not in self.users:
                self._log_debug_modes('(%s) Possible desync! Mode target %s is not in the users index.', self.name, target)
                return []  # Return an empty mode list

            supported_modes = self.umodes
            oldmodes = self.users[target].modes
            prefixmodes = None
        else:
            self._log_debug_modes('(%s) Using self.cmodes for this query: %s', self.name, self.cmodes)

            supported_modes = self.cmodes
            oldmodes = self._channels[target].modes
            prefixmodes = self._channels[target].prefixmodes

        return self._parse_modes(args, oldmodes, supported_modes, is_channel=is_channel,
                                 prefixmodes=prefixmodes, ignore_missing_args=ignore_missing_args)

    def _apply_modes(self, old_modelist, changedmodes, is_channel=False,
                     prefixmodes=None):
        """
        Takes a list of parsed IRC modes, and applies them onto the given target mode list.
        """
        modelist = set(old_modelist)
        mapping = collections.defaultdict(set)

        if is_channel:
            supported_modes = self.cmodes
        else:
            supported_modes = self.umodes

        for modepair in modelist:  # Make a mapping of mode chars to values
            mapping[modepair[0]].add(modepair[1])

        for mode in changedmodes:
            # Chop off the +/- part that parse_modes gives; it's meaningless for a mode list.
            try:
                real_mode = (mode[0][1], mode[1])
            except IndexError:
                real_mode = mode

            if is_channel:
                if prefixmodes is not None:
                    # We only handle +qaohv for now. Iterate over every supported mode:
                    # if the IRCd supports this mode and it is the one being set, add/remove
                    # the person from the corresponding prefix mode list (e.g. c.prefixmodes['op']
                    # for ops).
                    for pmode, pmodelist in prefixmodes.items():
                        if pmode in supported_modes and real_mode[0] == supported_modes[pmode]:
                            if mode[0][0] == '+':
                                pmodelist.add(mode[1])
                            else:
                                pmodelist.discard(mode[1])

                if real_mode[0] in self.prefixmodes:
                    # Don't add prefix modes to Channel.modes; they belong in the
                    # prefixmodes mapping handled above.
                    self._log_debug_modes('(%s) Not adding mode %s to Channel.modes because '
                                          'it\'s a prefix mode.', self.name, str(mode))
                    continue

            if mode[0][0] != '-':  # Adding a mode; assume add if no explicit +/- is given
                self._log_debug_modes('(%s) Adding mode %r on %s', self.name, real_mode, modelist)
                existing = mapping.get(real_mode[0])
                if existing and real_mode[0] not in supported_modes['*A']:
                    # The mode we're setting takes a parameter, but is not a list mode (like +beI).
                    # Therefore, only one version of it can exist at a time, and we must remove
                    # any old modepairs using the same letter. Otherwise, we'll get duplicates when,
                    # for example, someone sets mode "+l 30" on a channel already set "+l 25".
                    self._log_debug_modes('(%s) Old modes for mode %r exist in %s, removing them: %s',
                              self.name, real_mode, modelist, str(existing))
                    while existing:
                        oldvalue = existing.pop()
                        modelist.discard((real_mode[0], oldvalue))

                modelist.add(real_mode)
                mapping[real_mode[0]].add(real_mode[1])
            else:  # Removing a mode
                self._log_debug_modes('(%s) Removing mode %r from %s', self.name, real_mode, modelist)

                existing = mapping.get(real_mode[0])
                arg = real_mode[1]
                # Mode requires argument for removal (case insensitive)
                if real_mode[0] in (supported_modes['*A'] + supported_modes['*B']):
                    modelist.discard((real_mode[0], self.to_lower(arg)))
                # Mode does not require argument for removal - remove all modes entries with the same character
                else:
                    while existing:
                        oldvalue = existing.pop()
                        if arg is None or self.to_lower(arg) == self.to_lower(oldvalue):
                            modelist.discard((real_mode[0], oldvalue))
        self._log_debug_modes('(%s) Final modelist: %s', self.name, modelist)
        return modelist

    def apply_modes(self, target, changedmodes):
        """Takes a list of parsed IRC modes, and applies them on the given target.

        The target can be either a channel or a user; this is handled automatically."""
        is_channel = self.is_channel(target)

        prefixmodes = None
        try:
            if is_channel:
                c = self._channels[target]
                old_modelist = c.modes
                prefixmodes = c.prefixmodes
            else:
                old_modelist = self.users[target].modes
        except KeyError:
            log.warning('(%s) Possible desync? Mode target %s is unknown.', self.name, target)
            return

        modelist = self._apply_modes(old_modelist, changedmodes, is_channel=is_channel,
                                     prefixmodes=prefixmodes)

        try:
            if is_channel:
                self._channels[target].modes = modelist
            else:
                self.users[target].modes = modelist
        except KeyError:
            log.warning("(%s) Invalid MODE target %s (is_channel=%s)", self.name, target, is_channel)

    @staticmethod
    def _flip(mode):
        """Flips a mode character."""
        # Make it a list first; strings don't support item assignment
        mode = list(mode)
        if mode[0] == '-':  # Query is something like "-n"
            mode[0] = '+'  # Change it to "+n"
        elif mode[0] == '+':
            mode[0] = '-'
        else:  # No prefix given, assume +
            mode.insert(0, '-')
        return ''.join(mode)

    def reverse_modes(self, target, modes, oldobj=None):
        """
        IRC specific: Reverses/inverts the mode string or mode list given.

        Optionally, an oldobj argument can be given to look at an earlier state of
        a channel/user object, e.g. for checking the op status of a mode setter
        before their modes are processed and added to the channel state.

        This function allows both mode strings or mode lists. Example uses:
            "+mi-lk test => "-mi+lk test"
            "mi-k test => "-mi+k test"
            [('+m', None), ('+r', None), ('+l', '3'), ('-o', 'person')
             => [('-m', None), ('-r', None), ('-l', None), ('+o', 'person')}]
            {('s', None), ('+o', 'whoever') => [('-s', None), ('-o', 'whoever')}]
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
                    # Add prefix modes to the list of old modes
                    oldmodes |= {(self.cmodes[name], u) for u in userlist}
                except KeyError:
                    continue
        else:
            oldmodes = set(self.users[target].modes)
            possible_modes = self.umodes

        oldmodes_mapping = dict(oldmodes)
        oldmodes_lower = {(modepair[0], self.to_lower(modepair[1]) if modepair[1] else modepair[1])
                          for modepair in oldmodes}

        newmodes = []
        self._log_debug_modes('(%s) reverse_modes: old/current mode list for %s is: %s', self.name,
                              target, oldmodes)
        for char, arg in modes:
            # Mode types:
            # A = Mode that adds or removes a nick or address to a list. Always has a parameter.
            # B = Mode that changes a setting and always has a parameter.
            # C = Mode that changes a setting and only has a parameter when set.
            # D = Mode that changes a setting and never has a parameter.
            mchar = char[-1]
            if mchar in possible_modes['*B'] + possible_modes['*C']:
                # We need to look at the current mode list to reset modes that take arguments
                # For example, trying to bounce +l 30 on a channel that had +l 50 set should
                # give "+l 50" and not "-l".
                oldarg = oldmodes_mapping.get(mchar)

                if oldarg:  # Old mode argument for this mode existed, use that.
                    mpair = ('+%s' % mchar, oldarg)

                else:  # Not found, flip the mode then.

                    # Mode takes no arguments when unsetting.
                    if mchar in possible_modes['*C'] and char[0] != '-':
                        arg = None
                    mpair = (self._flip(char), arg)
            else:
                mpair = (self._flip(char), arg)

            if arg is not None:
                arg = self.to_lower(arg)
            if char[0] != '-' and (mchar, arg) in oldmodes:
                # Mode is already set.
                self._log_debug_modes("(%s) reverse_modes: skipping reversing '%s %s' with %s since we're "
                                      "setting a mode that's already set.", self.name, char, arg, mpair)
                continue
            elif char[0] == '-' and (mchar, arg) not in oldmodes and mchar in possible_modes['*A']:
                # We're unsetting a list or prefix mode that was never set - don't set it in response!
                # TS6 IRCds lacks server-side verification for this and can cause annoying mode floods.
                self._log_debug_modes("(%s) reverse_modes: skipping reversing '%s %s' with %s since it "
                                      "wasn't previously set.", self.name, char, arg, mpair)
                continue
            elif char[0] == '-' and mchar not in oldmodes_mapping:
                # Check the same for regular modes that previously didn't exist
                self._log_debug_modes("(%s) reverse_modes: skipping reversing '%s %s' with %s since it "
                                      "wasn't previously set.", self.name, char, arg, mpair)
                continue
            elif mpair in newmodes:
                # Check the same for regular modes that previously didn't exist
                self._log_debug_modes("(%s) reverse_modes: skipping duplicate reverse mode %s", self.name,  mpair)
                continue
            newmodes.append(mpair)

        self._log_debug_modes('(%s) reverse_modes: new modes: %s', self.name, newmodes)
        if origstring:
            # If the original query is a string, send it back as a string.
            return self.join_modes(newmodes)
        else:
            return newmodes

    @staticmethod
    def join_modes(modes, sort=False):
        """
        IRC specific: Takes a list of (mode, arg) tuples in parse_modes() format, and
        joins them into a string.
        """
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
                # If not, the current prefix stays the same as the last mode pair; move on
                # to the next one.
                pass
            else:
                # Only when the prefix of this mode isn't the same as the last one do we add
                # the prefix to the mode string. This prevents '+nt-lk' from turning
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
            modelist += ' '
            modelist += ' '.join((str(arg) for arg in args))
        return modelist

    @classmethod
    def wrap_modes(cls, modes, limit, max_modes_per_msg=0):
        """
        IRC specific: Takes a list of modes and wraps it across multiple lines.
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
            # The +/- part is optional and is treated as the prefix of the last mode if not given,
            # or + (adding modes) if it is the first mode in the list.
            next_mode = modes.pop(0)

            modechar, arg = next_mode
            prefix = modechar[0]
            if prefix not in '+-':
                prefix = last_prefix
                # Explicitly add the prefix to the mode character to prevent
                # ambiguity when passing it to e.g. join_modes().
                modechar = prefix + modechar
                # XXX: because tuples are immutable, we have to replace the entire modepair...
                next_mode = (modechar, arg)

            # Figure out the length that the next mode will add to the buffer. If we're changing
            # from + to - (setting to removing modes) or vice versa, we'll need two characters:
            # the "+" or "-" as well as the actual mode char.
            next_length = 1
            if prefix != last_prefix:
                next_length += 1

            # Replace the last mode prefix with the current one for the next iteration.
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
                cls._log_debug_modes('wrap_modes: Adding mode %s to queued modes', str(next_mode))
                queued_modes.append(next_mode)
                cls._log_debug_modes('wrap_modes: queued modes: %s', queued_modes)
            else:
                # Otherwise, create a new message by joining the previous queued modes into a message.
                # Then, create a new message with our current mode.
                strings.append(cls.join_modes(queued_modes))
                queued_modes.clear()

                cls._log_debug_modes('wrap_modes: cleared queue (length %s) and now adding %s', limit, str(next_mode))
                queued_modes.append(next_mode)
                total_length = next_length
        else:
            # Everything fit in one line, so just use that.
            strings.append(cls.join_modes(queued_modes))

        cls._log_debug_modes('wrap_modes: returning %s for %s', strings, orig_modes)
        return strings

    def get_hostmask(self, user, realhost=False, ip=False):
        """
        Returns a representative hostmask / user friendly identifier for a user.
        On IRC, this is nick!user@host; other platforms may choose to define a different
        style for user hostmasks.

        If the realhost option is given, prefer showing the real host of the user instead
        of the displayed host.
        If the ip option is given, prefering showing the IP address of the user (this overrides
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
        Returns the display name of an entity:

        For servers, this returns the server name given a SID.
        For users, this returns a nick given the UID.
        For channels, return the channel name (returned as-is for IRC).
        """
        if entityid in self.servers:
            return self.servers[entityid].name
        elif entityid in self.users:
            return self.users[entityid].nick
        # Return channels as-is. Remember to strip any STATUSMSG prefixes like from @#channel
        elif self.is_channel(entityid.lstrip(''.join(self.prefixmodes.values()))):
            return entityid
        else:
            raise KeyError("Unknown UID/SID %s" % entityid)

    def is_privileged_service(self, entityid):
        """
        Returns whether the given UID and SID belongs to a privileged service.

        For IRC, this reads the 'ulines' option in the server configuration. Other platforms
        may override this to suit their needs.
        """
        ulines = self.serverdata.get('ulines', [])

        if entityid in self.users:
            sid = self.get_server(entityid)
        else:
            sid = entityid

        return self.get_friendly_name(sid) in ulines

    def is_oper(self, uid, **kwargs):
        """
        Returns whether the given user has operator / server administration status.
        For IRC, this checks usermode +o. Other platforms may choose to define this another way.

        The allowAuthed and allowOper keyword arguments are deprecated since PyLink 2.0-alpha4.
        """
        if 'allowAuthed' in kwargs or 'allowOper' in kwargs:
            log.warning('(%s) is_oper: the "allowAuthed" and "allowOper" options are deprecated as '
                        'of PyLink 2.0-alpha4 and now imply False and True respectively. To check for'
                        'PyLink account status, instead check the User.account attribute directly.',
                        self.name)

        if uid in self.users and ("o", None) in self.users[uid].modes:
            return True
        return False

    def match_host(self, glob, target, ip=True, realhost=True):
        """
        Checks whether the given host or given UID's hostmask matches the given glob
        (nick!user@host for IRC). PyLink extended targets are also supported.

        If the target given is a UID, and the 'ip' or 'realhost' options are True, this will also
        match against the target's IP address and real host, respectively.

        This function respects IRC casemappings (rfc1459 and ascii). If the given target is a UID,
        and the 'ip' option is enabled, the host portion of the glob is also matched as a CIDR range.
        """
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

            # Iterate over the hosts to match, since we may have multiple (check IP/real host)
            for host in hosts:
                if self.match_text(glob, host):
                    return True

            return False

        result = match_host_core()
        if invert:
            result = not result
        return result

    def match_text(self, glob, text):
        """
        Returns whether the given glob matches the given text under the network's current case mapping.
        """
        return utils.match_text(glob, text, filterfunc=self.to_lower)

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

    def make_channel_ban(self, uid, ban_type='ban', ban_style=None):
        """Creates a hostmask-based ban for the given user.

        Ban exceptions, invite exceptions quiets, and extbans are also supported by setting ban_type
        to the appropriate PyLink named mode (e.g. "ban", "banexception", "invex", "quiet", "ban_nonick")."""
        assert uid in self.users, "Unknown user %s" % uid

        # FIXME: verify that this is a valid mask.
        # XXX: support slicing hosts so things like *!ident@*.isp.net are possible. This is actually
        #      more annoying to do than it appears because of vHosts using /, IPv6 addresses
        #      (cloaked and uncloaked), etc.
        # TODO: make this not specific to IRC
        ban_style = ban_style or self.serverdata.get('ban_style') or \
            conf.conf['pylink'].get('ban_style') or '*!*@$host'

        template = string.Template(ban_style)
        banhost = template.safe_substitute(self.users[uid].get_fields())
        if not self.is_hostmask(banhost):
            raise ValueError("Ban mask %r is not a valid hostmask!" % banhost)

        if ban_type in self.cmodes:
            return ('+%s' % self.cmodes[ban_type], banhost)
        elif ban_type in self.extbans_acting:  # Handle extbans, which are generally "+b prefix:banmask"
            return ('+%s' % self.cmodes['ban'], self.extbans_acting[ban_type]+banhost)
        else:
            raise ValueError("ban_type %r is not available on IRCd %r" % (ban_type, self.protoname))

    def updateTS(self, sender, channel, their_ts, modes=None):
        """
        IRC specific: Merges modes of a channel given the remote TS and a list of modes.
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
                    if their_ts != 0:  # Sometimes unreal sends SJOIN with 0, don't warn for those
                        if self.serverdata.get('ignore_ts_errors'):
                            log.debug('(%s) Silently ignoring bogus TS %s on channel %s', self.name, their_ts, channel)
                        else:
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
        IRC specific: Nick collision preprocessor for user introductions.

        If the given nick matches an existing UID, send out a SAVE hook payload indicating a nick collision.
        """
        uid = self.nick_to_uid(nick)
        # If there is a nick collision, we simply alert plugins. Relay will purposely try to
        # lose fights and tag nicks instead, while other plugins can choose how to handle this.
        if uid:
            log.info('(%s) Nick collision on %s/%s, forwarding this to plugins', self.name,
                     uid, nick)
            self.call_hooks([self.sid, 'SAVE', {'target': uid}])

    def _expandPUID(self, entityid):
        """
        Returns the nick or server name for the given UID/SID. This method helps support protocol
        modules that use PUIDs internally, as they must convert them to talk with the uplink.
        """
        # TODO: stop hardcoding @ as separator
        if isinstance(entityid, str) and '@' in entityid:
            name = self.get_friendly_name(entityid)
            log.debug('(%s) _expandPUID: mangling pseudo ID %s to %s', self.name, entityid, name)
            return name
        return entityid  # Regular UID/SID, no change

    def wrap_message(self, source, target, text):
        """
        Wraps the given message text into multiple lines (length depends on how much the protocol
        allows), and returns these as a list.
        """
        # This is protocol specific, so stub it here in the base class.
        raise NotImplementedError

# When this many pings in a row are missed, the ping timer loop will force a disconnect on the
# next cycle. Effectively the ping timeout is: pingfreq * (KEEPALIVE_MAX_MISSED + 1)
KEEPALIVE_MAX_MISSED = 2

class IRCNetwork(PyLinkNetworkCoreWithUtils):
    S2S_BUFSIZE = 510

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._queue = None
        self._ping_timer = None
        self._socket = None
        self._buffer = bytearray()
        self._reconnect_thread = None
        self._queue_thread = None

    def _init_vars(self, *args, **kwargs):
        super()._init_vars(*args, **kwargs)

        # Set IRC specific variables for ping checking and queuing
        self.lastping = time.time()  # This actually tracks the last message received as of 2.0-alpha4
        self.pingfreq = self.serverdata.get('pingfreq') or 90

        self.maxsendq = self.serverdata.get('maxsendq', 4096)
        self._queue = queue.Queue(self.maxsendq)

    def _schedule_ping(self):
        """Schedules periodic pings in a loop."""
        self._ping_uplink()

        if self._aborted.is_set():
            return

        elapsed = time.time() - self.lastping
        if elapsed > (self.pingfreq * KEEPALIVE_MAX_MISSED):
            log.error('(%s) Disconnected from IRC: Ping timeout (%d secs)', self.name, elapsed)
            self.disconnect()
            return

        self._ping_timer = threading.Timer(self.pingfreq, self._schedule_ping)
        self._ping_timer.daemon = True
        self._ping_timer.name = 'Ping timer loop for %s' % self.name
        self._ping_timer.start()

        log.debug('(%s) Ping scheduled at %s', self.name, time.time())

    def _log_connection_error(self, *args, **kwargs):
        # Log connection errors to ERROR unless were shutting down (in which case,
        # the given text goes to DEBUG).
        if self._aborted.is_set() or world.shutting_down.is_set():
            log.debug(*args, **kwargs)
        else:
            log.error(*args, **kwargs)

    def _make_ssl_context(self):
        """
        Returns a ssl.SSLContext instance appropriate for this connection.
        """
        context = ssl.create_default_context()

        # Use the ssl-should-verify protocol capability to determine whether we should
        # accept invalid certs by default. Generally, cert validation is OFF for server protocols
        # and ON for client-based protocols like clientbot
        if self.serverdata.get('ssl_accept_invalid_certs', not self.has_cap("ssl-should-verify")):
            # Note: check_hostname has to be off to set verify_mode to CERT_NONE,
            # since it's possible for the remote link to not provide a cert at all
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        else:
            # Otherwise, only check cert hostname if the target is a hostname OR we have
            # ssl-should-verify defined
            context.check_hostname = self.serverdata.get('ssl_validate_hostname',
                self.has_cap("ssl-should-verify") or
                utils.get_hostname_type(self.serverdata['ip']) == 0)

        return context

    def _setup_ssl(self):
        """
        Initializes SSL/TLS for this network.
        """
        log.info('(%s) Using TLS/SSL for this connection...', self.name)
        cafile = self.serverdata.get('ssl_cafile')
        certfile = self.serverdata.get('ssl_certfile')
        keyfile = self.serverdata.get('ssl_keyfile')

        context = self._make_ssl_context()

        # Cert and key files are optional, load them if specified.
        if certfile and keyfile:
            try:
                cafile != None and context.load_verify_locations(cafile)
                context.load_cert_chain(certfile, keyfile)
            except OSError:
                 log.exception('(%s) Caught OSError trying to initialize the SSL connection; '
                               'are "ssl_certfile", "ssl_keyfile", and "ssl_cafile" set correctly?',
                               self.name)
                 raise

        self._socket = context.wrap_socket(self._socket, server_hostname=self.serverdata.get('ip'))

    def _verify_ssl(self):
        """
        Implements additional SSL/TLS verifications (so far, only certificate fingerprints when enabled).
        """
        peercert = self._socket.getpeercert(binary_form=True)

        # Hash type is configurable using the ssl_fingerprint_type
        # value, and defaults to sha256.
        hashtype = self.serverdata.get('ssl_fingerprint_type', 'sha256').lower()

        try:
            hashfunc = getattr(hashlib, hashtype)
        except AttributeError:
            raise conf.ConfigurationError('Unsupported or invalid TLS/SSL certificate fingerprint type %r',
                                          hashtype)
        else:
            expected_fp = self.serverdata.get('ssl_fingerprint')
            if expected_fp and peercert is None:
                raise ssl.CertificateError('TLS/SSL certificate fingerprint checking is enabled but the uplink '
                                           'did not provide a certificate')

            fp = hashfunc(peercert).hexdigest()

            if expected_fp:
                if fp != expected_fp:
                    # SSL Fingerprint doesn't match; break.
                    raise ssl.CertificateError('Uplink TLS/SSL certificate fingerprint (%s: %r) does not '
                                               'match the one configured (%s: %r)' % (hashtype, fp, hashtype, expected_fp))
                else:
                    log.info('(%s) Uplink TLS/SSL certificate fingerprint '
                             'verified (%s: %r)', self.name, hashtype, fp)
            elif hasattr(self._socket, 'context') and self._socket.context.verify_mode == ssl.CERT_NONE:
                log.info('(%s) Uplink\'s TLS/SSL certificate fingerprint (%s) '
                         'is %r. You can enhance the security of your '
                         'link by specifying this in a "ssl_fingerprint"'
                         ' option in your server block.', self.name,
                         hashtype, fp)

    def _connect(self):
        """
        Connects to the network.
        """
        self._pre_connect()

        remote = self.serverdata["ip"]
        port = self.serverdata["port"]
        try:
            if 'bindhost' in self.serverdata:
                # Try detecting the socket type from the bindhost if specified.
                force_ipv6 = utils.get_hostname_type(self.serverdata['bindhost']) == 2
            else:
                force_ipv6 = self.serverdata.get("ipv6")  # ternary value (None = use system default)

            if force_ipv6 is True:
                dns_stype = socket.AF_INET6
            elif force_ipv6 is False:
                dns_stype = socket.AF_INET
            else:
                dns_stype = socket.AF_UNSPEC

            dns_result = socket.getaddrinfo(remote, port, family=dns_stype)[0]
            ip = dns_result[-1][0]

            log.debug('(%s) Resolving address %s to %s (force_ipv6=%s)', self.name, remote, ip, force_ipv6)

            # Create the actual socket.
            self._socket = socket.socket(dns_result[0])

            # Set the socket bind if applicable.
            if 'bindhost' in self.serverdata:
                self._socket.bind((self.serverdata['bindhost'], 0))

            # Enable SSL if set to do so.
            self.ssl = self.serverdata.get('ssl')
            if self.ssl:
                self._setup_ssl()
            elif not ipaddress.ip_address(ip).is_loopback:
                log.warning('(%s) This connection will be made via plain text, which is vulnerable '
                            'to man-in-the-middle (MITM) attacks and passive eavesdropping. Consider '
                            'enabling TLS/SSL with either certificate validation or fingerprint '
                            'pinning to better secure your network traffic.', self.name)

            log.info("Connecting to network %r on %s:%s", self.name, ip, port)

            self._socket.settimeout(self.pingfreq)

            # Start the actual connection
            self._socket.connect((ip, port))

            if self not in world.networkobjects.values():
                log.debug("(%s) _connect: disconnecting socket %s as the network was removed",
                          self.name, self._socket)
                try:
                    self._socket.shutdown(socket.SHUT_RDWR)
                finally:
                    self._socket.close()
                return

            # Make sure future reads never block, since select doesn't always guarantee this.
            self._socket.setblocking(False)

            selectdriver.register(self)

            if self.ssl:
                self._verify_ssl()

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

        # _run_irc() or the protocol module it called raised an exception, meaning we've disconnected
        except:
            self._log_connection_error('(%s) Disconnected from IRC:', self.name, exc_info=True)
            if not self._aborted.is_set():
                self.disconnect()

    def connect(self):
        """
        Starts a thread to connect the network.
        """
        connect_thread = threading.Thread(target=self._connect, daemon=True,
                                          name="Connect thread for %s" %
                                          self.name)
        connect_thread.start()

    def disconnect(self):
        """Handle disconnects from the remote server."""
        if self._aborted.is_set():
            return

        self._pre_disconnect()

        # Stop the queue thread.
        if self._queue is not None:
            try:
                # XXX: queue.Queue.queue isn't actually documented, so this is probably not reliable in the long run.
                with self._queue.mutex:
                    self._queue.queue[0] = None
            except IndexError:
                self._queue.put(None)

        if self._socket is not None:
            try:
                selectdriver.unregister(self)
            except KeyError:
                pass
            try:
                log.debug('(%s) disconnect: shutting down read half of socket %s', self.name, self._socket)
                self._socket.shutdown(socket.SHUT_RD)
            except:
                log.debug('(%s) Error on socket shutdown:', self.name, exc_info=True)

            log.debug('(%s) disconnect: waiting for write half of socket %s to shutdown', self.name, self._socket)
            # Wait for the write half to shut down when applicable.
            if self._queue_thread is None or self._aborted_send.wait(10):
                log.debug('(%s) disconnect: closing socket %s', self.name, self._socket)
                self._socket.close()

        # Stop the ping timer.
        if self._ping_timer:
            log.debug('(%s) Canceling pingTimer at %s due to disconnect() call', self.name, time.time())
            self._ping_timer.cancel()
        self._buffer.clear()
        self._post_disconnect()

        # Clear old sockets.
        self._socket = None

        self._start_reconnect()

    def _start_reconnect(self):
        """Schedules a reconnection to the network."""
        def _reconnect():
            # _run_autoconnect() will block and return True after the autoconnect
            # delay has passed, if autoconnect is disabled. We do not want it to
            # block whatever is calling disconnect() though, so we run it in a new
            # thread.
            if self._run_autoconnect():
                self.connect()

        if self not in world.networkobjects.values():
            log.debug('(%s) _start_reconnect: Stopping reconnect timer as the network was removed', self.name)
            return
        elif self._reconnect_thread is None or not self._reconnect_thread.is_alive():
            self._reconnect_thread = threading.Thread(target=_reconnect, name="Reconnecting network %s" % self.name)
            self._reconnect_thread.start()
        else:
            log.debug('(%s) Ignoring attempt to reschedule reconnect as one is in progress.', self.name)

    def handle_events(self, line):
        raise NotImplementedError

    def parse_irc_command(self, line):
        """Sends a command to the protocol module."""
        log.debug("(%s) <- %s", self.name, line)
        if not line:
            log.warning("(%s) Got empty line %r from IRC?", self.name, line)
            return

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
        """
        Message handler, called when select() has data to read.
        """
        if self._socket is None:
            log.debug('(%s) Ignoring attempt to read data because self._socket is None', self.name)
            return

        data = bytearray()
        try:
            data = self._socket.recv(2048)
        except (BlockingIOError, ssl.SSLWantReadError, ssl.SSLWantWriteError):
            log.debug('(%s) No data to read, trying again later...', self.name, exc_info=True)
            return
        except OSError:
            # Suppress socket read warnings from lingering recv() calls if
            # we've been told to shutdown.
            if self._aborted.is_set():
                return
            raise

        self._buffer += data
        if not data:
            self._log_connection_error('(%s) Connection lost, disconnecting.', self.name)
            self.disconnect()
            return

        while b'\n' in self._buffer:
            line, self._buffer = self._buffer.split(b'\n', 1)
            line = line.strip(b'\r')
            line = line.decode(self.encoding, "replace")
            self.parse_irc_command(line)

        # Update the last message received time
        self.lastping = time.time()

    def _send(self, data):
        """Sends raw text to the uplink server."""
        if self._aborted.is_set() or self._socket is None:
            log.debug("(%s) Not sending message %r since the connection is dead", self.name, data)
            return

        # Safeguard against newlines in input!! Otherwise, each line gets
        # treated as a separate command, which is particularly nasty.
        data = data.replace('\n', ' ')
        encoded_data = data.encode(self.encoding, 'replace')
        if self.S2S_BUFSIZE > 0:  # Apply message cutoff as needed
            encoded_data = encoded_data[:self.S2S_BUFSIZE]
        encoded_data += b"\r\n"

        log.debug("(%s) -> %s", self.name, data)

        while True:
            try:
                self._socket.send(encoded_data)
            except (BlockingIOError, ssl.SSLWantReadError, ssl.SSLWantWriteError):
                # The send attempt failed, wait a little bit.
                # I would prefer using a blocking socket and MSG_DONTWAIT in recv()'s flags
                # but SSLSocket doesn't support that...
                throttle_time = self.serverdata.get('throttle_time', 0)
                if self._aborted.wait(throttle_time):
                    break
                continue
            except:
                log.exception("(%s) Failed to send message %r; aborting!", self.name, data)
                self.disconnect()
                return
            else:
                break

    def send(self, data, queue=True):
        """send() wrapper with optional queueing support."""
        if self._aborted.is_set():
            log.debug('(%s) refusing to queue data %r as self._aborted is set', self.name, data)
            return
        if queue:
            # XXX: we don't really know how to handle blocking queues yet, so
            # it's better to not expose that yet.
            try:
                self._queue.put_nowait(data)
            except QUEUE_FULL:
                log.error('(%s) Max SENDQ exceeded (%s), disconnecting!', self.name, self._queue.maxsize)
                self.disconnect()
                raise
        else:
            self._send(data)

    def _process_queue(self):
        """Loop to process outgoing queue data."""
        while True:
            throttle_time = self.serverdata.get('throttle_time', 0)
            if not self._aborted.wait(throttle_time):
                data = self._queue.get()
                if data is None:
                    log.debug('(%s) Stopping queue thread due to getting None as item', self.name)
                    break
                elif self not in world.networkobjects.values():
                    log.debug('(%s) Stopping stale queue thread; no longer matches world.networkobjects', self.name)
                    break
                elif self._aborted.is_set():
                    # The _aborted flag may have changed while we were waiting for an item,
                    # so check for it again.
                    log.debug('(%s) Stopping queue thread since the connection is dead', self.name)
                    break
                elif data:
                    self._send(data)
            else:
                break

        # Once we're done here, shut down the write part of the socket.
        if self._socket:
            log.debug('(%s) _process_queue: shutting down write half of socket %s', self.name, self._socket)
            self._socket.shutdown(socket.SHUT_WR)
        self._aborted_send.set()

    def wrap_message(self, source, target, text):
        """
        Wraps the given message text into multiple lines, and returns these as a list.

        For IRC, the maximum length of one message is calculated as S2S_BUFSIZE (default to 510)
        minus the length of ":sender-nick!sender-user@sender-host PRIVMSG #target :"
        """
        # We explicitly want wrapping (e.g. for messages eventually making its way to a user), so
        # use the default bufsize of 510 even if the IRCd's S2S protocol allows infinitely long
        # long messages.
        bufsize = self.S2S_BUFSIZE or IRCNetwork.S2S_BUFSIZE
        try:
            target = self.get_friendly_name(target)
        except KeyError:
            log.warning('(%s) Possible desync? Error while expanding wrap_message target %r '
                        '(source=%s)', self.name, target, source, exc_info=True)

        prefixstr = ":%s PRIVMSG %s :" % (self.get_hostmask(source), target)
        maxlen = bufsize - len(prefixstr)

        log.debug('(%s) wrap_message: length of prefix %r is %s, bufsize=%s, maxlen=%s',
                  self.name, prefixstr, len(prefixstr), bufsize, maxlen)

        if maxlen <= 0:
            log.error('(%s) Got invalid maxlen %s for wrap_message (%s -> %s)', self.name, maxlen,
                      source, target)
            return [text]

        return textwrap.wrap(text, width=maxlen)

Irc = IRCNetwork

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
        if isinstance(name, str):
            self.name = name.lower()
        else:
            self.name = name
        self.desc = desc
        self._irc = irc

        assert uplink is None or uplink in self._irc.servers, "Unknown uplink %s" % uplink

        if uplink is None:
            self.hopcount = 1
        else:
            self.hopcount = self._irc.servers[uplink].hopcount + 1

        # Has the server finished bursting yet?
        self.has_eob = False

    def __repr__(self):
        return 'Server(%s)' % self.name

IrcServer = Server

class Channel(TSObject, structures.CamelCaseToSnakeCase, structures.CopyWrapper):
    """PyLink IRC channel class."""

    def __init__(self, irc, name=None):
        super().__init__()
        # Initialize variables, such as the topic, user list, TS, who's opped, etc.
        self.users = set()
        self.modes = set()
        self.topic = ''
        self.prefixmodes = {'op': set(), 'halfop': set(), 'voice': set(),
                            'owner': set(), 'admin': set()}
        self._irc = irc

        # Determines whether a topic has been set here or not. Protocol modules
        # should set this.
        self.topicset = False

        # Saves the channel name (may be useful to plugins, etc.)
        self.name = name

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
        return bool(self.get_prefix_modes(uid))

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
        Returns a numeric value for a named prefix mode: higher ranks have lower values
        (sorted first), and lower ranks have higher values (sorted last).

        This function essentially implements a sorted() key function for named prefix modes.
        """
        values = {'owner': 0, 'admin': 100, 'op': 200, 'halfop': 300, 'voice': 500}

        # Default to highest value (1000) for unknown modes, should they appear.
        return values.get(key, 1000)

    def get_prefix_modes(self, uid, prefixmodes=None):
        """
        Returns a list of all named prefix modes the user has in the channel, in
        decreasing order from owner to voice.

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
