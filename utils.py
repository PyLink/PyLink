import string
import re
import inspect

from log import log
import world

# This is separate from classes.py to prevent import loops.
class NotAuthenticatedError(Exception):
    pass

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

class TS6SIDGenerator():
    """<query>

    TS6 SID Generator. <query> is a 3 character string with any combination of
    uppercase letters, digits, and #'s. <query> must contain at least one #,
    which are used by the generator as a wildcard. On every next_sid() call,
    the first available wildcard character (from the right) will be
    incremented to generate the next SID.

    When there are no more available SIDs left (SIDs are not reused, only
    incremented), RuntimeError is raised.

    Example queries:
        "1#A" would give: 10A, 11A, 12A ... 19A, 1AA, 1BA ... 1ZA (36 total results)
        "#BQ" would give: 0BQ, 1BQ, 2BQ ... 9BQ (10 total results)
        "6##" would give: 600, 601, 602, ... 60Y, 60Z, 610, 611, ... 6ZZ (1296 total results)
    """

    def __init__(self, query):
        self.query = list(query)
        self.iters = self.query.copy()
        self.output = self.query.copy()
        self.allowedchars = {}
        qlen = len(query)
        assert qlen == 3, 'Incorrect length for a SID (must be 3, got %s)' % qlen
        assert '#' in query, "Must be at least one wildcard (#) in query"
        for idx, char in enumerate(query):
            assert char in (string.digits+string.ascii_uppercase+"#"), \
                "Invalid character %r found." % char
            if char == '#':
                if idx == 0:  # The first char be only digits
                    self.allowedchars[idx] = string.digits
                else:
                    self.allowedchars[idx] = string.digits+string.ascii_uppercase
                self.iters[idx] = iter(self.allowedchars[idx])
                self.output[idx] = self.allowedchars[idx][0]
                next(self.iters[idx])


    def increment(self, pos=2):
        if pos < 0:
            # Oh no, we've wrapped back to the start!
            raise RuntimeError('No more available SIDs!')
        it = self.iters[pos]
        try:
            self.output[pos] = next(it)
        except TypeError:  # This position is not an iterator, but a string.
            self.increment(pos-1)
        except StopIteration:
            self.output[pos] = self.allowedchars[pos][0]
            self.iters[pos] = iter(self.allowedchars[pos])
            next(self.iters[pos])
            self.increment(pos-1)

    def next_sid(self):
        sid = ''.join(self.output)
        self.increment()
        return sid

def msg(irc, target, text, notice=False):
    if notice:
        irc.proto.noticeClient(irc, irc.pseudoclient.uid, target, text)
    else:
        irc.proto.messageClient(irc, irc.pseudoclient.uid, target, text)

def add_cmd(func, name=None):
    if name is None:
        name = func.__name__
    name = name.lower()
    world.bot_commands[name].append(func)

def add_hook(func, command):
    """Add a hook <func> for command <command>."""
    command = command.upper()
    world.command_hooks[command].append(func)

def toLower(irc, text):
    """<irc object> <text>

    Returns a lowercase representation of <text> based on <irc object>'s
    casemapping (rfc1459 vs ascii)."""
    if irc.proto.casemapping == 'rfc1459':
        text = text.replace('{', '[')
        text = text.replace('}', ']')
        text = text.replace('|', '\\')
        text = text.replace('~', '^')
    return text.lower()

def nickToUid(irc, nick):
    """<irc object> <nick>

    Returns the UID of a user named <nick>, if present."""
    nick = toLower(irc, nick)
    for k, v in irc.users.items():
        if toLower(irc, v.nick) == nick:
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
    """Parses a modestring list into a list of (mode, argument) tuples.
    ['+mitl-o', '3', 'person'] => [('+m', None), ('+i', None), ('+t', None), ('+l', '3'), ('-o', 'person')]
    """
    # http://www.irc.org/tech_docs/005.html
    # A = Mode that adds or removes a nick or address to a list. Always has a parameter.
    # B = Mode that changes a setting and always has a parameter.
    # C = Mode that changes a setting and only has a parameter when set.
    # D = Mode that changes a setting and never has a parameter.
    usermodes = not isChannel(target)
    prefix = ''
    modestring = args[0]
    if not modestring:
        return ValueError('No modes supplied in parseModes query: %r' % modes)
    args = args[1:]
    if usermodes:
        log.debug('(%s) Using irc.umodes for this query: %s', irc.name, irc.umodes)
        supported_modes = irc.umodes
        oldmodes = irc.users[target].modes
    else:
        log.debug('(%s) Using irc.cmodes for this query: %s', irc.name, irc.cmodes)
        supported_modes = irc.cmodes
        oldmodes = irc.channels[target].modes
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
                if mode in (supported_modes['*A'] + supported_modes['*B']):
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
                elif mode in irc.prefixmodes and not usermodes:
                    # We're setting a prefix mode on someone (e.g. +o user1)
                    log.debug('Mode %s: This mode is a prefix mode.', mode)
                    arg = args.pop(0)
                elif prefix == '+' and mode in supported_modes['*C']:
                    # Only has parameter when setting.
                    log.debug('Mode %s: Only has parameter when setting.', mode)
                    arg = args.pop(0)
            except IndexError:
                log.warning('(%s/%s) Error while parsing mode %r: mode requires an '
                            'argument but none was found. (modestring: %r)',
                            irc.name, target, mode, modestring)
                continue  # Skip this mode; don't error out completely.
            res.append((prefix + mode, arg))
    return res

def applyModes(irc, target, changedmodes):
    """<target> <changedmodes>

    Takes a list of parsed IRC modes (<changedmodes>, in the format of parseModes()), and applies them on <target>.
    <target> can be either a channel or a user; this is handled automatically."""
    usermodes = not isChannel(target)
    log.debug('(%s) Using usermodes for this query? %s', irc.name, usermodes)
    if usermodes:
        old_modelist = irc.users[target].modes
        supported_modes = irc.umodes
    else:
        old_modelist = irc.channels[target].modes
        supported_modes = irc.cmodes
    modelist = set(old_modelist)
    log.debug('(%s) Applying modes %r on %s (initial modelist: %s)', irc.name, changedmodes, target, modelist)
    for mode in changedmodes:
        # Chop off the +/- part that parseModes gives; it's meaningless for a mode list.
        try:
            real_mode = (mode[0][1], mode[1])
        except IndexError:
            real_mode = mode
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
                irc.channels[target].prefixmodes[pmode] = pmodelist
                log.debug('(%s) Final prefixmodes list: %s', irc.name, irc.channels[target].prefixmodes)
            if real_mode[0] in irc.prefixmodes:
                # Ignore other prefix modes such as InspIRCd's +Yy
                log.debug('(%s) Not adding mode %s to IrcChannel.modes because '
                          'it\'s a prefix mode we don\'t care about.', irc.name, str(mode))
                continue
        if mode[0][0] == '+':
            # We're adding a mode
            existing = [m for m in modelist if m[0] == real_mode[0] and m[1] != real_mode[1]]
            if existing and real_mode[1] and real_mode[0] not in irc.cmodes['*A']:
                # The mode we're setting takes a parameter, but is not a list mode (like +beI).
                # Therefore, only one version of it can exist at a time, and we must remove
                # any old modepairs using the same letter. Otherwise, we'll get duplicates when,
                # for example, someone sets mode "+l 30" on a channel already set "+l 25".
                log.debug('(%s) Old modes for mode %r exist on %s, removing them: %s',
                          irc.name, real_mode, target, str(existing))
                [modelist.discard(oldmode) for oldmode in existing]
            modelist.add(real_mode)
            log.debug('(%s) Adding mode %r on %s', irc.name, real_mode, target)
        else:
            log.debug('(%s) Removing mode %r on %s', irc.name, real_mode, target)
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
    if usermodes:
        irc.users[target].modes = modelist
    else:
        irc.channels[target].modes = modelist

def joinModes(modes):
    """<mode list>

    Takes a list of (mode, arg) tuples in parseModes() format, and
    joins them into a string. See testJoinModes in tests/test_utils.py
    for some examples."""
    prefix = '+'  # Assume we're adding modes unless told otherwise
    modelist = ''
    args = []
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

def reverseModes(irc, target, modes):
    """<mode string/mode list>

    Reverses/Inverts the mode string or mode list given.

    "+nt-lk" => "-nt+lk"
    "nt-k" => "-nt+k"
    [('+m', None), ('+t', None), ('+l', '3'), ('-o', 'person')] =>
        [('-m', None), ('-t', None), ('-l', '3'), ('+o', 'person')]
    [('s', None), ('+n', None)] => [('-s', None), ('-n', None)]
    """
    origtype = type(modes)
    # Operate on joined modestrings only; it's easier.
    if origtype != str:
        modes = joinModes(modes)
    # Swap the +'s and -'s by replacing one with a dummy character, and then changing it back.
    assert '\x00' not in modes, 'NUL cannot be in the mode list (it is a reserved character)!'
    if not modes.startswith(('+', '-')):
        modes = '+' + modes
    newmodes = modes.replace('+', '\x00')
    newmodes = newmodes.replace('-', '+')
    newmodes = newmodes.replace('\x00', '-')
    if origtype != str:
        # If the original query isn't a string, send back the parseModes() output.
        return parseModes(irc, target, newmodes.split(" "))
    else:
        return newmodes

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

def isOper(irc, uid, allowAuthed=True, allowOper=True):
    """<irc object> <UID>

    Returns whether <UID> has operator status on PyLink. This can be achieved
    by either identifying to PyLink as admin (if allowAuthed is True),
    or having user mode +o set (if allowOper is True). At least one of
    allowAuthed or allowOper must be True for this to give any meaningful
    results.
    """
    if uid in irc.users:
        if allowOper and ("o", None) in irc.users[uid].modes:
            return True
        elif allowAuthed and irc.users[uid].identified:
            return True
    return False

def checkAuthenticated(irc, uid, allowAuthed=True, allowOper=True):
    """<irc object> <UID>

    Checks whether user <UID> has operator status on PyLink, raising
    NotAuthenticatedError and logging the access denial if not."""
    lastfunc = inspect.stack()[1][3]
    if not isOper(irc, uid, allowAuthed=allowAuthed, allowOper=allowOper):
        log.warning('(%s) Access denied for %s calling %r', irc.name,
                    getHostmask(irc, uid), lastfunc)
        raise NotAuthenticatedError("You are not authenticated!")
    return True

def getHostmask(irc, user):
    """<irc object> <UID>

    Gets the hostmask of user <UID>, if present."""
    userobj = irc.users.get(user)
    if userobj is None:
        return '<user object not found>'
    try:
        nick = userobj.nick
    except AttributeError:
        nick = '<unknown nick>'
    try:
        ident = userobj.ident
    except AttributeError:
        ident = '<unknown ident>'
    try:
        host = userobj.host
    except AttributeError:
        host = '<unknown host>'
    return '%s!%s@%s' % (nick, ident, host)

hostmaskRe = re.compile(r'^\S+!\S+@\S+$')
def isHostmask(text):
    """Returns whether <text> is a valid hostmask."""
    return bool(hostmaskRe.match(text))
