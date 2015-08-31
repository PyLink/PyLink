import threading
from random import randint
import time
import socket
import threading
import ssl
from collections import defaultdict
import hashlib

from log import log
from conf import conf
import world

### Exceptions

class ProtocolError(Exception):
    pass

### Internal classes (users, servers, channels)

class Irc():
    def initVars(self):
        self.pseudoclient = None
        self.connected = threading.Event()
        self.lastping = time.time()
        # Server, channel, and user indexes to be populated by our protocol module
        self.servers = {self.sid: IrcServer(None, self.serverdata['hostname'], internal=True)}
        self.users = {}
        self.channels = defaultdict(IrcChannel)
        # Sets flags such as whether to use halfops, etc. The default RFC1459
        # modes are implied.
        self.cmodes = {'op': 'o', 'secret': 's', 'private': 'p',
                       'noextmsg': 'n', 'moderated': 'm', 'inviteonly': 'i',
                       'topiclock': 't', 'limit': 'l', 'ban': 'b',
                       'voice': 'v', 'key': 'k',
                       # Type A, B, and C modes
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
        self.prefixmodes = {'o': '@', 'v': '+'}

        # Uplink SID (filled in by protocol module)
        self.uplink = None
        self.start_ts = int(time.time())

        # UID generators, for servers that need it
        self.uidgen = {}

    def __init__(self, netname, proto):
        # Initialize some variables
        self.name = netname.lower()
        self.conf = conf
        self.serverdata = conf['servers'][netname]
        self.sid = self.serverdata["sid"]
        self.botdata = conf['bot']
        self.proto = proto
        self.pingfreq = self.serverdata.get('pingfreq') or 30
        self.pingtimeout = self.pingfreq * 2

        self.initVars()

        if world.testing:
            # HACK: Don't thread if we're running tests.
            self.connect()
        else:
            self.connection_thread = threading.Thread(target = self.connect)
            self.connection_thread.start()
        self.pingTimer = None

    def connect(self):
        ip = self.serverdata["ip"]
        port = self.serverdata["port"]
        while True:
            self.initVars()
            checks_ok = True
            try:
                self.socket = socket.socket()
                self.socket.setblocking(0)
                # Initial connection timeout is a lot smaller than the timeout after
                # we've connected; this is intentional.
                self.socket.settimeout(self.pingfreq)
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
                    else:
                        log.error('(%s) SSL certfile/keyfile was not set '
                                  'correctly, aborting... ', self.name)
                        checks_ok = False
                log.info("Connecting to network %r on %s:%s", self.name, ip, port)
                self.socket.connect((ip, port))
                self.socket.settimeout(self.pingtimeout)

                if self.ssl and checks_ok:
                    peercert = self.socket.getpeercert(binary_form=True)
                    sha1fp = hashlib.sha1(peercert).hexdigest()
                    expected_fp = self.serverdata.get('ssl_fingerprint')
                    if expected_fp:
                        if sha1fp != expected_fp:
                            log.error('(%s) Uplink\'s SSL certificate '
                                      'fingerprint (SHA1) does not match the '
                                      'one configured: expected %r, got %r; '
                                      'disconnecting...', self.name,
                                      expected_fp, sha1fp)
                            checks_ok = False
                        else:
                            log.info('(%s) Uplink SSL certificate fingerprint '
                                     '(SHA1) verified: %r', self.name, sha1fp)
                    else:
                        log.info('(%s) Uplink\'s SSL certificate fingerprint '
                                 'is %r. You can enhance the security of your '
                                 'link by specifying this in a "ssl_fingerprint"'
                                 ' option in your server block.', self.name,
                                 sha1fp)

                if checks_ok:
                    self.proto.connect(self)
                    self.spawnMain()
                    log.info('(%s) Starting ping schedulers....', self.name)
                    self.schedulePing()
                    log.info('(%s) Server ready; listening for data.', self.name)
                    self.run()
                else:
                    log.error('(%s) A configuration error was encountered '
                              'trying to set up this connection. Please check'
                              ' your configuration file and try again.',
                              self.name)
            except (socket.error, ProtocolError, ConnectionError) as e:
                log.warning('(%s) Disconnected from IRC: %s: %s',
                            self.name, type(e).__name__, str(e))
            self.disconnect()
            autoconnect = self.serverdata.get('autoconnect')
            log.debug('(%s) Autoconnect delay set to %s seconds.', self.name, autoconnect)
            if autoconnect is not None and autoconnect >= 0:
                log.info('(%s) Going to auto-reconnect in %s seconds.', self.name, autoconnect)
                time.sleep(autoconnect)
            else:
                return

    def disconnect(self):
        log.debug('(%s) Canceling pingTimer at %s due to disconnect() call', self.name, time.time())
        self.connected.clear()
        try:
            self.socket.close()
            self.pingTimer.cancel()
        except:  # Socket timed out during creation; ignore
            pass
        # Internal hook signifying that a network has disconnected.
        self.callHooks([None, 'PYLINK_DISCONNECT', {}])

    def run(self):
        buf = b""
        data = b""
        while True:
            data = self.socket.recv(2048)
            buf += data
            if self.connected.is_set() and not data:
                log.warning('(%s) No data received and self.connected is set; disconnecting!', self.name)
                return
            elif (time.time() - self.lastping) > self.pingtimeout:
                log.warning('(%s) Connection timed out.', self.name)
                return
            while b'\n' in buf:
                line, buf = buf.split(b'\n', 1)
                line = line.strip(b'\r')
                # TODO: respect other encodings?
                line = line.decode("utf-8", "replace")
                log.debug("(%s) <- %s", self.name, line)
                hook_args = None
                try:
                    hook_args = self.proto.handle_events(self, line)
                except Exception:
                    log.exception('(%s) Caught error in handle_events, disconnecting!', self.name)
                    return
                # Only call our hooks if there's data to process. Handlers that support
                # hooks will return a dict of parsed arguments, which can be passed on
                # to plugins and the like. For example, the JOIN handler will return
                # something like: {'channel': '#whatever', 'users': ['UID1', 'UID2',
                # 'UID3']}, etc.
                if hook_args is not None:
                    self.callHooks(hook_args)

    def callHooks(self, hook_args):
        numeric, command, parsed_args = hook_args
        # Always make sure TS is sent.
        if 'ts' not in parsed_args:
            parsed_args['ts'] = int(time.time())
        hook_cmd = command
        hook_map = self.proto.hook_map
        # Handlers can return a 'parse_as' key to send their payload to a
        # different hook. An example of this is "/join 0" being interpreted
        # as leaving all channels (PART).
        if command in hook_map:
            hook_cmd = hook_map[command]
        hook_cmd = parsed_args.get('parse_as') or hook_cmd
        log.debug('Parsed args %r received from %s handler (calling hook %s)', parsed_args, command, hook_cmd)
        # Iterate over hooked functions, catching errors accordingly
        for hook_func in world.command_hooks[hook_cmd]:
            try:
                log.debug('Calling function %s', hook_func)
                hook_func(self, numeric, command, parsed_args)
            except Exception:
                # We don't want plugins to crash our servers...
                log.exception('Unhandled exception caught in %r' % hook_func)
                continue

    def send(self, data):
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
        self.proto.pingServer(self)
        self.pingTimer = threading.Timer(self.pingfreq, self.schedulePing)
        self.pingTimer.daemon = True
        self.pingTimer.start()
        log.debug('(%s) Ping scheduled at %s', self.name, time.time())

    def spawnMain(self):
        nick = self.botdata.get('nick') or 'PyLink'
        ident = self.botdata.get('ident') or 'pylink'
        host = self.serverdata["hostname"]
        log.info('(%s) Connected! Spawning main client %s.', self.name, nick)
        olduserobj = self.pseudoclient
        self.pseudoclient = self.proto.spawnClient(self, nick, ident, host, modes={("+o", None)})
        for chan in self.serverdata['channels']:
            self.proto.joinClient(self, self.pseudoclient.uid, chan)
        # PyLink internal hook called when spawnMain is called and the
        # contents of Irc().pseudoclient change.
        self.callHooks([self.sid, 'PYLINK_SPAWNMAIN', {'olduser': olduserobj}])

class IrcUser():
    def __init__(self, nick, ts, uid, ident='null', host='null',
                 realname='PyLink dummy client', realhost='null',
                 ip='0.0.0.0'):
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

    def __repr__(self):
        return repr(self.__dict__)

class IrcServer():
    """PyLink IRC Server class.

    uplink: The SID of this IrcServer instance's uplink. This is set to None
            for the main PyLink PseudoServer!
    name: The name of the server.
    internal: Whether the server is an internal PyLink PseudoServer.
    """
    def __init__(self, uplink, name, internal=False):
        self.uplink = uplink
        self.users = set()
        self.internal = internal
        self.name = name.lower()
    def __repr__(self):
        return repr(self.__dict__)

class IrcChannel():
    def __init__(self):
        self.users = set()
        self.modes = {('n', None), ('t', None)}
        self.topic = ''
        self.ts = int(time.time())
        self.topicset = False
        self.prefixmodes = {'ops': set(), 'halfops': set(), 'voices': set(),
                            'owners': set(), 'admins': set()}

    def __repr__(self):
        return repr(self.__dict__)

    def removeuser(self, target):
        for s in self.prefixmodes.values():
            s.discard(target)
        self.users.discard(target)

### FakeIRC classes, used for test cases

class FakeIRC(Irc):
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
        hook_args = self.proto.handle_events(self, data)
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

class FakeProto():
    """Dummy protocol module for testing purposes."""
    def __init__(self):
        self.hook_map = {}
        self.casemapping = 'rfc1459'
        self.__name__ = 'FakeProto'

    @staticmethod
    def handle_events(irc, data):
        pass

    @staticmethod
    def connect(irc):
        pass

    @staticmethod
    def spawnClient(irc, nick, *args, **kwargs):
        uid = randint(1, 10000000000)
        ts = int(time.time())
        irc.users[uid] = user = IrcUser(nick, ts, uid)
        return user

    @staticmethod
    def joinClient(irc, client, channel):
        irc.channels[channel].users.add(client)
        irc.users[client].channels.add(channel)
