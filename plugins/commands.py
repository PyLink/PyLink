# commands.py: base PyLink commands
from time import ctime

from pylinkirc import utils, __version__, world, real_version
from pylinkirc.log import log
from pylinkirc.coremods import permissions

from pylinkirc.coremods.login import pwd_context

default_permissions = {"*!*@*": ['commands.status', 'commands.showuser', 'commands.showchan']}

def main(irc=None):
    """Commands plugin main function, called on plugin load."""
    # Register our permissions.
    permissions.addDefaultPermissions(default_permissions)

def die(irc=None):
    """Commands plugin die function, called on plugin unload."""
    permissions.removeDefaultPermissions(default_permissions)

@utils.add_cmd
def status(irc, source, args):
    """takes no arguments.

    Returns your current PyLink login status."""
    permissions.checkPermissions(irc, source, ['commands.status'])
    identified = irc.users[source].account
    if identified:
        irc.reply('You are identified as \x02%s\x02.' % identified)
    else:
        irc.reply('You are not identified as anyone.')
    irc.reply('Operator access: \x02%s\x02' % bool(irc.isOper(source)))

_none = '\x1D(none)\x1D'
@utils.add_cmd
def showuser(irc, source, args):
    """<user>

    Shows information about <user>."""
    permissions.checkPermissions(irc, source, ['commands.showuser'])
    try:
        target = args[0]
    except IndexError:
        irc.error("Not enough arguments. Needs 1: nick.")
        return
    u = irc.nickToUid(target) or target
    # Only show private info if the person is calling 'showuser' on themselves,
    # or is an oper.
    verbose = irc.isOper(source) or u == source
    if u not in irc.users:
        irc.error('Unknown user %r.' % target)
        return

    f = lambda s: irc.reply(s, private=True)

    userobj = irc.users[u]
    f('Showing information on user \x02%s\x02 (%s@%s): %s' % (userobj.nick, userobj.ident,
      userobj.host, userobj.realname))

    sid = irc.getServer(u)
    serverobj = irc.servers[sid]
    ts = userobj.ts

    # Show connected server & nick TS
    f('\x02Home server\x02: %s (%s); \x02Nick TS:\x02 %s (%s)' % \
      (serverobj.name, sid, ctime(float(ts)), ts))

    if verbose:  # Oper only data: user modes, channels on, account info, etc.

        f('\x02User modes\x02: %s' % irc.joinModes(userobj.modes, sort=True))
        f('\x02Protocol UID\x02: %s; \x02Real host\x02: %s; \x02IP\x02: %s' % \
          (u, userobj.realhost, userobj.ip))
        channels = sorted(userobj.channels)
        f('\x02Channels\x02: %s' % (' '.join(channels) or _none))
        f('\x02PyLink identification\x02: %s; \x02Services account\x02: %s; \x02Away status\x02: %s' % \
          ((userobj.account or _none), (userobj.services_account or _none), userobj.away or _none))


@utils.add_cmd
def showchan(irc, source, args):
    """<channel>

    Shows information about <channel>."""
    permissions.checkPermissions(irc, source, ['commands.showchan'])
    try:
        channel = irc.toLower(args[0])
    except IndexError:
        irc.error("Not enough arguments. Needs 1: channel.")
        return
    if channel not in irc.channels:
        irc.error('Unknown channel %r.' % channel)
        return

    f = lambda s: irc.reply(s, private=True)

    c = irc.channels[channel]
    # Only show verbose info if caller is oper or is in the target channel.
    verbose = source in c.users or irc.isOper(source)
    secret = ('s', None) in c.modes
    if secret and not verbose:
        # Hide secret channels from normal users.
        irc.error('Unknown channel %r.' % channel)
        return

    nicks = [irc.users[u].nick for u in c.users]

    f('Information on channel \x02%s\x02:' % channel)
    if c.topic:
        f('\x02Channel topic\x02: %s' % c.topic)

    # Mark TS values as untrusted on Clientbot and others (where TS is read-only or not trackable)
    f('\x02Channel creation time\x02: %s (%s)%s' % (ctime(c.ts), c.ts,
                                                    ' [UNTRUSTED]' if not irc.proto.hasCap('has-ts') else ''))

    # Show only modes that aren't list-style modes.
    modes = irc.joinModes([m for m in c.modes if m[0] not in irc.cmodes['*A']], sort=True)
    f('\x02Channel modes\x02: %s' % modes)
    if verbose:
        nicklist = []
        # Iterate over the user list, sorted by nick.
        for user, nick in sorted(zip(c.users, nicks),
                                 key=lambda userpair: userpair[1].lower()):
            for pmode in c.getPrefixModes(user):
                # Show prefix modes in order from highest to lowest.
                nick = irc.prefixmodes.get(irc.cmodes.get(pmode, ''), '') + nick
            nicklist.append(nick)

        while nicklist[:20]:  # 20 nicks per line to prevent message cutoff.
            f('\x02User list\x02: %s' % ' '.join(nicklist[:20]))
            nicklist = nicklist[20:]

@utils.add_cmd
def version(irc, source, args):
    """takes no arguments.

    Returns the version of the currently running PyLink instance."""
    irc.reply("PyLink version \x02%s\x02 (in VCS: %s), released under the Mozilla Public License version 2.0." % (__version__, real_version))
    irc.reply("The source of this program is available at \x02%s\x02." % world.source)

@utils.add_cmd
def echo(irc, source, args):
    """<text>

    Echoes the text given."""
    permissions.checkPermissions(irc, source, ['commands.echo'])
    irc.reply(' '.join(args))

def _check_logout_access(irc, source, target, perms):
    """
    Checks whether the source UID has access to log out the target UID.
    This returns True if the source user has a permission specified,
    or if the source and target are both logged in and have the same account.
    """
    assert source in irc.users, "Unknown source user"
    assert target in irc.users, "Unknown target user"
    try:
        permissions.checkPermissions(irc, source, perms)
    except utils.NotAuthorizedError:
        if irc.users[source].account and (irc.users[source].account == irc.users[target].account):
            return True
        else:
            raise
    else:
        return True

@utils.add_cmd
def logout(irc, source, args):
    """[<other nick/UID>]

    Logs your account out of PyLink. If you have the 'commands.logout.force' permission, or are
    attempting to log out yourself, you can also specify a nick to force a logout for."""

    try:
        othernick = args[0]
    except IndexError:  # No user specified
        if irc.users[source].account:
            irc.users[source].account = ''
        else:
            irc.error("You are not logged in!")
            return
    else:
        otheruid = irc.nickToUid(othernick)
        if not otheruid:
            irc.error("Unknown user %s." % othernick)
            return
        else:
            _check_logout_access(irc, source, otheruid, ['commands.logout.force'])
            if irc.users[otheruid].account:
                irc.users[otheruid].account = ''
            else:
                irc.error("%s is not logged in." % othernick)
                return

    irc.reply("Done.")

loglevels = {'DEBUG': 10, 'INFO': 20, 'WARNING': 30, 'ERROR': 40, 'CRITICAL': 50}
@utils.add_cmd
def loglevel(irc, source, args):
    """<level>

    Sets the log level to the given <level>. <level> must be either DEBUG, INFO, WARNING, ERROR, or CRITICAL.
    If no log level is given, shows the current one."""
    permissions.checkPermissions(irc, source, ['commands.loglevel'])
    try:
        level = args[0].upper()
        try:
            loglevel = loglevels[level]
        except KeyError:
            irc.error('Unknown log level "%s".' % level)
            return
        else:
            world.console_handler.setLevel(loglevel)
            irc.reply("Done.")
    except IndexError:
        irc.reply(world.console_handler.level)

@utils.add_cmd
def mkpasswd(irc, source, args):
    """<password>
    Hashes a password for use in the configuration file."""
    # TODO: restrict to only certain users?
    try:
        password = args[0]
    except IndexError:
        irc.error("Not enough arguments. (Needs 1, password)")
        return
    if not password:
        irc.error("Password cannot be empty.")
        return

    if not pwd_context:
        irc.error("Password encryption is not available (missing passlib).")
        return

    hashed_pass = pwd_context.encrypt(password)
    irc.reply(hashed_pass, private=True)
