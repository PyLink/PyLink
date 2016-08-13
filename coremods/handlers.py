"""
handlers.py - Implements miscellaneous IRC command handlers (WHOIS, services login, etc.)
"""
import time

from pylinkirc import utils, conf
from pylinkirc.log import log

def handle_whois(irc, source, command, args):
    """Handle WHOIS queries."""
    target = args['target']
    user = irc.users.get(target)

    f = lambda num, source, text: irc.proto.numeric(irc.sid, num, source, text)

    # Get the server that the target is on.
    server = irc.getServer(target)

    if user is None:  # User doesn't exist
        # <- :42X 401 7PYAAAAAB GL- :No such nick/channel
        nick = target
        f(401, source, "%s :No such nick/channel" % nick)
    else:
        nick = user.nick
        sourceisOper = ('o', None) in irc.users[source].modes
        sourceisBot = (irc.umodes.get('bot'), None) in irc.users[source].modes

        # Get the full network name.
        netname = irc.serverdata.get('netname', irc.name)

        # https://www.alien.net.au/irc/irc2numerics.html
        # 311: sends nick!user@host information
        f(311, source, "%s %s %s * :%s" % (nick, user.ident, user.host, user.realname))

        # 319: RPL_WHOISCHANNELS; Show public channels of the target, respecting
        # hidechans umodes for non-oper callers.
        isHideChans = (irc.umodes.get('hidechans'), None) in user.modes
        if (not isHideChans) or (isHideChans and sourceisOper):
            public_chans = []
            for chan in user.channels:
                c = irc.channels[chan]
                # Here, we'll want to hide secret/private channels from non-opers
                # who are not in them.

                if ((irc.cmodes.get('secret'), None) in c.modes or \
                    (irc.cmodes.get('private'), None) in c.modes) \
                    and not (sourceisOper or source in c.users):
                        continue

                # Show the highest prefix mode like a regular IRCd does, if there are any.
                prefixes = c.getPrefixModes(target)
                if prefixes:
                    highest = prefixes[-1]

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
            if (not isHideOper) or (isHideOper and sourceisOper) or \
                    (isHideOper and not irc.botdata.get('whois_use_hideoper', True)):
                # Let's be gramatically correct. (If the opertype starts with a vowel,
                # write "an Operator" instead of "a Operator")
                n = 'n' if user.opertype[0].lower() in 'aeiou' else ''

                # I want to normalize the syntax: PERSON is an OPERTYPE on NETWORKNAME.
                # This is the only syntax InspIRCd supports, but for others it doesn't
                # really matter since we're handling the WHOIS requests by ourselves.
                f(313, source, "%s :is a%s %s on %s" % (nick, n, user.opertype, netname))

        # 379: RPL_WHOISMODES, used by UnrealIRCd and InspIRCd to show user modes.
        # Only show this to opers!
        if sourceisOper:
            f(378, source, "%s :is connecting from %s@%s %s" % (nick, user.ident, user.realhost, user.ip))
            f(379, source, '%s :is using modes %s' % (nick, irc.joinModes(user.modes, sort=True)))

        # 301: used to show away information if present
        away_text = user.away
        log.debug('(%s) coremods.handlers.handle_whois: away_text for %s is %r', irc.name, target, away_text)
        if away_text:
            f(301, source, '%s :%s' % (nick, away_text))

        if (irc.umodes.get('bot'), None) in user.modes:
            # Show botmode info in WHOIS.
            f(335, source, "%s :is a bot" % nick)

        # Call custom WHOIS handlers via the PYLINK_CUSTOM_WHOIS hook, unless the
        # caller is marked a bot and the whois_show_extensions_to_bots option is False
        if (sourceisBot and conf.conf['bot'].get('whois_show_extensions_to_bots')) or (not sourceisBot):
            irc.callHooks([source, 'PYLINK_CUSTOM_WHOIS', {'target': target, 'server': server}])
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
    if irc.isInternalClient(target) and not irc.isInternalClient(source):
        if ('-o', None) in modes and (target == irc.pseudoclient.uid or not irc.isManipulatableClient(target)):
            irc.proto.mode(irc.sid, target, {('+o', None)})
utils.add_hook(handle_mode, 'MODE')

def handle_operup(irc, source, command, args):
    """Logs successful oper-ups on networks."""
    otype = args.get('text', 'IRC Operator')
    log.debug("(%s) Successful oper-up (opertype %r) from %s", irc.name, otype, irc.getHostmask(source))
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
    irc.proto.numeric(irc.sid, 351, source, fullversion)
utils.add_hook(handle_version, 'VERSION')

def handle_time(irc, source, command, args):
    """Handles requests for the PyLink server time."""
    timestring = time.ctime()
    irc.proto.numeric(irc.sid, 391, source, '%s :%s' % (irc.hostname(), timestring))
utils.add_hook(handle_time, 'TIME')
