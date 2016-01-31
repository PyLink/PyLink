"""
classes.py - Base classes for PyLink IRC Services.

This module contains the base classes used by PyLink, including threaded IRC
connections and objects used to represent IRC servers, users, and channels.

Here be dragons.
"""

import threading
from random import randint
import time
import socket
import threading
import ssl
from collections import defaultdict
import hashlib
from copy import deepcopy

from log import *
import world
import utils

### Exceptions

class ProtocolError(Exception):
    pass

### Internal classes (users, servers, channels)

class Irc():
    """Base IRC object for PyLink."""

    def __init__(self, netname, proto, conf):
        """
        Initializes an IRC object. This takes 3 variables: the network name
        (a string), the name of the protocol module to use for this connection,
        and a configuration object.
        """
        self.loghandlers = []
        self.name = netname.lower()
        self.conf = conf
        self.serverdata = conf['servers'][netname]
        self.sid = self.serverdata["sid"]
        self.botdata = conf['bot']
        self.protoname = proto.__name__
        self.proto = proto.Class(self)
        self.pingfreq = self.serverdata.get('pingfreq') or 30
        self.pingtimeout = self.pingfreq * 2

        self.connected = threading.Event()
        self.aborted = threading.Event()

        if world.testing:
            # HACK: Don't thread if we're running tests.
            self.connect()
        else:
            self.connection_thread = threading.Thread(target=self.connect,
                                                      name="Listener for %s" %
                                                      self.name)
            self.connection_thread.start()
        self.pingTimer = None

    def logSetup(self):
        """
        Initializes any channel loggers defined for the current network.
        """
        try:
            channels = self.conf['logging']['channels'][self.name]
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

    def initVars(self):
        """
        (Re)sets an IRC object to its default state. This should be called when
        an IRC object is first created, and on every reconnection to a network.
        """
        self.sid = self.serverdata["sid"]
        self.botdata = self.conf['bot']
        self.pingfreq = self.serverdata.get('pingfreq') or 30
        self.pingtimeout = self.pingfreq * 2

        self.connected.clear()
        self.aborted.clear()
        self.pseudoclient = None
        self.lastping = time.time()

        # Internal variable to set the place the last command was called (in PM
        # or in a channel), used by fantasy command support.
        self.called_by = None

        # Intialize the server, channel, and user indexes to be populated by
        # our protocol module. For the server index, we can add ourselves right
        # now.
        self.servers = {self.sid: IrcServer(None, self.serverdata['hostname'],
                        internal=True, desc=self.serverdata.get('serverdesc')
                        or self.botdata['serverdesc'])}
        self.users = {}
        self.channels = defaultdict(IrcChannel)

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
                       '*D': 'imnpstr'}
        self.umodes = {'invisible': 'i', 'snomask': 's', 'wallops': 'w',
                       'oper': 'o',
                       '*A': '', '*B': '', '*C': 's', '*D': 'iow'}

        # This max nick length starts off as the config value, but may be
        # overwritten later by the protocol module if such information is
        # received. Note that only some IRCds (InspIRCd) give us nick length
        # during link, so it is still required that the config value be set!
        self.maxnicklen = self.serverdata['maxnicklen']

        # Defines a list of supported prefix modes.
        self.prefixmodes = {'o': '@', 'v': '+'}

        # Defines the uplink SID (to be filled in by protocol module).
        self.uplink = None
        self.start_ts = int(time.time())

        # Set up channel logging for the network
        self.logSetup()

    def connect(self):
        """
        Runs the connect loop for the IRC object. This is usually called by
        __init__ in a separate thread to allow multiple concurrent connections.
        """
        while True:
            self.initVars()
            ip = self.serverdata["ip"]
            port = self.serverdata["port"]
            checks_ok = True
            try:
                # Set the socket type (IPv6 or IPv4).
                stype = socket.AF_INET6 if self.serverdata.get("ipv6") else socket.AF_INET

                # Creat the socket.
                self.socket = socket.socket(stype)
                self.socket.setblocking(0)

                # Set the connection timeouts. Initial connection timeout is a
                # lot smaller than the timeout after we've connected; this is
                # intentional.
                self.socket.settimeout(self.pingfreq)

                # Enable SSL if set to do so. This requires a valid keyfile and
                # certfile to be present.
                self.ssl = self.serverdata.get('ssl')
                if self.ssl:
                    log.info('(%s) Attempting SSL for this connection...', self.name)
                    certfile = self.serverdata.get('ssl_certfile')
                    keyfile = self.serverdata.get('ssl_keyfile')
                    if certfile and keyfile:
                        try:
                            self.socket = ssl.wrap_socket(self.socket,
                                                          certfile=certfile,
                                                          keyfile=keyfile)
                        except OSError:
                             log.exception('(%s) Caught OSError trying to '
                                           'initialize the SSL connection; '
                                           'are "ssl_certfile" and '
                                           '"ssl_keyfile" set correctly?',
                                           self.name)
                             checks_ok = False
                    else:  # SSL was misconfigured, abort.
                        log.error('(%s) SSL certfile/keyfile was not set '
                                  'correctly, aborting... ', self.name)
                        checks_ok = False

                log.info("Connecting to network %r on %s:%s", self.name, ip, port)
                self.socket.connect((ip, port))
                self.socket.settimeout(self.pingtimeout)

                # If SSL was enabled, optionally verify the certificate
                # fingerprint for some added security. I don't bother to check
                # the entire certificate for validity, since most IRC networks
                # self-sign their certificates anyways.
                if self.ssl and checks_ok:
                    peercert = self.socket.getpeercert(binary_form=True)

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
                            log.info('(%s) Uplink\'s SSL certificate fingerprint (%s)'
                                     'is %r. You can enhance the security of your '
                                     'link by specifying this in a "ssl_fingerprint"'
                                     ' option in your server block.', self.name,
                                     hashtype, fp)

                if checks_ok:
                    # All our checks passed, get the protocol module to connect
                    # and run the listen loop.
                    self.proto.connect()
                    self.spawnMain()
                    log.info('(%s) Starting ping schedulers....', self.name)
                    self.schedulePing()
                    log.info('(%s) Server ready; listening for data.', self.name)
                    self.run()
                else:  # Configuration error :(
                    log.error('(%s) A configuration error was encountered '
                              'trying to set up this connection. Please check'
                              ' your configuration file and try again.',
                              self.name)
            except (socket.error, ProtocolError, ConnectionError) as e:
                # self.run() or the protocol module it called raised an
                # exception, meaning we've disconnected!
                log.warning('(%s) Disconnected from IRC: %s: %s',
                            self.name, type(e).__name__, str(e))

                if not self.aborted.is_set():
                    # Only start a disconnection process if one doesn't already
                    # exist.
                    self.disconnect()

            # Internal hook signifying that a network has disconnected.
            self.callHooks([None, 'PYLINK_DISCONNECT', {}])

            # If autoconnect is enabled, loop back to the start. Otherwise,
            # return and stop.
            autoconnect = self.serverdata.get('autoconnect')
            log.debug('(%s) Autoconnect delay set to %s seconds.', self.name, autoconnect)
            if autoconnect is not None and autoconnect >= 1:
                log.info('(%s) Going to auto-reconnect in %s seconds.', self.name, autoconnect)
                time.sleep(autoconnect)
            else:
                log.info('(%s) Stopping connect loop (autoconnect value %r is < 1).', self.name, autoconnect)
                return

    def disconnect(self):
        """Handle disconnects from the remote server."""

        log.debug('(%s) _disconnect: Clearing self.connected state.', self.name)
        self.connected.clear()

        log.debug('(%s) _disconnect: Setting self.aborted to True.', self.name)
        self.aborted.set()

        log.debug('(%s) Removing channel logging handlers due to disconnect.', self.name)
        while self.loghandlers:
            log.removeHandler(self.loghandlers.pop())

        try:
            log.debug('(%s) _disconnect: Shutting down and closing socket.', self.name)
            self.socket.shutdown(socket.SHUT_RDWR)
            self.socket.close()
        except:  # Socket timed out during creation; ignore
            log.exception('(%s) _disconnect: Failed to close/shutdown socket.', self.name)

        if self.pingTimer:
            log.debug('(%s) Canceling pingTimer at %s due to disconnect() call', self.name, time.time())
            self.pingTimer.cancel()

    def run(self):
        """Main IRC loop which listens for messages."""
        # Some magic below cause this to work, though anything that's
        # not encoded in UTF-8 doesn't work very well.
        buf = b""
        data = b""
        while not self.aborted.is_set():

            try:
                data = self.socket.recv(2048)
            except OSError:
                # Suppress socket read warnings from lingering recv() calls if
                # we've been told to shutdown.
                if self.aborted.is_set():
                    return
                raise

            buf += data
            if not data:
                log.warning('(%s) No data received, disconnecting!', self.name)
                return
            elif (time.time() - self.lastping) > self.pingtimeout:
                log.warning('(%s) Connection timed out.', self.name)
                return
            while b'\n' in buf:
                line, buf = buf.split(b'\n', 1)
                line = line.strip(b'\r')
                # FIXME: respect other encodings?
                line = line.decode("utf-8", "replace")
                self.runline(line)

    def runline(self, line):
        """Sends a command to the protocol module."""
        log.debug("(%s) <- %s", self.name, line)
        try:
            hook_args = self.proto.handle_events(line)
        except Exception:
            log.exception('(%s) Caught error in handle_events, disconnecting!', self.name)
            log.error('(%s) The offending line was: <- %s', self.name, line)
            self.aborted.set()
            return
        # Only call our hooks if there's data to process. Handlers that support
        # hooks will return a dict of parsed arguments, which can be passed on
        # to plugins and the like. For example, the JOIN handler will return
        # something like: {'channel': '#whatever', 'users': ['UID1', 'UID2',
        # 'UID3']}, etc.
        if hook_args is not None:
            self.callHooks(hook_args)

        return hook_args

    def callHooks(self, hook_args):
        """Calls a hook function with the given hook args."""
        numeric, command, parsed_args = hook_args
        # Always make sure TS is sent.
        if 'ts' not in parsed_args:
            parsed_args['ts'] = int(time.time())
        hook_cmd = command
        hook_map = self.proto.hook_map

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

    def send(self, data):
        """Sends raw text to the uplink server."""
        # Safeguard against newlines in input!! Otherwise, each line gets
        # treated as a separate command, which is particularly nasty.
        data = data.replace('\n', ' ')
        data = data.encode("utf-8") + b"\n"
        stripped_data = data.decode("utf-8").strip("\n")
        log.debug("(%s) -> %s", self.name, stripped_data)
        try:
            self.socket.send(data)
        except (OSError, AttributeError):
            log.debug("(%s) Dropping message %r; network isn't connected!", self.name, stripped_data)

    def schedulePing(self):
        """Schedules periodic pings in a loop."""
        self.proto.ping()

        self.pingTimer = threading.Timer(self.pingfreq, self.schedulePing)
        self.pingTimer.daemon = True
        self.pingTimer.name = 'Ping timer loop for %s' % self.name
        self.pingTimer.start()

        log.debug('(%s) Ping scheduled at %s', self.name, time.time())

    def spawnMain(self):
        """Spawns the main PyLink client."""
        nick = self.botdata.get('nick') or 'PyLink'
        ident = self.botdata.get('ident') or 'pylink'
        host = self.serverdata["hostname"]
        log.info('(%s) Connected! Spawning main client %s.', self.name, nick)
        olduserobj = self.pseudoclient
        self.pseudoclient = self.proto.spawnClient(nick, ident, host,
                                                   modes={("+o", None)},
                                                   manipulatable=True)
        for chan in self.serverdata['channels']:
            self.proto.join(self.pseudoclient.uid, chan)
        # PyLink internal hook called when spawnMain is called and the
        # contents of Irc().pseudoclient change.
        self.callHooks([self.sid, 'PYLINK_SPAWNMAIN', {'olduser': olduserobj}])

    def __repr__(self):
        return "<classes.Irc object for %r>" % self.name

    ### Utility functions
    def callCommand(self, source, text):
        """
        Calls a PyLink bot command. source is the caller's UID, and text is the
        full, unparsed text of the message.
        """
        cmd_args = text.strip().split(' ')
        cmd = cmd_args[0].lower()
        cmd_args = cmd_args[1:]
        if cmd not in world.commands:
            self.msg(self.called_by or source, 'Error: Unknown command %r.' % cmd)
            log.info('(%s) Received unknown command %r from %s', self.name, cmd, utils.getHostmask(self, source))
            return
        log.info('(%s) Calling command %r for %s', self.name, cmd, utils.getHostmask(self, source))
        for func in world.commands[cmd]:
            try:
                func(self, source, cmd_args)
            except utils.NotAuthenticatedError:
                self.msg(self.called_by or source, 'Error: You are not authorized to perform this operation.')
            except Exception as e:
                log.exception('Unhandled exception caught in command %r', cmd)
                self.msg(self.called_by or source, 'Uncaught exception in command %r: %s: %s' % (cmd, type(e).__name__, str(e)))

    def msg(self, target, text, notice=False, source=None):
        """Handy function to send messages/notices to clients. Source
        is optional, and defaults to the main PyLink client if not specified."""
        source = source or self.pseudoclient.uid
        if notice:
            self.proto.notice(source, target, text)
            cmd = 'PYLINK_SELF_NOTICE'
        else:
            self.proto.message(source, target, text)
            cmd = 'PYLINK_SELF_PRIVMSG'
        self.callHooks([source, cmd, {'target': target, 'text': text}])

    def reply(self, text, notice=False, source=None):
        """Replies to the last caller in the right context (channel or PM)."""
        self.msg(self.called_by, text, notice=notice, source=source)

    def nickToUid(self, nick):
        """Looks up the UID of a user with the given nick, if one is present."""
        nick = utils.toLower(self, nick)
        for k, v in self.users.copy().items():
            if utils.toLower(self, v.nick) == nick:
                return k

    def isInternalClient(self, numeric):
        """
        Checks whether the given numeric is a PyLink Client,
        returning the SID of the server it's on if so.
        """
        for sid in self.servers:
            if self.servers[sid].internal and numeric in self.servers[sid].users:
                return sid
        return False

    def isInternalServer(self, sid):
        """Returns whether the given SID is an internal PyLink server."""
        return (sid in self.servers and self.servers[sid].internal)

    def getServer(self, numeric):
        """Finds the SID of the server a user is on."""
        for server in self.servers:
            if numeric in self.servers[server].users:
                return server

class IrcUser():
    """PyLink IRC user class."""
    def __init__(self, nick, ts, uid, ident='null', host='null',
                 realname='PyLink dummy client', realhost='null',
                 ip='0.0.0.0', manipulatable=False):
        self.nick = nick
        self.ts = ts
        self.uid = uid
        self.ident = ident
        self.host = host
        self.realhost = realhost
        self.ip = ip
        self.realname = realname
        self.modes = set()

        self.identified = False
        self.channels = set()
        self.away = ''

        # This sets whether the client should be marked as manipulatable.
        # Plugins like bots.py's commands should take caution against
        # manipulating these "protected" clients, to prevent desyncs and such.
        # For "serious" service clients, this should always be False.
        self.manipulatable = manipulatable

    def __repr__(self):
        return 'IrcUser(%s)' % self.__dict__

class IrcServer():
    """PyLink IRC server class.

    uplink: The SID of this IrcServer instance's uplink. This is set to None
            for the main PyLink PseudoServer!
    name: The name of the server.
    internal: Whether the server is an internal PyLink PseudoServer.
    """

    def __init__(self, uplink, name, internal=False, desc="(None given)"):
        self.uplink = uplink
        self.users = set()
        self.internal = internal
        self.name = name.lower()
        self.desc = desc

    def __repr__(self):
        return 'IrcServer(%s)' % self.__dict__

class IrcChannel():
    """PyLink IRC channel class."""
    def __init__(self):
        # Initialize variables, such as the topic, user list, TS, who's opped, etc.
        self.users = set()
        self.modes = {('n', None), ('t', None)}
        self.topic = ''
        self.ts = int(time.time())
        self.prefixmodes = {'ops': set(), 'halfops': set(), 'voices': set(),
                            'owners': set(), 'admins': set()}

        # Determines whether a topic has been set here or not. Protocol modules
        # should set this.
        self.topicset = False

    def __repr__(self):
        return 'IrcChannel(%s)' % self.__dict__

    def removeuser(self, target):
        """Removes a user from a channel."""
        for s in self.prefixmodes.values():
            s.discard(target)
        self.users.discard(target)

    def deepcopy(self):
        """Returns a deep copy of the channel object."""
        return deepcopy(self)

class Protocol():
    """Base Protocol module class for PyLink."""
    def __init__(self, irc):
        self.irc = irc
        self.casemapping = 'rfc1459'
        self.hook_map = {}

    def parseArgs(self, args):
        """Parses a string of RFC1459-style arguments split into a list, where ":" may
        be used for multi-word arguments that last until the end of a line.
        """
        real_args = []
        for idx, arg in enumerate(args):
            real_args.append(arg)
            # If the argument starts with ':' and ISN'T the first argument.
            # The first argument is used for denoting the source UID/SID.
            if arg.startswith(':') and idx != 0:
                # : is used for multi-word arguments that last until the end
                # of the message. We can use list splicing here to turn them all
                # into one argument.
                # Set the last arg to a joined version of the remaining args
                arg = args[idx:]
                arg = ' '.join(arg)[1:]
                # Cut the original argument list right before the multi-word arg,
                # and then append the multi-word arg.
                real_args = args[:idx]
                real_args.append(arg)
                break
        return real_args

    def removeClient(self, numeric):
        """Internal function to remove a client from our internal state."""
        for c, v in self.irc.channels.copy().items():
            v.removeuser(numeric)
            # Clear empty non-permanent channels.
            if not (self.irc.channels[c].users or ((self.irc.cmodes.get('permanent'), None) in self.irc.channels[c].modes)):
                del self.irc.channels[c]
            assert numeric not in v.users, "IrcChannel's removeuser() is broken!"

        sid = numeric[:3]
        log.debug('Removing client %s from self.irc.users', numeric)
        del self.irc.users[numeric]
        log.debug('Removing client %s from self.irc.servers[%s].users', numeric, sid)
        self.irc.servers[sid].users.discard(numeric)

    def updateTS(self, channel, their_ts):
        """
        Compares the current TS of the channel given with the new TS, resetting
        all modes we have if the one given is older.
        """

        our_ts = self.irc.channels[channel].ts

        if their_ts < our_ts:
            # Channel timestamp was reset on burst
            log.debug('(%s) Setting channel TS of %s to %s from %s',
                      self.irc.name, channel, their_ts, our_ts)
            self.irc.channels[channel].ts = their_ts
            # When TS is reset, clear all modes we currently have
            self.irc.channels[channel].modes.clear()
            for p in self.irc.channels[channel].prefixmodes.values():
                p.clear()

### FakeIRC classes, used for test cases

class FakeIRC(Irc):
    """Fake IRC object used for unit tests."""
    def connect(self):
        self.messages = []
        self.hookargs = []
        self.hookmsgs = []
        self.socket = None
        self.initVars()
        self.spawnMain()
        self.connected = threading.Event()
        self.connected.set()

    def run(self, data):
        """Queues a message to the fake IRC server."""
        log.debug('<- ' + data)
        hook_args = self.proto.handle_events(data)
        if hook_args is not None:
            self.hookmsgs.append(hook_args)
            self.callHooks(hook_args)

    def send(self, data):
        self.messages.append(data)
        log.debug('-> ' + data)

    def takeMsgs(self):
        """Returns a list of messages sent by the protocol module since
        the last takeMsgs() call, so we can track what has been sent."""
        msgs = self.messages
        self.messages = []
        return msgs

    def takeCommands(self, msgs):
        """Returns a list of commands parsed from the output of takeMsgs()."""
        sidprefix = ':' + self.sid
        commands = []
        for m in msgs:
            args = m.split()
            if m.startswith(sidprefix):
                commands.append(args[1])
            else:
                commands.append(args[0])
        return commands

    def takeHooks(self):
        """Returns a list of hook arguments sent by the protocol module since
        the last takeHooks() call."""
        hookmsgs = self.hookmsgs
        self.hookmsgs = []
        return hookmsgs

class FakeProto(Protocol):
    """Dummy protocol module for testing purposes."""
    def handle_events(self, data):
        pass

    def connect(self):
        pass

    def spawnClient(self, nick, *args, **kwargs):
        uid = str(randint(1, 10000000000))
        ts = int(time.time())
        self.irc.users[uid] = user = IrcUser(nick, ts, uid)
        return user

    def join(self, client, channel):
        self.irc.channels[channel].users.add(client)
        self.irc.users[client].channels.add(channel)

FakeProto.Class = FakeProto
