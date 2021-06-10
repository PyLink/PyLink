"""
handlers.py - Implements miscellaneous IRC command handlers (WHOIS, services login, etc.)
"""
import time

from pylinkirc import conf, utils
from pylinkirc.log import log

__all__ = []


def handle_whois(irc, source, command, args):
    """Handle WHOIS queries."""
    target = args['target']
    user = irc.users.get(target)

    f = lambda num, source, text: irc.numeric(irc.sid, num, source, text)

    # Get the server that the target is on.
    server = irc.get_server(target)

    if user is None:  # User doesn't exist
        # <- :42X 401 7PYAAAAAB jlu5- :No such nick/channel
        nick = target
        f(401, source, "%s :No such nick/channel" % nick)
    else:
        nick = user.nick
        source_is_oper = ('o', None) in irc.users[source].modes
        source_is_bot = (irc.umodes.get('bot'), None) in irc.users[source].modes

        # Get the full network name.
        netname = irc.serverdata.get('netname', irc.name)

        # https://www.alien.net.au/irc/irc2numerics.html
        # 311: sends nick!user@host information
        f(311, source, "%s %s %s * :%s" % (nick, user.ident, user.host, user.realname))

        # 319: RPL_WHOISCHANNELS; Show public channels of the target, respecting
        # hidechans umodes for non-oper callers.
        isHideChans = (irc.umodes.get('hidechans'), None) in user.modes
        if (not isHideChans) or (isHideChans and source_is_oper):
            public_chans = []
            for chan in user.channels:
                c = irc.channels[chan]
                # Here, we'll want to hide secret/private channels from non-opers
                # who are not in them.

                if ((irc.cmodes.get('secret'), None) in c.modes or \
                    (irc.cmodes.get('private'), None) in c.modes) \
                    and not (source_is_oper or source in c.users):
                        continue

                # Show the highest prefix mode like a regular IRCd does, if there are any.
                prefixes = c.get_prefix_modes(target)
                if prefixes:
                    highest = prefixes[0]

                    # Fetch the prefix mode letter from the named mode.
                    modechar = irc.cmodes[highest]

                    # Fetch and prepend the prefix character (@, +, etc.), given the mode letter.
                    chan = irc.prefixmodes[modechar] + chan

                public_chans.append(chan)

            if public_chans:  # Only send the line if the person is in any visible channels...
                f(319, source, '%s :%s' % (nick, ' '.join(public_chans)))

        # 312: sends the server the target is on, and its server description.
        f(312, source, "%s %s :%s" % (nick, irc.servers[server].name,
          irc.servers[server].desc))

        # 313: sends a string denoting the target's operator privilege if applicable.
        if ('o', None) in user.modes:
            # Check hideoper status. Require that either:
            # 1) +H is not set
            # 2) +H is set, but the caller is oper
            # 3) +H is set, but whois_use_hideoper is disabled in config
            isHideOper = (irc.umodes.get('hideoper'), None) in user.modes
            if (not isHideOper) or (isHideOper and source_is_oper) or \
                    (isHideOper and not conf.conf['pylink'].get('whois_use_hideoper', True)):
                opertype = user.opertype

                # Let's be gramatically correct. (If the opertype starts with a vowel,
                # write "an Operator" instead of "a Operator")
                n = 'n' if opertype[0].lower() in 'aeiou' else ''

                # Remove the "(on $network)" bit in relay oper types if the target network is the
                # same - this prevents duplicate text such as "jlu5/ovd is a Network Administrator
                # (on OVERdrive-IRC) on OVERdrive-IRC" from showing.
                # XXX: does this post-processing really belong here?
                opertype = opertype.replace(' (on %s)' % irc.get_full_network_name(), '')

                f(313, source, "%s :is a%s %s" % (nick, n, opertype))

        # 379: RPL_WHOISMODES, used by UnrealIRCd and InspIRCd to show user modes.
        # Only show this to opers!
        if source_is_oper:
            f(378, source, "%s :is connecting from %s@%s %s" % (nick, user.ident, user.realhost, user.ip))
            f(379, source, '%s :is using modes %s' % (nick, irc.join_modes(user.modes, sort=True)))

        # 301: used to show away information if present
        away_text = user.away
        log.debug('(%s) coremods.handlers.handle_whois: away_text for %s is %r', irc.name, target, away_text)
        if away_text:
            f(301, source, '%s :%s' % (nick, away_text))

        if (irc.umodes.get('bot'), None) in user.modes:
            # Show botmode info in WHOIS.
            f(335, source, "%s :is a bot" % nick)

        # :charybdis.midnight.vpn 317 jlu5 jlu5 1946 1499867833 :seconds idle, signon time
        if irc.get_service_bot(target) and conf.conf['pylink'].get('whois_show_startup_time', True):
            f(317, source, "%s 0 %s :seconds idle (placeholder), signon time" % (nick, irc.start_ts))

        # Call custom WHOIS handlers via the PYLINK_CUSTOM_WHOIS hook, unless the
        # caller is marked a bot and the whois_show_extensions_to_bots option is False
        if (source_is_bot and conf.conf['pylink'].get('whois_show_extensions_to_bots')) or (not source_is_bot):
            irc.call_hooks([source, 'PYLINK_CUSTOM_WHOIS', {'target': target, 'server': server}])
        else:
            log.debug('(%s) coremods.handlers.handle_whois: skipping custom whois handlers because '
                      'caller %s is marked as a bot', irc.name, source)

    # 318: End of WHOIS.
    f(318, source, "%s :End of /WHOIS list" % nick)
utils.add_hook(handle_whois, 'WHOIS')

def handle_mode(irc, source, command, args):
    """Protect against forced deoper attempts."""
    target = args['target']
    modes = args['modes']
    # If the sender is not a PyLink client, and the target IS a protected
    # client, revert any forced deoper attempts.
    if irc.is_internal_client(target) and not irc.is_internal_client(source):
        if ('-o', None) in modes and (target == irc.pseudoclient.uid or not irc.is_manipulatable_client(target)):
            irc.mode(irc.sid, target, {('+o', None)})
utils.add_hook(handle_mode, 'MODE')

def handle_operup(irc, source, command, args):
    """Logs successful oper-ups on networks."""
    otype = args.get('text', 'IRC Operator')
    log.debug("(%s) Successful oper-up (opertype %r) from %s", irc.name, otype, irc.get_hostmask(source))
    irc.users[source].opertype = otype

utils.add_hook(handle_operup, 'CLIENT_OPERED')

def handle_services_login(irc, source, command, args):
    """Sets services login status for users."""

    try:
        irc.users[source].services_account = args['text']
    except KeyError:  # User doesn't exist
        log.debug("(%s) Ignoring early account name setting for %s (UID hasn't been sent yet)", irc.name, source)

utils.add_hook(handle_services_login, 'CLIENT_SERVICES_LOGIN')

def handle_version(irc, source, command, args):
    """Handles requests for the PyLink server version."""
    # 351 syntax is usually "<server version>. <server hostname> :<anything else you want to add>
    fullversion = irc.version()
    irc.numeric(irc.sid, 351, source, fullversion)
utils.add_hook(handle_version, 'VERSION')

def handle_time(irc, source, command, args):
    """Handles requests for the PyLink server time."""
    timestring = time.ctime()
    irc.numeric(irc.sid, 391, source, '%s :%s' % (irc.hostname(), timestring))
utils.add_hook(handle_time, 'TIME')

def _state_cleanup_core(irc, source, channel):
    """
    Handles PART and KICK on clientbot-like networks (where only the users and channels we see are available)
    by deleting channels when we leave and users when they leave all shared channels.
    """
    if irc.has_cap('visible-state-only'):
        # Delete channels that we were removed from.
        if irc.pseudoclient and source == irc.pseudoclient.uid:
            log.debug('(%s) state_cleanup: removing channel %s since we have left', irc.name, channel)
            del irc._channels[channel]

        # Delete external users no longer sharing a channel with us.
        if (not irc.users[source].channels) and (not irc.is_internal_client(source)):
            log.debug('(%s) state_cleanup: removing external user %s/%s who no longer shares a channel with us',
                      irc.name, source, irc.users[source].nick)
            irc._remove_client(source)

    # Clear empty non-permanent channels.
    if channel in irc.channels and not (irc._channels[channel].users or ((irc.cmodes.get('permanent'), None) \
            in irc._channels[channel].modes)):
        log.debug('(%s) state_cleanup: removing empty channel %s', irc.name, channel)
        del irc._channels[channel]

def _state_cleanup_part(irc, source, command, args):
    for channel in args['channels']:
        _state_cleanup_core(irc, source, channel)
utils.add_hook(_state_cleanup_part, 'PART', priority=-100)

def _state_cleanup_kick(irc, source, command, args):
    _state_cleanup_core(irc, args['target'], args['channel'])
utils.add_hook(_state_cleanup_kick, 'KICK', priority=-100)

def _state_cleanup_mode(irc, source, command, args):
    """
    Cleans up and removes empty channels when -P (permanent mode) is removed from them.
    """
    target = args['target']
    if target in irc.channels and 'permanent' in irc.cmodes:
        c = irc.channels[target]
        mode = '-%s' % irc.cmodes['permanent']

        if (not c.users) and (mode, None) in args['modes']:
            log.debug('(%s) _state_cleanup_mode: deleting empty channel %s as %s was set', irc.name, target, mode)
            del irc._channels[target]
            return False  # Block further hooks from running
utils.add_hook(_state_cleanup_mode, 'MODE', priority=10000)
