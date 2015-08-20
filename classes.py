import threading
from random import randint

from log import log
import main
import time

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
        self.users = []
        self.internal = internal
        self.name = name.lower()
    def __repr__(self):
        return repr(self.__dict__)

class IrcChannel():
    def __init__(self):
        self.users = set()
        self.modes = set()
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

class ProtocolError(Exception):
    pass

global testconf
testconf = {'bot':
                {
                    'nick': 'PyLink',
                    'user': 'pylink',
                    'realname': 'PyLink Service Client',
                    'loglevel': 'DEBUG',
                },
            'servers':
                {'unittest':
                    {
                        'ip': '0.0.0.0',
                        'port': 7000,
                        'recvpass': "abcd",
                        'sendpass': "abcd",
                        'protocol': "null",
                        'hostname': "pylink.unittest",
                        'sid': "9PY",
                        'channels': ["#pylink"],
                    },
                },
           }

class FakeIRC(main.Irc):
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
        self.proto.handle_events(self, data)

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

    @staticmethod
    def dummyhook(irc, source, command, parsed_args):
        """Dummy function to bind to hooks."""
        irc.hookmsgs.append(parsed_args)

class FakeProto():
    """Dummy protocol module for testing purposes."""
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
