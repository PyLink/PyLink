import string
import re

global bot_commands
# This should be a mapping of command names to functions
bot_commands = {}

# From http://www.inspircd.org/wiki/Modules/spanningtree/UUIDs.html
chars = string.digits + string.ascii_uppercase
iters = [iter(chars) for _ in range(6)]
a = [next(i) for i in iters]

def next_uid(sid, level=-1):
    try:
        a[level] = next(iters[level])
        return sid + ''.join(a)
    except StopIteration:
        return UID(level-1)

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
