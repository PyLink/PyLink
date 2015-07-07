import string
import re
from collections import defaultdict

from log import log

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
    return _isASCII(s) and '.' in s and not s.startswith('.')

def parseModes(irc, target, args):
    """Parses a mode string into a list of (mode, argument) tuples.
    ['+mitl-o', '3', 'person'] => [('+m', None), ('+i', None), ('+t', None), ('+l', '3'), ('-o', 'person')]
    """
    # http://www.irc.org/tech_docs/005.html
    # A = Mode that adds or removes a nick or address to a list. Always has a parameter.
    # B = Mode that changes a setting and always has a parameter.
    # C = Mode that changes a setting and only has a parameter when set.
    # D = Mode that changes a setting and never has a parameter.
    usermodes = not isChannel(target)
    modestring = args[0]
    if not modestring:
        return ValueError('No modes supplied in parseModes query: %r' % modes)
    args = args[1:]
    if usermodes:
        log.debug('(%s) Using irc.umodes for this query: %s', irc.name, irc.umodes)
        supported_modes = irc.umodes
    else:
        log.debug('(%s) Using irc.cmodes for this query: %s', irc.name, irc.cmodes)
        supported_modes = irc.cmodes
    res = []
    for mode in modestring:
        if mode in '+-':
            prefix = mode
        else:
            arg = None
            log.debug('Current mode: %s%s; args left: %s', prefix, mode, args)
            if mode in (supported_modes['*A'] + supported_modes['*B']):
                # Must have parameter.
                log.debug('Mode %s: This mode must have parameter.', mode)
                arg = args.pop(0)
            elif mode in irc.prefixmodes and not usermodes:
                # We're setting a prefix mode on someone (e.g. +o user1)
                log.debug('Mode %s: This mode is a prefix mode.', mode)
                arg = args.pop(0)
            elif prefix == '+' and mode in supported_modes['*C']:
                # Only has parameter when setting.
                log.debug('Mode %s: Only has parameter when setting.', mode)
                arg = args.pop(0)
            res.append((prefix + mode, arg))
    return res

def applyModes(irc, target, changedmodes):
    """<target> <changedmodes>
    
    Takes a list of parsed IRC modes (<changedmodes>, in the format of parseModes()), and applies them on <target>.
    <target> can be either a channel or a user; this is handled automatically."""
    usermodes = not isChannel(target)
    log.debug('(%s) Using usermodes for this query? %s', irc.name, usermodes)
    if usermodes:
        modelist = irc.users[target].modes
        supported_modes = irc.umodes
    else:
        modelist = irc.channels[target].modes
        supported_modes = irc.cmodes
    log.debug('(%s) Applying modes %r on %s (initial modelist: %s)', irc.name, changedmodes, target, modelist)
    for mode in changedmodes:
        # Chop off the +/- part that parseModes gives; it's meaningless for a mode list.
        real_mode = (mode[0][1], mode[1])
        if not usermodes:
            pmode = ''
            for m in ('owner', 'admin', 'op', 'halfop', 'voice'):
                if m in irc.cmodes and real_mode[0] == irc.cmodes[m]:
                    pmode = m+'s'
            if pmode:
                pmodelist = irc.channels[target].prefixmodes[pmode]
                log.debug('(%s) Initial prefixmodes list: %s', irc.name, irc.channels[target].prefixmodes)
                if mode[0][0] == '+':
                    pmodelist.add(mode[1])
                else:
                    pmodelist.discard(mode[1])
                log.debug('(%s) Final prefixmodes list: %s', irc.name, irc.channels[target].prefixmodes)
            if real_mode[0] in irc.prefixmodes:
                # Ignore other prefix modes such as InspIRCd's +Yy
                log.debug('(%s) Not adding mode %s to IrcChannel.modes because '
                          'it\'s a prefix mode we don\'t care about.', irc.name, str(mode))
                continue
        if mode[0][0] == '+':
            # We're adding a mode
            existing = [m for m in modelist if m[0] == real_mode[0]]
            if existing and real_mode[1] and mode[0] not in irc.cmodes['*A']:
                # The mode we're setting takes a parameter, but is not a list mode (like +beI).
                # Therefore, only one version of it can exist at a time, and we must remove
                # any old modepairs using the same letter. Otherwise, we'll get duplicates when,
                # for example, someone sets mode "+l 30" on a channel already set "+l 25".
                log.debug('(%s) Old modes for mode %r exist on %s, removing them: %s',
                          irc.name, mode, target, str(existing))
                [modelist.discard(oldmode) for oldmode in existing]
            modelist.add(real_mode)
            log.debug('(%s) Adding mode %r on %s', irc.name, mode, target)
        else:
            log.debug('(%s) Removing mode %r on %s', irc.name, mode, target)
            # We're removing a mode
            if real_mode[1] is None:
                # We're removing a mode that only takes arguments when setting.
                # Remove all mode entries that use the same letter as the one
                # we're unsetting.
                for oldmode in modelist.copy():
                    if oldmode[0] == real_mode[0]:
                        modelist.discard(oldmode)
            else:
                # Swap the - for a + and then remove it from the list.
                modelist.discard(real_mode)
    log.debug('(%s) Final modelist: %s', irc.name, modelist)

def joinModes(modes):
    modelist = ''
    args = []
    for modepair in modes:
        mode, arg = modepair
        modelist += mode
        if arg is not None:
            args.append(arg)
    s = '+%s' % modelist
    if args:
        s += ' %s' % ' '.join(args)
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
