import string
import re
from collections import defaultdict

global bot_commands, command_hooks
# This should be a mapping of command names to functions
bot_commands = {}
command_hooks = defaultdict(list)

class TS6UIDGenerator():
    """TS6 UID Generator module, adapted from InspIRCd source
    https://github.com/inspircd/inspircd/blob/f449c6b296ab/src/server.cpp#L85-L156
    """

    def __init__(self, sid):
        # TS6 UIDs are 6 characters in length (9 including the SID).
        # They wrap from ABCDEFGHIJKLMNOPQRSTUVWXYZ -> 0123456789 -> wrap around:
        # (e.g. AAAAAA, AAAAAB ..., AAAAA8, AAAAA9, AAAABA)
        self.allowedchars = string.ascii_uppercase + string.digits
        self.uidchars = [self.allowedchars[0]]*6
        self.sid = sid

    def increment(self, pos=5):
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
        uid = self.sid + ''.join(self.uidchars)
        self.increment()
        return uid

def msg(irc, target, text, notice=False):
    command = 'NOTICE' if notice else 'PRIVMSG'
    irc.proto._sendFromUser(irc, irc.pseudoclient.uid, '%s %s :%s' % (command, target, text))

def add_cmd(func, name=None):
    if name is None:
        name = func.__name__
    name = name.lower()
    bot_commands[name] = func

def add_hook(func, command):
    """Add a hook <func> for command <command>."""
    command = command.upper()
    command_hooks[command].append(func)

def nickToUid(irc, nick):
    for k, v in irc.users.items():
        if v.nick == nick:
            return k

def clientToServer(irc, numeric):
    """<irc object> <numeric>

    Finds the server SID of user <numeric> and returns it."""
    for server in irc.servers:
        if numeric in irc.servers[server].users:
            return server

# A+ regex
_nickregex = r'^[A-Za-z\|\\_\[\]\{\}\^\`][A-Z0-9a-z\-\|\\_\[\]\{\}\^\`]*$'
def isNick(s, nicklen=None):
    if nicklen and len(s) > nicklen:
        return False
    return bool(re.match(_nickregex, s))

def isChannel(s):
    return s.startswith('#')

def _isASCII(s):
    chars = string.ascii_letters + string.digits + string.punctuation
    return all(char in chars for char in s)

def isServerName(s):
    return _isASCII(s) and '.' in s and not s.startswith('.') \
        and not s.endswith('.')

def parseModes(irc, args, usermodes=False):
    """Parses a mode string into a list of (mode, argument) tuples.
    ['+mitl-o', '3', 'person'] => [('+m', None), ('+i', None), ('+t', None), ('+l', '3'), ('-o', 'person')]
    """
    # http://www.irc.org/tech_docs/005.html
    # A = Mode that adds or removes a nick or address to a list. Always has a parameter. 
    # B = Mode that changes a setting and always has a parameter. 
    # C = Mode that changes a setting and only has a parameter when set.
    # D = Mode that changes a setting and never has a parameter.
    print(args)
    modestring = args[0]
    if not modestring:
        return ValueError('No modes supplied in parseModes query: %r' % modes)
    args = args[1:]
    if usermodes:
        supported_modes = irc.umodes 
    else:
        supported_modes = irc.cmodes
    print('supported modes: %s' % supported_modes)
    res = []
    for x in ('A', 'B', 'C', 'D'):
        print('%s modes: %s' % (x, supported_modes['*'+x]))
    for mode in modestring:
        if mode in '+-':
            prefix = mode
        else:
            arg = None
            if mode in (supported_modes['*A'] + supported_modes['*B']):
                # Must have parameter.
                print('%s: Must have parameter.' % mode)
                arg = args.pop(0)
            elif mode in irc.prefixmodes and not usermodes:
                # We're setting a prefix mode on someone (e.g. +o user1)
                print('%s: prefixmode.' % mode)
                # TODO: handle this properly (issue #16).
                continue
            elif prefix == '+' and mode in supported_modes['*C']:
                # Only has parameter when setting.
                print('%s: Only has parameter when setting.' % mode)
                arg = args.pop(0)
            res.append((prefix + mode, arg))
    return res

def applyModes(modelist, changedmodes):
    modelist = modelist.copy()
    print('Initial modelist: %s' % modelist)
    print('Changedmodes: %r' % changedmodes)
    for mode in changedmodes:
        if mode[0][0] == '+':
            # We're adding a mode
            modelist.add(mode)
            print('Adding mode %r' % str(mode))
        else:
            # We're removing a mode
            mode[0] = mode[0].replace('-', '+')
            modelist.discard(mode)
            print('Removing mode %r' % str(mode))
    print('Final modelist: %s' % modelist)
    return modelist

def joinModes(modes):
    modelist = ''
    args = []
    for modepair in modes:
        mode, arg = modepair
        modelist += mode[1]
        if arg is not None:
            args.append(arg)
    s = '+%s %s' % (modelist, ' '.join(args))
    return s

def isInternalClient(irc, numeric):
    """<irc object> <client numeric>

    Checks whether <client numeric> is a PyLink PseudoClient,
    returning the SID of the PseudoClient's server if True.
    """
    for sid in irc.servers:
        if irc.servers[sid].internal and numeric in irc.servers[sid].users:
            return sid

def isInternalServer(irc, sid):
    """<irc object> <sid>

    Returns whether <sid> is an internal PyLink PseudoServer.
    """
    return (sid in irc.servers and irc.servers[sid].internal)
