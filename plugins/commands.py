# commands.py: base PyLink commands
import sys
import time

from pylinkirc import __version__, conf, real_version, utils, world
from pylinkirc.coremods import permissions
from pylinkirc.coremods.login import pwd_context

default_permissions = {"*!*@*": ['commands.status', 'commands.showuser', 'commands.showchan', 'commands.shownet']}

def main(irc=None):
    """Commands plugin main function, called on plugin load."""
    # Register our permissions.
    permissions.add_default_permissions(default_permissions)

def die(irc=None):
    """Commands plugin die function, called on plugin unload."""
    permissions.remove_default_permissions(default_permissions)

@utils.add_cmd
def status(irc, source, args):
    """takes no arguments.

    Returns your current PyLink login status."""
    permissions.check_permissions(irc, source, ['commands.status'])
    identified = irc.users[source].account
    if identified:
        irc.reply('You are identified as \x02%s\x02.' % identified)
    else:
        irc.reply('You are not identified as anyone.')
    irc.reply('Operator access: \x02%s\x02' % bool(irc.is_oper(source)))

_none = '\x1D(none)\x1D'
_notavail = '\x1DN/A\x1D'
def _do_showuser(irc, source, u):
    """Helper function for showuser."""
    # Some protocol modules store UIDs as ints; make sure we check for that.
    try:
        int_u = int(u)
    except ValueError:
        pass
    else:
        if int_u in irc.users:
            u = int_u

    # Only show private info if the person is calling 'showuser' on themselves,
    # or is an oper.
    verbose = irc.is_oper(source) or u == source

    if u not in irc.users:
        irc.error('Unknown user %r.' % u)
        return

    f = lambda s: irc.reply('  ' + s, private=True)

    userobj = irc.users[u]
    irc.reply('Showing information on user \x02%s\x02 (%s@%s): %s' % (userobj.nick, userobj.ident,
               userobj.host, userobj.realname), private=True)

    sid = irc.get_server(u)
    serverobj = irc.servers[sid]
    ts = userobj.ts

    # Show connected server & nick TS if available
    serverinfo = '%s[%s]' % (serverobj.name, sid) \
        if irc.has_cap('can-track-servers') else None
    tsinfo = '%s [UTC] (%s)' % (time.asctime(time.gmtime(int(ts))), ts) \
        if irc.has_cap('has-ts') else None
    if tsinfo or serverinfo:
        f('\x02Home server\x02: %s; \x02Nick TS:\x02 %s' % (serverinfo or _notavail, tsinfo or _notavail))

    if verbose:  # Oper/self only data: user modes, channels in, account info, etc.
        f('\x02Protocol UID\x02: %s; \x02Real host\x02: %s; \x02IP\x02: %s' % \
          (u, userobj.realhost or _notavail, userobj.ip))
        channels = sorted(userobj.channels)
        f('\x02Channels\x02: %s' % (' '.join(map(str, channels)) or _none))
        f('\x02PyLink identification\x02: %s; \x02Services account\x02: %s; \x02Away status\x02: %s' % \
          ((userobj.account or _none), (userobj.services_account or _none), userobj.away or _none))
        f('\x02User modes\x02: %s' % irc.join_modes(userobj.modes, sort=True))

    # Show relay user data if available
    relay = world.plugins.get('relay')
    if relay:
        try:
            userpair = relay.get_orig_user(irc, u) or (irc.name, u)
            remoteusers = relay.relayusers[userpair].items()
        except KeyError:
            pass
        else:
            nicks = []
            if remoteusers:
                # Display all of the user's relay subclients, if there are any
                nicks.append('%s:\x02%s\x02' % (userpair[0],
                             world.networkobjects[userpair[0]].users[userpair[1]].nick))
                for r in remoteusers:
                    remotenet, remoteuser = r
                    remoteirc = world.networkobjects[remotenet]
                    nicks.append('%s:\x02%s\x02' % (remotenet, remoteirc.users[remoteuser].nick))
                f("\x02Relay nicks\x02: %s" % ', '.join(nicks))
        if verbose:
            # Show the relay channels the user is in, if applicable
            relaychannels = []
            for ch in irc.users[u].channels:
                relayentry = relay.get_relay(irc, ch)
                if relayentry:
                    relaychannels.append(''.join(relayentry))
            if relaychannels and verbose:
                f("\x02Relay channels\x02: %s" % ' '.join(relaychannels))

@utils.add_cmd
def showuser(irc, source, args):
    """<user>

    Shows information about <user>."""
    permissions.check_permissions(irc, source, ['commands.showuser'])
    target = ' '.join(args)

    if not target:
        irc.error("Not enough arguments. Needs 1: nick.")
        return

    users = irc.nick_to_uid(target, multi=True) or [target]

    for user in users:
        _do_showuser(irc, source, user)

@utils.add_cmd
def shownet(irc, source, args):
    """[<network name>]

    Shows information about <network name>, or the current network if no argument is given."""
    permissions.check_permissions(irc, source, ['commands.shownet'])
    try:
        extended = permissions.check_permissions(irc, source, ['commands.shownet.extended'])
    except utils.NotAuthorizedError:
        extended = False

    try:
        target = args[0]
    except IndexError:
        target = irc.name

    try:
        netobj = world.networkobjects[target]
        serverdata = netobj.serverdata
    except KeyError:
        netobj = None

        # If we have extended access, also look for disconnected networks
        if extended and target in conf.conf['servers']:
            serverdata = conf.conf['servers'][target]
        else:
            irc.error('Unknown network %r' % target)
            return

    # Get extended protocol details: IRCd type, virtual server info
    protocol_name = serverdata.get('protocol')
    ircd_type = None

    # A bit of hardcoding here :(
    if protocol_name == 'ts6':
        ircd_type = serverdata.get('ircd', 'charybdis[default]')
    elif protocol_name == 'inspircd':
        ircd_type = serverdata.get('target_version', 'insp20[default]')
    elif protocol_name == 'p10':
        ircd_type = serverdata.get('ircd') or serverdata.get('p10_ircd') or 'nefarious[default]'

    if protocol_name and ircd_type:
        protocol_name = '%s/%s' % (protocol_name, ircd_type)
    elif netobj and not protocol_name:  # Show virtual server detail if applicable
        try:
            parent_name = netobj.virtual_parent.name
        except AttributeError:
            parent_name = None
        protocol_name = 'none; virtual server defined by \x02%s\x02' % parent_name

    irc.reply('Information on network \x02%s\x02: \x02%s\x02' %
              (target, netobj.get_full_network_name() if netobj else '\x1dCurrently not connected\x1d'))

    irc.reply('\x02PyLink protocol module\x02: %s; \x02Encoding\x02: %s' %
              (protocol_name, netobj.encoding if netobj else serverdata.get('encoding', 'utf-8[default]')))

    # Extended info: target host, defined hostname / SID
    if extended:
        connected = netobj and netobj.connected.is_set()
        irc.reply('\x02Connected?\x02 %s' % ('\x0303true' if connected else '\x0304false'))

        if serverdata.get('ip'):
            irc.reply('\x02Server target\x02: \x1f%s:%s' % (serverdata['ip'], serverdata.get('port')))
        if serverdata.get('hostname'):
            irc.reply('\x02PyLink hostname\x02: %s; \x02SID:\x02 %s; \x02SID range:\x02 %s' %
                      (serverdata.get('hostname') or _none,
                        serverdata.get('sid') or _none,
                        serverdata.get('sidrange') or _none))

@utils.add_cmd
def showchan(irc, source, args):
    """<channel>

    Shows information about <channel>."""
    permissions.check_permissions(irc, source, ['commands.showchan'])
    try:
        channel = args[0]
    except IndexError:
        irc.error("Not enough arguments. Needs 1: channel.")
        return
    if channel not in irc.channels:
        irc.error('Unknown channel %r.' % channel)
        return

    f = lambda s: irc.reply(s, private=True)

    c = irc.channels[channel]
    # Only show verbose info if caller is oper or is in the target channel.
    verbose = source in c.users or irc.is_oper(source)
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
    f('\x02Channel creation time\x02: %s (%s) [UTC]%s' %
      (time.asctime(time.gmtime(int(c.ts))), c.ts,
       ' [UNTRUSTED]' if not irc.has_cap('has-ts') else ''))

    # Show only modes that aren't list-style modes.
    modes = irc.join_modes([m for m in c.modes if m[0] not in irc.cmodes['*A']], sort=True)
    f('\x02Channel modes\x02: %s' % modes)
    if verbose:
        nicklist = []
        # Iterate over the user list, sorted by nick.
        for user, nick in sorted(zip(c.users, nicks),
                                 key=lambda userpair: userpair[1].lower()):
            # Note: reversed() is used here because we're adding prefixes onto the nick in reverse
            for pmode in reversed(c.get_prefix_modes(user)):
                # Show prefix modes in order from highest to lowest.
                nick = irc.prefixmodes.get(irc.cmodes.get(pmode, ''), '') + nick
            nicklist.append(nick)

        f('\x02User list\x02: %s' % ' '.join(nicklist))

        # Show relay info, if applicable
        relay = world.plugins.get('relay')
        if relay:
            relayentry = relay.get_relay(irc, channel)
            if relayentry:
                relays = ['\x02%s\x02' % ''.join(relayentry)]
                relays += [''.join(link) for link in relay.db[relayentry]['links']]
                f('\x02Relayed channels:\x02 %s' % (' '.join(relays)))

@utils.add_cmd
def version(irc, source, args):
    """takes no arguments.

    Returns the version of the currently running PyLink instance."""
    py_version = utils.NORMALIZEWHITESPACE_RE.sub(' ', sys.version)
    irc.reply("PyLink version \x02%s\x02 (in VCS: %s), running on Python %s." % (__version__, real_version, py_version))
    irc.reply("The source of this program is available at \x02%s\x02." % world.source)

@utils.add_cmd
def echo(irc, source, args):
    """<text>

    Echoes the text given."""
    permissions.check_permissions(irc, source, ['commands.echo'])
    if not args:
        irc.error('No text to send!')
        return
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
        permissions.check_permissions(irc, source, perms)
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
        otheruid = irc.nick_to_uid(othernick)
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
    permissions.check_permissions(irc, source, ['commands.loglevel'])
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
