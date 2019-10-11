# relay_clientbot.py: Clientbot extensions for Relay
import shlex
import string
import time

from pylinkirc import conf, utils, world
from pylinkirc.log import log

# Clientbot default styles:
# These use template strings as documented @ https://docs.python.org/3/library/string.html#template-strings
default_styles = {'MESSAGE': '\x02[$netname]\x02 <$mode_prefix$colored_sender> $text',
                  'KICK': '\x02[$netname]\x02 - $colored_sender$sender_identhost has kicked $target_nick from $channel ($text)',
                  'PART': '\x02[$netname]\x02 - $colored_sender$sender_identhost has left $channel ($text)',
                  'JOIN': '\x02[$netname]\x02 - $colored_sender$sender_identhost has joined $channel',
                  'NICK': '\x02[$netname]\x02 - $colored_sender$sender_identhost is now known as $newnick',
                  'QUIT': '\x02[$netname]\x02 - $colored_sender$sender_identhost has quit ($text)',
                  'ACTION': '\x02[$netname]\x02 * $mode_prefix$colored_sender $text',
                  'NOTICE': '\x02[$netname]\x02 - Notice from $mode_prefix$colored_sender: $text',
                  'SQUIT': '\x02[$netname]\x02 - Netsplit lost users: $colored_nicks',
                  'SJOIN': '\x02[$netname]\x02 - Netjoin gained users: $colored_nicks',
                  'MODE': '\x02[$netname]\x02 - $colored_sender$sender_identhost sets mode $modes on $channel',
                  'PM': 'PM from $sender on $netname: $text',
                  'PNOTICE': '<$sender> $text',
                  }

def color_text(s):
    """
    Returns a colorized version of the given text based on a simple hash algorithm.
    """
    if not s:
        return s
    colors = ('03', '04', '05', '06', '07', '08', '09', '10', '11', '12', '13', '15')
    hash_output = hash(s.encode())
    num = hash_output % len(colors)
    return "\x03%s%s\x03" % (colors[num], s)

def cb_relay_core(irc, source, command, args):
    """
    This function takes Clientbot events and formats them as text to the target channel / user.
    """
    real_command = command.split('_')[-1]

    relay = world.plugins.get('relay')

    private = False

    if irc.pseudoclient and relay:
        try:
            sourcename = irc.get_friendly_name(source)
        except KeyError:  # User has left due to /quit
            sourcename = args['userdata'].nick

        relay_conf = conf.conf.get('relay') or {}

        # Be less floody on startup: don't relay non-PRIVMSGs for the first X seconds after connect.
        startup_delay = relay_conf.get('clientbot_startup_delay', 20)

        target = args.get('target')
        if isinstance(target, str):
            # Remove STATUSMSG prefixes (e.g. @#channel) before checking whether target is a channel
            target = target.lstrip(''.join(irc.prefixmodes.values()))

        # Special case for CTCPs.
        if real_command == 'MESSAGE':
            # CTCP action, format accordingly
            if (not args.get('is_notice')) and args['text'].startswith('\x01ACTION ') and args['text'].endswith('\x01'):
                args['text'] = args['text'][8:-1]
                real_command = 'ACTION'

            elif not irc.is_channel(target):
                # Target is a user; handle this accordingly.
                if relay_conf.get('allow_clientbot_pms'):
                    real_command = 'PNOTICE' if args.get('is_notice') else 'PM'
                    private = True

            # Other CTCPs are ignored
            elif args['text'].startswith('\x01'):
                return

            elif args.get('is_notice'):  # Different syntax for notices
                real_command = 'NOTICE'
        elif (time.time() - irc.start_ts) < startup_delay:
            log.debug('(%s) relay_cb_core: Not relaying %s because of startup delay of %s.', irc.name,
                      real_command, startup_delay)
            return

        # Try to fetch the format for the given command from the relay:clientbot_styles:$command
        # key, falling back to one defined in default_styles above, and then nothing if not found
        # there.
        text_template = irc.get_service_options('relay', 'clientbot_styles', dict).get(
                            real_command, default_styles.get(real_command, ''))
        text_template = string.Template(text_template)

        if text_template:
            if irc.get_service_bot(source):
                # HACK: service bots are global and lack the relay state we look for.
                # just pretend the message comes from the current network.
                log.debug('(%s) relay_cb_core: Overriding network origin to local (source=%s)', irc.name, source)
                sourcenet = irc.name
                realsource = source
            else:
                # Get the original client that the relay client source was meant for.
                log.debug('(%s) relay_cb_core: Trying to find original sender (user) for %s', irc.name, source)
                try:
                    origuser = relay.get_orig_user(irc, source) or args['userdata'].remote
                except (AttributeError, KeyError):
                    log.debug('(%s) relay_cb_core: Trying to find original sender (server) for %s. serverdata=%s', irc.name, source, args.get('serverdata'))
                    try:
                        localsid = args.get('serverdata') or irc.servers[source]
                        origuser = (localsid.remote, world.networkobjects[localsid.remote].uplink)
                    except (AttributeError, KeyError):
                        return

                log.debug('(%s) relay_cb_core: Original sender found as %s', irc.name, origuser)
                sourcenet, realsource = origuser

            try:  # Try to get the full network name
                netname = conf.conf['servers'][sourcenet]['netname']
            except KeyError:
                netname = sourcenet

            # Figure out where the message is destined to.
            stripped_target = target = args.get('channel') or args.get('target')
            if isinstance(target, str):
                # HACK: cheap fix to prevent @#channel messages from interpreted as non-channel specific
                stripped_target = target.lstrip(''.join(irc.prefixmodes.values()))

            if target is None or not (irc.is_channel(stripped_target) or private):
                # Non-channel specific message (e.g. QUIT or NICK). If this isn't a PM, figure out
                # all channels that the sender shares over the relay, and relay them to those
                # channels.
                userdata = args.get('userdata') or irc.users.get(source)
                if not userdata:
                    # No user data given. This was probably some other global event such as SQUIT.
                    userdata = irc.pseudoclient

                targets = [channel for channel in userdata.channels if relay.get_relay(irc, channel)]
            else:
                # Pluralize the channel so that we can iterate over it.
                targets = [target]
                args['channel'] = stripped_target
            log.debug('(%s) relay_cb_core: Relaying event %s to channels: %s', irc.name, real_command, targets)

            identhost = ''
            if source in irc.users:
                try:
                    identhost = irc.get_hostmask(source).split('!')[-1]
                except KeyError:  # User got removed due to quit
                    identhost = '%s@%s' % (args['userdata'].ident, args['userdata'].host)
                # This is specifically spaced so that ident@host is only shown for users that have
                # one, and not servers.
                identhost = ' (%s)' % identhost

            # $target_nick: Convert the target for kicks, etc. from a UID to a nick
            if args.get("target") in irc.users:
                args["target_nick"] = irc.get_friendly_name(args['target'])

            # Join up modes from their list form
            if args.get('modes'):
                args['modes'] = irc.join_modes(args['modes'])

            mode_prefix = ''
            if 'channel' in args:
                # Display the real (remote) channel name instead of the local one, if applicable.
                args['local_channel'] = args['channel']
                log.debug('(%s) relay_clientbot: coersing $channel from %s to %s', irc.name, args['local_channel'], args['channel'])

                sourceirc = world.networkobjects.get(sourcenet)
                log.debug('(%s) relay_clientbot: Checking prefix modes for %s on %s (relaying to %s)',
                          irc.name, realsource, sourcenet, args['channel'])
                if sourceirc:
                    args['channel'] = remotechan = relay.get_remote_channel(irc, sourceirc, args['channel'])
                    if source in irc.users and remotechan in sourceirc.channels and \
                            realsource in sourceirc.channels[remotechan].users:
                        # Fetch the prefixmode prefixes (e.g. ~@%) for the sender, if available.
                        prefixmodes = sourceirc.channels[remotechan].get_prefix_modes(realsource)
                        log.debug('(%s) relay_clientbot: got prefix modes %s for %s on %s@%s',
                                  irc.name, prefixmodes, realsource, remotechan, sourcenet)
                        if prefixmodes:
                            # Only pick the highest prefix.
                            mode_prefix = sourceirc.prefixmodes.get(
                                sourceirc.cmodes.get(prefixmodes[0]))

            args.update({
                'netname': netname, 'sender': sourcename, 'sender_identhost': identhost,
                'colored_sender': color_text(sourcename), 'colored_netname': color_text(netname),
                'mode_prefix': mode_prefix
            })

            for target in targets:
                cargs = args.copy()  # Copy args list to manipulate them in a channel specific way

                # $nicks / $colored_nicks: used when the event affects multiple users, such as SJOIN or SQUIT.
                # For SJOIN, this is simply a list of nicks. For SQUIT, this is sent as a dict
                # mapping channels to lists of nicks, as netsplits aren't channel specific but
                # still have to be relayed as such.
                nicklist = args.get('nicks')
                if nicklist:
                    # Get channel-specific nick list if relevent.
                    if isinstance(nicklist, dict):
                        nicklist = nicklist.get(target, [])

                    # Ignore if no nicks are affected on the channel.
                    if not nicklist:
                        continue

                    colored_nicks = [color_text(nick) for nick in nicklist]

                    # Join both the nicks and colored_nicks fields into a comma separated string.
                    cargs['nicks'] = ', '.join(nicklist)
                    cargs['colored_nicks'] = ', '.join(colored_nicks)

                text = text_template.safe_substitute(cargs)
                # PMs are always sent as notice - this prevents unknown command loops with bots.
                irc.msg(target, text, loopback=False, notice=private)

utils.add_hook(cb_relay_core, 'CLIENTBOT_MESSAGE')
utils.add_hook(cb_relay_core, 'CLIENTBOT_KICK')
utils.add_hook(cb_relay_core, 'CLIENTBOT_PART')
utils.add_hook(cb_relay_core, 'CLIENTBOT_JOIN')
utils.add_hook(cb_relay_core, 'CLIENTBOT_QUIT')
utils.add_hook(cb_relay_core, 'CLIENTBOT_NICK')
utils.add_hook(cb_relay_core, 'CLIENTBOT_SJOIN')
utils.add_hook(cb_relay_core, 'CLIENTBOT_SQUIT')
utils.add_hook(cb_relay_core, 'RELAY_RAW_MODE')

@utils.add_cmd
def rpm(irc, source, args):
    """<target nick/UID> <text>

    Sends PMs to users over Relay, if Clientbot PMs are enabled.
    If the target nick has spaces in it, you may quote the nick as "nick".
    """
    args = shlex.split(' '.join(args))  # HACK: use shlex.split so that quotes are preserved
    try:
        target = args[0]
        text = ' '.join(args[1:])
    except IndexError:
        irc.error('Not enough arguments. Needs 2: target nick and text.')
        return

    relay = world.plugins.get('relay')
    if irc.has_cap('can-spawn-clients'):
        irc.error('This command is only supported on Clientbot networks. Try /msg %s <text>' % target)
        return
    elif relay is None:
        irc.error('PyLink Relay is not loaded.')
        return
    elif not text:
        irc.error('No text given.')
        return
    elif not conf.conf.get('relay').get('allow_clientbot_pms'):
        irc.error('Private messages with users connected via Clientbot have been '
                  'administratively disabled.')
        return

    if target in irc.users:
        uids = [target]
    else:
        uids = irc.nick_to_uid(target, multi=True, filterfunc=lambda u: relay.is_relay_client(irc, u))

    if not uids:
        irc.error('Unknown user %s.' % target)
        return
    elif len(uids) > 1:
        targets = ['\x02%s\x02: %s @ %s' % (uid, irc.get_hostmask(uid), irc.users[uid].remote[0]) for uid in uids]
        irc.error('Please select the target you want to PM: %s' % (', '.join(targets)))
        return
    else:
        assert not irc.is_internal_client(source), "rpm is not allowed from PyLink bots"

        # Send the message through relay by faking a hook for its handler.
        relay.handle_messages(irc, source, 'RELAY_CLIENTBOT_PRIVMSG', {'target': uids[0], 'text': text})
        irc.reply('Message sent.')
