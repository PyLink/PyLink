class IrcUser():
    def __init__(self, nick, ts, uid, ident='null', host='null',
                 realname='PyLink dummy client', realhost='null',
                 ip='0.0.0.0', modes=set()):
        self.nick = nick
        self.ts = ts
        self.uid = uid
        self.ident = ident
        self.host = host
        self.realhost = realhost
        self.ip = ip
        self.realname = realname
        self.modes = modes

        self.identified = False

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
        '''
        self.ops = []
        self.halfops = []
        self.voices = []
        '''
    def __repr__(self):
        return repr(self.__dict__)
