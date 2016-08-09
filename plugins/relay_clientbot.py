# relay_clientbot.py: Clientbot extensions for Relay
import string
import collections
import time

from pylinkirc import utils, conf, world
from pylinkirc.log import log

# TODO: document configurable styles in relay::clientbot_styles::COMMAND_NAME
# These use template strings as documented @ https://docs.python.org/3/library/string.html#template-strings
default_styles = {'MESSAGE': '\x02[$colored_netname]\x02 <$colored_sender> $text',
                  'KICK': '\x02[$colored_netname]\x02 - $colored_sender$sender_identhost has kicked $target_nick from $channel ($text)',
                  'PART': '\x02[$colored_netname]\x02 - $colored_sender$sender_identhost has left $channel ($text)',
                  'JOIN': '\x02[$colored_netname]\x02 - $colored_sender$sender_identhost has joined $channel',
                  'NICK': '\x02[$colored_netname]\x02 - $colored_sender$sender_identhost is now known as $newnick',
                  'QUIT': '\x02[$colored_netname]\x02 - $colored_sender$sender_identhost has quit ($text)',
                  'ACTION': '\x02[$colored_netname]\x02 * $colored_sender $text',
                  'NOTICE': '\x02[$colored_netname]\x02 - Notice from $colored_sender: $text',
                  'SQUIT': '\x02[$colored_netname]\x02 - Netsplit lost users: $colored_nicks',
                  'SJOIN': '\x02[$colored_netname]\x02 - Netjoin gained users: $colored_nicks',
                  }

def color_text(s):
    """
    Returns a colorized version of the given text based on a simple hash algorithm
    (sum of all characters).
    """
    colors = ('02', '03', '04', '05', '06', '07', '08', '09', '10', '11',
              '12', '13')
    num = sum([ord(char) for char in s])
    num = num % len(colors)
    return "\x03%s%s\x03" % (colors[num], s)

def cb_relay_core(irc, source, command, args):
    """
    This function takes Clientbot actions and outputs them to a channel as regular text.
    """
    real_command = command.split('_')[-1]

    relay = world.plugins.get('relay')
    if irc.pseudoclient and relay:
        try:
            sourcename = irc.getFriendlyName(source)
        except KeyError:  # User has left due to /quit
            sourcename = args['userdata'].nick

        relay_conf = conf.conf.get('relay', {})

        # Be less floody on startup: don't relay non-PRIVMSGs for the first X seconds after connect.
        startup_delay = relay_conf.get('clientbot_startup_delay', 5)

        # Special case for CTCPs.
        if real_command == 'MESSAGE':
            # CTCP action, format accordingly
            if (not args.get('is_notice')) and args['text'].startswith('\x01ACTION ') and args['text'].endswith('\x01'):
                args['text'] = args['text'][8:-1]

                real_command = 'ACTION'

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
        text_template = relay_conf.get('clientbot_styles', {}).get(real_command,
                        default_styles.get(real_command, ''))
        text_template = string.Template(text_template)

        if text_template:
            # Get the original client that the relay client source was meant for.
            log.debug('(%s) relay_cb_core: Trying to find original sender (user) for %s', irc.name, source)
            try:
                origuser = relay.getOrigUser(irc, source) or args['userdata'].remote
            except (AttributeError, KeyError):
                log.debug('(%s) relay_cb_core: Trying to find original sender (server) for %s. serverdata=%s', irc.name, source, args.get('serverdata'))
                try:
                    origuser = ((args.get('serverdata') or irc.servers[source]).remote,)
                except (AttributeError, KeyError):
                    return

            log.debug('(%s) relay_cb_core: Original sender found as %s', irc.name, origuser)
            netname = origuser[0]
            try:  # Try to get the full network name
                netname = conf.conf['servers'][netname]['netname'].lower()
            except KeyError:
                pass

            # Figure out where the message is destined to.
            target = args.get('channel') or args.get('target')
            if target is None or not utils.isChannel(target):
                # Quit and nick messages are not channel specific. Figure out all channels that the
                # sender shares over the relay, and relay them that way.
                userdata = args.get('userdata') or irc.users.get(source)
                if not userdata:
                    # No user data given. This was probably some other global event such as SQUIT.
                    userdata = irc.pseudoclient

                channels = [channel for channel in userdata.channels if relay.getRelay((irc.name, channel))]
            else:
                # Pluralize the channel so that we can iterate over it.
                channels = [target]
            log.debug('(%s) relay_cb_core: Relaying event %s to channels: %s', irc.name, real_command, channels)

            if source in irc.users:
                try:
                    identhost = irc.getHostmask(source).split('!')[-1]
                except KeyError:  # User got removed due to quit
                    identhost = '%s@%s' % (args['olduser'].ident, args['olduser'].host)
                # This is specifically spaced so that ident@host is only shown for users that have
                # one, and not servers.
                identhost = ' (%s)' % identhost
            else:
                identhost = ''

            # $target_nick: Convert the target for kicks, etc. from a UID to a nick
            if args.get("target") in irc.users:
                args["target_nick"] = irc.getFriendlyName(args['target'])

            args.update({'netname': netname, 'sender': sourcename, 'sender_identhost': identhost,
                         'colored_sender': color_text(sourcename), 'colored_netname': color_text(netname)})

            for channel in channels:
                cargs = args.copy()  # Copy args list to manipualte them in a channel specific way

                # $nicks / $colored_nicks: used when the event affects multiple users, such as SJOIN or SQUIT.
                # For SJOIN, this is simply a list of nicks. For SQUIT, this is sent as a dict
                # mapping channels to lists of nicks, as netsplits aren't channel specific but
                # still have to be relayed as such.
                nicklist = args.get('nicks')
                if nicklist:

                    # Get channel-specific nick list if relevent.
                    if type(nicklist) == collections.defaultdict:
                        nicklist = nicklist.get(channel, [])

                    # Ignore if no nicks are affected on the channel.
                    if not nicklist:
                        continue

                    colored_nicks = [color_text(nick) for nick in nicklist]

                    # Join both the nicks and colored_nicks fields into a comma separated string.
                    cargs['nicks'] = ', '.join(nicklist)
                    cargs['colored_nicks'] = ', '.join(colored_nicks)

                text = text_template.safe_substitute(cargs)
                irc.proto.message(irc.pseudoclient.uid, channel, text)

utils.add_hook(cb_relay_core, 'CLIENTBOT_MESSAGE')
utils.add_hook(cb_relay_core, 'CLIENTBOT_KICK')
utils.add_hook(cb_relay_core, 'CLIENTBOT_PART')
utils.add_hook(cb_relay_core, 'CLIENTBOT_JOIN')
utils.add_hook(cb_relay_core, 'CLIENTBOT_QUIT')
utils.add_hook(cb_relay_core, 'CLIENTBOT_NICK')
utils.add_hook(cb_relay_core, 'CLIENTBOT_SJOIN')
utils.add_hook(cb_relay_core, 'CLIENTBOT_SQUIT')
