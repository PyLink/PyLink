"""
service_support.py - Implements handlers for the PyLink ServiceBot API.
"""

from pylinkirc import conf, utils, world
from pylinkirc.log import log

__all__ = []


def spawn_service(irc, source, command, args):
    """Handles new service bot introductions."""

    if not irc.connected.is_set():
        return

    # Service name
    name = args['name']

    if name != 'pylink' and not irc.has_cap('can-spawn-clients'):
        log.debug("(%s) Not spawning service %s because the server doesn't support spawning clients",
                  irc.name, name)
        return

    # Get the ServiceBot object.
    sbot = world.services[name]

    old_userobj = irc.users.get(sbot.uids.get(irc.name))
    if old_userobj and old_userobj.service:
        # A client already exists, so don't respawn it.
        log.debug('(%s) spawn_service: Not respawning service %r as service client %r already exists.', irc.name, name,
                  irc.pseudoclient.nick)
        return

    if name == 'pylink' and irc.pseudoclient:
        # irc.pseudoclient already exists, reuse values from it but
        # spawn a new client. This is used for protocols like Clientbot,
        # so that they can override the main service nick, among other things.
        log.debug('(%s) spawn_service: Using existing nick %r for service %r', irc.name, irc.pseudoclient.nick, name)
        userobj = irc.pseudoclient
        userobj.opertype = "PyLink Service"
        userobj.manipulatable = sbot.manipulatable
    else:
        # No client exists, spawn a new one
        nick = sbot.get_nick(irc)
        ident = sbot.get_ident(irc)
        host = sbot.get_host(irc)
        realname = sbot.get_realname(irc)

        # Spawning service clients with these umodes where supported. servprotect usage is a
        # configuration option.
        preferred_modes = ['oper', 'hideoper', 'hidechans', 'invisible', 'bot']
        modes = []

        if conf.conf['pylink'].get('protect_services'):
            preferred_modes.append('servprotect')

        for mode in preferred_modes:
            mode = irc.umodes.get(mode)
            if mode:
                modes.append((mode, None))

        # Track the service's UIDs on each network.
        log.debug('(%s) spawn_service: Spawning new client %s for service %s', irc.name, nick, name)
        userobj = irc.spawn_client(nick, ident, host, modes=modes, opertype="PyLink Service",
                                   realname=realname, manipulatable=sbot.manipulatable)

    # Store the service name in the User object for easier access.
    userobj.service = name

    sbot.uids[irc.name] = u = userobj.uid

    # Special case: if this is the main PyLink client being spawned,
    # assign this as irc.pseudoclient.
    if name == 'pylink' and not irc.pseudoclient:
        log.debug('(%s) spawn_service: irc.pseudoclient set to UID %s', irc.name, u)
        irc.pseudoclient = userobj

    # Enumerate & join network defined channels.
    sbot.join(irc, sbot.get_persistent_channels(irc))

utils.add_hook(spawn_service, 'PYLINK_NEW_SERVICE')

def handle_disconnect(irc, source, command, args):
    """Handles network disconnections."""
    for name, sbot in world.services.items():
        try:
            del sbot.uids[irc.name]
            log.debug("coremods.service_support: removing uids[%s] from service bot %s", irc.name, sbot.name)
        except KeyError:
            continue

utils.add_hook(handle_disconnect, 'PYLINK_DISCONNECT')

def handle_endburst(irc, source, command, args):
    """Handles network bursts."""
    if source == irc.uplink:
        log.debug('(%s): spawning service bots now.', irc.name)

        # We just connected. Burst all our registered services.
        for name, sbot in world.services.items():
            spawn_service(irc, source, command, {'name': name})

utils.add_hook(handle_endburst, 'ENDBURST', priority=500)

def handle_kill(irc, source, command, args):
    """Handle KILLs to PyLink service bots, respawning them as needed."""
    target = args['target']
    if irc.pseudoclient and target == irc.pseudoclient.uid:
        irc.pseudoclient = None
    userdata = args.get('userdata')
    sbot = irc.get_service_bot(target)
    servicename = None

    if userdata and hasattr(userdata, 'service'):  # Look for the target's service name attribute
        servicename = userdata.service
    elif sbot:  # Or their service bot instance
        servicename = sbot.name
    if servicename:
        log.info('(%s) Received kill to service %r (nick: %r) from %s (reason: %r).', irc.name, servicename,
                 userdata.nick if userdata else irc.users[target].nick, irc.get_hostmask(source), args.get('text'))
        spawn_service(irc, source, command, {'name': servicename})

utils.add_hook(handle_kill, 'KILL')

def handle_join(irc, source, command, args):
    """Monitors channel joins for dynamic service bot joining."""
    if irc.has_cap('visible-state-only'):
        # No-op on bot-only servers.
        return

    channel = args['channel']
    users = irc.channels[channel].users
    for servicename, sbot in world.services.items():
        if channel in sbot.get_persistent_channels(irc) and \
                sbot.uids.get(irc.name) not in users:
            log.debug('(%s) Dynamically joining service %r to channel %r.', irc.name, servicename, channel)
            sbot.join(irc, channel)
utils.add_hook(handle_join, 'JOIN')
utils.add_hook(handle_join, 'PYLINK_SERVICE_JOIN')

def _services_dynamic_part(irc, channel):
    """Dynamically removes service bots from empty channels."""
    if irc.has_cap('visible-state-only'):
        # No-op on bot-only servers.
        return
    if irc.serverdata.get('join_empty_channels', conf.conf['pylink'].get('join_empty_channels', False)):
        return

    # If all remaining users in the channel are service bots, make them all part.
    if all(irc.get_service_bot(u) for u in irc.channels[channel].users):
        for u in irc.channels[channel].users.copy():
            sbot = irc.get_service_bot(u)
            if sbot:
                log.debug('(%s) Dynamically parting service %r from channel %r.', irc.name, sbot.name, channel)
                irc.part(u, channel)
        return True

def handle_part(irc, source, command, args):
    """Monitors channel joins for dynamic service bot joining."""
    for channel in args['channels']:
        _services_dynamic_part(irc, channel)
utils.add_hook(handle_part, 'PART')

def handle_kick(irc, source, command, args):
    """Handle KICKs to the PyLink service bots, rejoining channels as needed."""
    channel = args['channel']
    # Skip autorejoin routines if the channel is now empty.
    if not _services_dynamic_part(irc, channel):
        kicked = args['target']
        sbot = irc.get_service_bot(kicked)
        if sbot and channel in sbot.get_persistent_channels(irc):
            sbot.join(irc, channel)
utils.add_hook(handle_kick, 'KICK')

def handle_commands(irc, source, command, args):
    """Handle commands sent to the PyLink service bots (PRIVMSG)."""
    target = args['target']
    text = args['text']

    sbot = irc.get_service_bot(target)
    if sbot:
        sbot.call_cmd(irc, source, text)

utils.add_hook(handle_commands, 'PRIVMSG')

# Register the main PyLink service. All command definitions MUST go after this!
# TODO: be more specific in description, and possibly allow plugins to modify this to mention
# their features?
mydesc = "\x02PyLink\x02 provides extended network services for IRC."
utils.register_service('pylink', default_nick="PyLink", desc=mydesc, manipulatable=True)
