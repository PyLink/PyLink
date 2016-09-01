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
import ssl
import hashlib
from copy import deepcopy
import inspect
import re
from collections import defaultdict, deque

try:
    import ircmatch
except ImportError:
    raise ImportError("Please install the ircmatch library and try again.")

from . import world, utils, structures, __version__
from .log import *

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
        self.name = netname
        self.conf = conf
        self.sid = None
        self.serverdata = conf['servers'][netname]
        self.botdata = conf['bot']
        self.bot_clients = {}
        self.protoname = proto.__name__.split('.')[-1]  # Remove leading pylinkirc.protocols.
        self.proto = proto.Class(self)
        self.pingfreq = self.serverdata.get('pingfreq') or 90
        self.pingtimeout = self.pingfreq * 2

        self.queue = deque()

        self.connected = threading.Event()
        self.aborted = threading.Event()

        self.pingTimer = None

        self.initVars()

        if world.testing:
            # HACK: Don't thread if we're running tests.
            self.connect()
        else:
            self.connection_thread = threading.Thread(target=self.connect,
                                                      name="Listener for %s" %
                                                      self.name)
            self.connection_thread.start()

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
        self.botdata = self.conf['bot']
        self.pingfreq = self.serverdata.get('pingfreq') or 90
        self.pingtimeout = self.pingfreq * 3

        self.connected.clear()
        self.pseudoclient = None
        self.lastping = time.time()

        self.queue.clear()

        # Internal variable to set the place and caller of the last command (in PM
        # or in a channel), used by fantasy command support.
        self.called_by = None
        self.called_in = None

        # Intialize the server, channel, and user indexes to be populated by
        # our protocol module. For the server index, we can add ourselves right
        # now.
        self.servers = {}
        self.users = {}
        self.channels = structures.KeyedDefaultdict(IrcChannel)

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
                       '*A': '', '*B': '', '*C': '', '*D': 'iosw'}

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
        self.logSetup()

    def processQueue(self):
        """Loop to process outgoing queue data."""
        while not self.aborted.is_set():
            if self.queue:  # Only process if there's data.
                data = self.queue.popleft()
                self._send(data)
            throttle_time = self.serverdata.get('throttle_time', 0.01)
            time.sleep(throttle_time)

    def connect(self):
        """
        Runs the connect loop for the IRC object. This is usually called by
        __init__ in a separate thread to allow multiple concurrent connections.
        """
        while True:
            self.aborted.clear()
            self.initVars()

            try:
                self.proto.validateServerConf()
            except AssertionError as e:
                log.exception("(%s) Configuration error: %s", self.name, e)
                return

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

                # Resolve hostnames if it's not an IP address already.
                old_ip = ip
                ip = socket.getaddrinfo(ip, port, stype)[0][-1][0]
                log.debug('(%s) Resolving address %s to %s', self.name, old_ip, ip)

                # Enable SSL if set to do so. This requires a valid keyfile and
                # certfile to be present.
                self.ssl = self.serverdata.get('ssl')
                if self.ssl:
                    log.info('(%s) Attempting SSL for this connection...', self.name)
                    certfile = self.serverdata.get('ssl_certfile')
                    keyfile = self.serverdata.get('ssl_keyfile')

                    context = ssl.SSLContext(ssl.PROTOCOL_SSLv23)
                    # Disable SSLv2 and SSLv3 - these are insecure
                    context.options |= ssl.OP_NO_SSLv2
                    context.options |= ssl.OP_NO_SSLv3

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

                    self.socket = context.wrap_socket(self.socket)

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
                            log.info('(%s) Uplink\'s SSL certificate fingerprint (%s) '
                                     'is %r. You can enhance the security of your '
                                     'link by specifying this in a "ssl_fingerprint"'
                                     ' option in your server block.', self.name,
                                     hashtype, fp)

                if checks_ok:

                    self.queue_thread = threading.Thread(name="Queue thread for %s" % self.name,
                                                         target=self.processQueue, daemon=True)
                    self.queue_thread.start()

                    self.sid = self.serverdata.get("sid")
                    # All our checks passed, get the protocol module to connect and run the listen
                    # loop. This also updates any SID values should the protocol module do so.
                    self.proto.connect()

                    log.info('(%s) Enumerating our own SID %s', self.name, self.sid)
                    host = self.hostname()

                    self.servers[self.sid] = IrcServer(None, host, internal=True,
                            desc=self.serverdata.get('serverdesc')
                            or self.botdata['serverdesc'])

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
                log.error('(%s) Disconnected from IRC: %s: %s',
                          self.name, type(e).__name__, str(e))

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

        log.debug('(%s) disconnect: Clearing self.connected state.', self.name)
        self.connected.clear()

        log.debug('(%s) Removing channel logging handlers due to disconnect.', self.name)
        while self.loghandlers:
            log.removeHandler(self.loghandlers.pop())

        try:
            log.debug('(%s) disconnect: Shutting down socket.', self.name)
            self.socket.shutdown(socket.SHUT_RDWR)
        except:  # Socket timed out during creation; ignore
            pass

        self.socket.close()

        if self.pingTimer:
            log.debug('(%s) Canceling pingTimer at %s due to disconnect() call', self.name, time.time())
            self.pingTimer.cancel()

        log.debug('(%s) disconnect: Setting self.aborted to True.', self.name)
        self.aborted.set()

        log.debug('(%s) disconnect: Clearing state via initVars().', self.name)
        self.initVars()

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
                log.error('(%s) No data received, disconnecting!', self.name)
                return
            elif (time.time() - self.lastping) > self.pingtimeout:
                log.error('(%s) Connection timed out.', self.name)
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

    def _send(self, data):
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

    def send(self, data, queue=True):
        """send() wrapper with optional queueing support."""
        if queue:
            self.queue.append(data)
        else:
            self._send(data)

    def schedulePing(self):
        """Schedules periodic pings in a loop."""
        self.proto.ping()

        self.pingTimer = threading.Timer(self.pingfreq, self.schedulePing)
        self.pingTimer.daemon = True
        self.pingTimer.name = 'Ping timer loop for %s' % self.name
        self.pingTimer.start()

        log.debug('(%s) Ping scheduled at %s', self.name, time.time())

    def __repr__(self):
        return "<classes.Irc object for %r>" % self.name

    ### General utility functions
    def callCommand(self, source, text):
        """
        Calls a PyLink bot command. source is the caller's UID, and text is the
        full, unparsed text of the message.
        """
        world.services['pylink'].call_cmd(self, source, text)

    def msg(self, target, text, notice=False, source=None, loopback=True):
        """Handy function to send messages/notices to clients. Source
        is optional, and defaults to the main PyLink client if not specified."""
        if not text:
            return

        source = source or self.pseudoclient.uid

        if notice:
            self.proto.notice(source, target, text)
            cmd = 'PYLINK_SELF_NOTICE'
        else:
            self.proto.message(source, target, text)
            cmd = 'PYLINK_SELF_PRIVMSG'

        if loopback:
            # Determines whether we should send a hook for this msg(), to relay things like services
            # replies across relay.
            self.callHooks([source, cmd, {'target': target, 'text': text}])

    def reply(self, text, notice=False, source=None, private=False, force_privmsg_in_private=False,
            loopback=True):
        """Replies to the last caller in the right context (channel or PM)."""

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

    def toLower(self, text):
        """Returns a lowercase representation of text based on the IRC object's
        casemapping (rfc1459 or ascii)."""
        if self.proto.casemapping == 'rfc1459':
            text = text.replace('{', '[')
            text = text.replace('}', ']')
            text = text.replace('|', '\\')
            text = text.replace('~', '^')
        # Encode the text as bytes first, and then lowercase it so that only ASCII characters are
        # changed. Unicode in channel names, etc. is case sensitive because IRC is just that old of
        # a protocol!!!
        return text.encode().lower().decode()

    def parseModes(self, target, args):
        """Parses a modestring list into a list of (mode, argument) tuples.
        ['+mitl-o', '3', 'person'] => [('+m', None), ('+i', None), ('+t', None), ('+l', '3'), ('-o', 'person')]
        """
        # http://www.irc.org/tech_docs/005.html
        # A = Mode that adds or removes a nick or address to a list. Always has a parameter.
        # B = Mode that changes a setting and always has a parameter.
        # C = Mode that changes a setting and only has a parameter when set.
        # D = Mode that changes a setting and never has a parameter.

        if type(args) == str:
            # If the modestring was given as a string, split it into a list.
            args = args.split()

        assert args, 'No valid modes were supplied!'
        usermodes = not utils.isChannel(target)
        prefix = ''
        modestring = args[0]
        args = args[1:]
        if usermodes:
            log.debug('(%s) Using self.umodes for this query: %s', self.name, self.umodes)

            if target not in self.users:
                log.warning('(%s) Possible desync! Mode target %s is not in the users index.', self.name, target)
                return []  # Return an empty mode list

            supported_modes = self.umodes
            oldmodes = self.users[target].modes
        else:
            log.debug('(%s) Using self.cmodes for this query: %s', self.name, self.cmodes)

            supported_modes = self.cmodes
            oldmodes = self.channels[target].modes
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
                        arg = self.nickToUid(arg) or arg
                        if arg not in self.users:  # Target doesn't exist, skip it.
                            log.debug('(%s) Skipping setting mode "%s %s"; the '
                                      'target doesn\'t seem to exist!', self.name,
                                      mode, arg)
                            continue
                    elif mode in (supported_modes['*A'] + supported_modes['*B']):
                        # Must have parameter.
                        log.debug('Mode %s: This mode must have parameter.', mode)
                        arg = args.pop(0)
                        if prefix == '-' and mode in supported_modes['*B'] and arg == '*':
                            # Charybdis allows unsetting +k without actually
                            # knowing the key by faking the argument when unsetting
                            # as a single "*".
                            # We'd need to know the real argument of +k for us to
                            # be able to unset the mode.
                            oldargs = [m[1] for m in oldmodes if m[0] == mode]
                            if oldargs:
                                # Set the arg to the old one on the channel.
                                arg = oldargs[0]
                                log.debug("Mode %s: coersing argument of '*' to %r.", mode, arg)
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

    def applyModes(self, target, changedmodes):
        """Takes a list of parsed IRC modes, and applies them on the given target.

        The target can be either a channel or a user; this is handled automatically."""
        usermodes = not utils.isChannel(target)
        log.debug('(%s) Using usermodes for this query? %s', self.name, usermodes)

        try:
            if usermodes:
                old_modelist = self.users[target].modes
                supported_modes = self.umodes
            else:
                old_modelist = self.channels[target].modes
                supported_modes = self.cmodes
        except KeyError:
            log.warning('(%s) Possible desync? Mode target %s is unknown.', self.name, target)
            return

        modelist = set(old_modelist)
        log.debug('(%s) Applying modes %r on %s (initial modelist: %s)', self.name, changedmodes, target, modelist)
        for mode in changedmodes:
            # Chop off the +/- part that parseModes gives; it's meaningless for a mode list.
            try:
                real_mode = (mode[0][1], mode[1])
            except IndexError:
                real_mode = mode

            if not usermodes:
                # We only handle +qaohv for now. Iterate over every supported mode:
                # if the IRCd supports this mode and it is the one being set, add/remove
                # the person from the corresponding prefix mode list (e.g. c.prefixmodes['op']
                # for ops).
                for pmode, pmodelist in self.channels[target].prefixmodes.items():
                    if pmode in self.cmodes and real_mode[0] == self.cmodes[pmode]:
                        log.debug('(%s) Initial prefixmodes list: %s', self.name, pmodelist)
                        if mode[0][0] == '+':
                            pmodelist.add(mode[1])
                        else:
                            pmodelist.discard(mode[1])

                        log.debug('(%s) Final prefixmodes list: %s', self.name, pmodelist)

                if real_mode[0] in self.prefixmodes:
                    # Don't add prefix modes to IrcChannel.modes; they belong in the
                    # prefixmodes mapping handled above.
                    log.debug('(%s) Not adding mode %s to IrcChannel.modes because '
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
                self.channels[target].modes = modelist
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

    def reverseModes(self, target, modes, oldobj=None):
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
        origtype = type(modes)
        # If the query is a string, we have to parse it first.
        if origtype == str:
            modes = self.parseModes(target, modes.split(" "))
        # Get the current mode list first.
        if utils.isChannel(target):
            c = oldobj or self.channels[target]
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
        log.debug('(%s) reverseModes: old/current mode list for %s is: %s', self.name,
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
                log.debug("(%s) reverseModes: skipping reversing '%s %s' with %s since we're "
                          "setting a mode that's already set.", self.name, char, arg, mpair)
                continue
            elif char[0] == '-' and (mchar, arg) not in oldmodes and mchar in possible_modes['*A']:
                # We're unsetting a prefixmode that was never set - don't set it in response!
                # Charybdis lacks verification for this server-side.
                log.debug("(%s) reverseModes: skipping reversing '%s %s' with %s since it "
                          "wasn't previously set.", self.name, char, arg, mpair)
                continue
            newmodes.append(mpair)

        log.debug('(%s) reverseModes: new modes: %s', self.name, newmodes)
        if origtype == str:
            # If the original query is a string, send it back as a string.
            return self.joinModes(newmodes)
        else:
            return set(newmodes)

    @staticmethod
    def joinModes(modes, sort=False):
        """Takes a list of (mode, arg) tuples in parseModes() format, and
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

    def version(self):
        """
        Returns a detailed version string including the PyLink daemon version,
        the protocol module in use, and the server hostname.
        """
        fullversion = 'PyLink-%s. %s :[protocol:%s]' % (__version__, self.hostname(), self.protoname)
        return fullversion

    def hostname(self):
        """
        Returns the server hostname used by PyLink on the given server.
        """
        return self.serverdata.get('hostname', world.fallback_hostname)

    ### State checking functions
    def nickToUid(self, nick):
        """Looks up the UID of a user with the given nick, if one is present."""
        nick = self.toLower(nick)
        for k, v in self.users.copy().items():
            if self.toLower(v.nick) == nick:
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

    def isManipulatableClient(self, uid):
        """
        Returns whether the given user is marked as an internal, manipulatable
        client. Usually, automatically spawned services clients should have this
        set True to prevent interactions with opers (like mode changes) from
        causing desyncs.
        """
        return self.isInternalClient(uid) and self.users[uid].manipulatable

    def isServiceBot(self, uid):
        """
        Checks whether the given UID is a registered service bot. If True,
        returns the cooresponding ServiceBot object.
        """
        if not uid:
            return False
        for sbot in world.services.values():
            if uid == sbot.uids.get(self.name):
                return sbot
        return False

    def getHostmask(self, user, realhost=False, ip=False):
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

    def getFriendlyName(self, entityid):
        """
        Returns the friendly name of a SID or UID (server name for SIDs, nick for UID)."""
        if entityid in self.servers:
            return self.servers[entityid].name
        elif entityid in self.users:
            return self.users[entityid].nick
        else:
            raise KeyError("Unknown UID/SID %s" % entityid)

    def isOper(self, uid, allowAuthed=True, allowOper=True):
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

    def checkAuthenticated(self, uid, allowAuthed=True, allowOper=True):
        """
        Checks whether the given user has operator status on PyLink, raising
        NotAuthorizedError and logging the access denial if not.
        """
        lastfunc = inspect.stack()[1][3]
        if not self.isOper(uid, allowAuthed=allowAuthed, allowOper=allowOper):
            log.warning('(%s) Access denied for %s calling %r', self.name,
                        self.getHostmask(uid), lastfunc)
            raise utils.NotAuthorizedError("You are not authenticated!")
        return True

    def matchHost(self, glob, target, ip=True, realhost=True):
        """
        Checks whether the given host, or given UID's hostmask matches the given nick!user@host
        glob.

        If the target given is a UID, and the ip or realhost options are True, this will also match
        against the target's IP address and real host, respectively.
        """
        # Get the corresponding casemapping value used by ircmatch.
        if self.proto.casemapping == 'rfc1459':
            casemapping = 0
        else:
            casemapping = 1

        # Try to convert target into a UID. If this fails, it's probably a hostname.
        target = self.nickToUid(target) or target

        # Prepare a list of hosts to check against.
        if target in self.users:
            if glob.startswith(('$', '!$')):
                # !$exttarget inverts the given match.
                invert = glob.startswith('!$')

                # Exttargets start with $. Skip regular ban matching and find the matching ban handler.
                glob = glob.lstrip('$!')
                exttargetname = glob.split(':', 1)[0]
                handler = world.exttarget_handlers.get(exttargetname)

                if handler:
                    # Handler exists. Return what it finds.
                    result = handler(self, glob, target)
                    log.debug('(%s) Got %s from exttarget %s in matchHost() glob $%s for target %s',
                              self.name, result, exttargetname, glob, target)
                    if invert:  # Anti-exttarget was specified.
                        result = not result
                    return result
                else:
                    log.debug('(%s) Unknown exttarget %s in matchHost() glob $%s', self.name,
                              exttargetname, glob)
                    return False

            hosts = {self.getHostmask(target)}

            if ip:
                hosts.add(self.getHostmask(target, ip=True))

            if realhost:
                hosts.add(self.getHostmask(target, ip=True))
        else:  # We were given a host, use that.
            hosts = [target]

        # Iterate over the hosts to match using ircmatch.
        for host in hosts:
            if ircmatch.match(casemapping, glob, host):
                return True

        return False

class IrcUser():
    """PyLink IRC user class."""
    def __init__(self, nick, ts, uid, ident='null', host='null',
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

        # Tracks PyLink identification status
        self.account = ''

        # Tracks oper type (for display only)
        self.opertype = opertype

        # Tracks external services identification status
        self.services_account = ''

        # Tracks channels the user is in
        self.channels = set()

        # Tracks away message status
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
    def __init__(self, name=None):
        # Initialize variables, such as the topic, user list, TS, who's opped, etc.
        self.users = set()
        self.modes = {('n', None), ('t', None)}
        self.topic = ''
        self.ts = int(time.time())
        self.prefixmodes = {'op': set(), 'halfop': set(), 'voice': set(),
                            'owner': set(), 'admin': set()}

        # Determines whether a topic has been set here or not. Protocol modules
        # should set this.
        self.topicset = False

        # Saves the channel name (may be useful to plugins, etc.)
        self.name = name

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

    def isVoice(self, uid):
        """Returns whether the given user is voice in the channel."""
        return uid in self.prefixmodes['voice']

    def isHalfop(self, uid):
        """Returns whether the given user is halfop in the channel."""
        return uid in self.prefixmodes['halfop']

    def isOp(self, uid):
        """Returns whether the given user is op in the channel."""
        return uid in self.prefixmodes['op']

    def isAdmin(self, uid):
        """Returns whether the given user is admin (&) in the channel."""
        return uid in self.prefixmodes['admin']

    def isOwner(self, uid):
        """Returns whether the given user is owner (~) in the channel."""
        return uid in self.prefixmodes['owner']

    def isVoicePlus(self, uid):
        """Returns whether the given user is voice or above in the channel."""
        # If the user has any prefix mode, it has to be voice or greater.
        return bool(self.getPrefixModes(uid))

    def isHalfopPlus(self, uid):
        """Returns whether the given user is halfop or above in the channel."""
        for mode in ('halfop', 'op', 'admin', 'owner'):
            if uid in self.prefixmodes[mode]:
                return True
        return False

    def isOpPlus(self, uid):
        """Returns whether the given user is op or above in the channel."""
        for mode in ('op', 'admin', 'owner'):
            if uid in self.prefixmodes[mode]:
                return True
        return False

    @staticmethod
    def sortPrefixes(key):
        """
        Implements a sorted()-compatible sorter for prefix modes, giving each one a
        numeric value.
        """
        values = {'owner': 100, 'admin': 10, 'op': 5, 'halfop': 4, 'voice': 3}

        # Default to highest value (1000) for unknown modes, should we choose to
        # support them.
        return values.get(key, 1000)

    def getPrefixModes(self, uid, prefixmodes=None):
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

        return sorted(result, key=self.sortPrefixes)

class Protocol():
    """Base Protocol module class for PyLink."""
    def __init__(self, irc):
        self.irc = irc
        self.casemapping = 'rfc1459'
        self.hook_map = {}

        # Lock for updateTS to make sure only one thread can change the channel TS at one time.
        self.ts_lock = threading.Lock()

        # Lists required conf keys for the server block.
        self.conf_keys = {'ip', 'port', 'hostname', 'sid', 'sidrange', 'protocol', 'sendpass',
                          'recvpass'}

    def validateServerConf(self):
        """Validates that the server block given contains the required keys."""
        for k in self.conf_keys:
            assert k in self.irc.serverdata, "Missing option %r in server block for network %s." % (k, self.irc.name)

        port = self.irc.serverdata['port']
        assert type(port) == int and 0 < port < 65535, "Invalid port %r for network %s" % (port, self.irc.name)

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

        sid = self.irc.getServer(numeric)
        log.debug('Removing client %s from self.irc.users', numeric)
        del self.irc.users[numeric]
        log.debug('Removing client %s from self.irc.servers[%s].users', numeric, sid)
        self.irc.servers[sid].users.discard(numeric)

    def updateTS(self, sender, channel, their_ts, modes=[]):
        """
        Merges modes of a channel given the remote TS and a list of modes.
        """

        # Okay, so the situation is that we have 6 possible TS/sender combinations:

        #                       | our TS lower | TS equal | their TS lower
        # mode origin is us     |   OVERWRITE  |   MERGE  |    IGNORE
        # mode origin is uplink |    IGNORE    |   MERGE  |   OVERWRITE

        def _clear():
            log.debug("(%s) Clearing local modes from channel %s due to TS change", self.irc.name,
                      channel)
            self.irc.channels[channel].modes.clear()
            for p in self.irc.channels[channel].prefixmodes.values():
                for user in p.copy():
                    if not self.irc.isInternalClient(user):
                        p.discard(user)

        def _apply():
            if modes:
                log.debug("(%s) Applying modes on channel %s (TS ok)", self.irc.name,
                          channel)
                self.irc.applyModes(channel, modes)

        # Use a lock so only one thread can change a channel's TS at once: this prevents race
        # conditions from desyncing the channel list.
        with self.ts_lock:
            our_ts = self.irc.channels[channel].ts
            assert type(our_ts) == int, "Wrong type for our_ts (expected int, got %s)" % type(our_ts)
            assert type(their_ts) == int, "Wrong type for their_ts (expected int, got %s)" % type(their_ts)

            # Check if we're the mode sender based on the UID / SID given.
            our_mode = self.irc.isInternalClient(sender) or self.irc.isInternalServer(sender)

            log.debug("(%s/%s) our_ts: %s; their_ts: %s; is the mode origin us? %s", self.irc.name,
                      channel, our_ts, their_ts, our_mode)

            if their_ts == our_ts:
                log.debug("(%s/%s) remote TS of %s is equal to our %s; mode query %s",
                          self.irc.name, channel, their_ts, our_ts, modes)
                # Their TS is equal to ours. Merge modes.
                _apply()

            elif (their_ts < our_ts):
                log.debug('(%s) Resetting channel TS of %s from %s to %s (remote has lower TS)',
                          self.irc.name, channel, our_ts, their_ts)
                self.irc.channels[channel].ts = their_ts

                # Remote TS was lower and we're receiving modes. Clear the modelist and apply theirs.

                _clear()
                _apply()

    def _getSid(self, sname):
        """Returns the SID of a server with the given name, if present."""
        name = sname.lower()
        for k, v in self.irc.servers.items():
            if v.name.lower() == name:
                return k
        else:
            return sname  # Fall back to given text instead of None

    def _getUid(self, target):
        """Converts a nick argument to its matching UID. This differs from irc.nickToUid()
        in that it returns the original text instead of None, if no matching nick is found."""
        target = self.irc.nickToUid(target) or target
        return target

    def parsePrefixedArgs(self, args):
        """Similar to parseArgs(), but stripping leading colons from the first argument
        of a line (usually the sender field)."""
        args = self.parseArgs(args)
        args[0] = args[0].split(':', 1)[1]
        return args

    def _squit(self, numeric, command, args):
        """Handles incoming SQUITs."""

        split_server = self._getSid(args[0])

        # Normally we'd only need to check for our SID as the SQUIT target, but Nefarious
        # actually uses the uplink server as the SQUIT target.
        # <- ABAAE SQ nefarious.midnight.vpn 0 :test
        if split_server in (self.irc.sid, self.irc.uplink):
            raise ProtocolError('SQUIT received: (reason: %s)' % args[-1])

        affected_users = []
        affected_nicks = defaultdict(list)
        log.debug('(%s) Splitting server %s (reason: %s)', self.irc.name, split_server, args[-1])

        if split_server not in self.irc.servers:
            log.warning("(%s) Tried to split a server (%s) that didn't exist!", self.irc.name, split_server)
            return

        # Prevent RuntimeError: dictionary changed size during iteration
        old_servers = self.irc.servers.copy()
        old_channels = self.irc.channels.copy()

        # Cycle through our list of servers. If any server's uplink is the one that is being SQUIT,
        # remove them and all their users too.
        for sid, data in old_servers.items():
            if data.uplink == split_server:
                log.debug('Server %s also hosts server %s, removing those users too...', split_server, sid)
                # Recursively run SQUIT on any other hubs this server may have been connected to.
                args = self._squit(sid, 'SQUIT', [sid, "0",
                                   "PyLink: Automatically splitting leaf servers of %s" % sid])
                affected_users += args['users']

        for user in self.irc.servers[split_server].users.copy():
            affected_users.append(user)
            nick = self.irc.users[user].nick

            # Nicks affected is channel specific for SQUIT:. This makes Clientbot's SQUIT relaying
            # much easier to implement.
            for name, cdata in old_channels.items():
                if user in cdata.users:
                    affected_nicks[name].append(nick)

            log.debug('Removing client %s (%s)', user, nick)
            self.removeClient(user)

        serverdata = self.irc.servers[split_server]
        sname = serverdata.name
        uplink = serverdata.uplink

        del self.irc.servers[split_server]
        log.debug('(%s) Netsplit affected users: %s', self.irc.name, affected_users)

        return {'target': split_server, 'users': affected_users, 'name': sname,
                'uplink': uplink, 'nicks': affected_nicks, 'serverdata': serverdata,
                'channeldata': old_channels}

    def parseCapabilities(self, args):
        """
        Parses a string of capabilities in the 005 / RPL_ISUPPORT format.
        """

        if type(args) == str:
            args = args.split(' ')

        caps = {}
        for cap in args:
            try:
                # Try to split it as a KEY=VALUE pair.
                key, value = cap.split('=', 1)
            except ValueError:
                key = cap
                value = ''
            caps[key] = value

        return caps

    @staticmethod
    def parsePrefixes(args):
        """
        Separates prefixes field like "(qaohv)~&@%+" into a dict mapping mode characters to mode
        prefixes.
        """
        prefixsearch = re.search(r'\(([A-Za-z]+)\)(.*)', args)
        return dict(zip(prefixsearch.group(1), prefixsearch.group(2)))

    def handle_error(self, numeric, command, args):
        """Handles ERROR messages - these mean that our uplink has disconnected us!"""
        self.irc.connected.clear()
        raise ProtocolError('Received an ERROR, disconnecting!')
