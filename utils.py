import string
import re

global bot_commands
# This should be a mapping of command names to functions
bot_commands = {}

class TS6UIDGenerator():
    """TS6 UID Generator module, adapted from InspIRCd source
    https://github.com/inspircd/inspircd/blob/f449c6b296ab/src/server.cpp#L85-L156
    """

    def __init__(self):
        # TS6 UIDs are 6 characters in length (9 including the SID).
        # They wrap from ABCDEFGHIJKLMNOPQRSTUVWXYZ -> 1234567890 -> wrap around:
        # (e.g. AAAAAA, AAAAAB ..., AAAAA8, AAAAA9, AAAAB0)
        self.allowedchars = string.ascii_uppercase + string.digits
        self.uidchars = [self.allowedchars[-1]]*6

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

    def next_uid(self, sid):
        self.increment()
        return sid + ''.join(self.uidchars)

def msg(irc, target, text, notice=False):
    command = 'NOTICE' if notice else 'PRIVMSG'
    irc.proto._sendFromUser(irc, irc.pseudoclient.uid, '%s %s :%s' % (command, target, text))

def add_cmd(func, name=None):
    if name is None:
        name = func.__name__
    name = name.lower()
    bot_commands[name] = func

def nickToUid(irc, nick):
    for k, v in irc.users.items():
        if v.nick == nick:
            return k

# A+ regex
_nickregex = r'^[A-Za-z\|\\_\[\]\{\}\^\`][A-Z0-9a-z\-\|\\_\[\]\{\}\^\`]*$'
def isNick(s, nicklen=None):
    if nicklen and len(s) > nicklen:
        return False
    return bool(re.match(_nickregex, s))

def isChannel(s):
    return bool(s.startswith('#'))

def parseModes(args):
    """['+mitl-o', '3', 'person'] => ['+m', '+i', '+t', '-o']

    TODO: handle modes with extra arguments (mainly channel modes like +beIqlk)
    """
    modes = args[0]
    extramodes = args[1:]
    if not modes:
        return ValueError('No modes supplied in parseModes query: %r' % modes)
    res = []
    for mode in modes:
        if mode in '+-':
            prefix = mode
        else:
            res.append(prefix + mode)
    return res

def applyModes(modelist, changedmodes):
    for mode in changedmodes:
        if mode[0] == '+':
            # We're adding a mode
            modelist.append(mode)
        else:
            # We're removing a mode
            try:
                modelist.remove(mode.replace('-', '+'))
            except ValueError:
                print('Attempted to remove modes %r not in %s\'s modes' % (mode, numeric))
    return modelist
