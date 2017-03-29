# fantasy.py: Adds FANTASY command support, to allow calling commands in channels
from pylinkirc import utils, world, conf
from pylinkirc.log import log

def handle_fantasy(irc, source, command, args):
    """Fantasy command handler."""

    if not irc.connected.is_set():
        # Break if the IRC network isn't ready.
        return

    channel = args['target']
    orig_text = args['text']

    if utils.isChannel(channel) and not irc.isInternalClient(source):
        # The following conditions must be met for an incoming message for
        # fantasy to trigger:
        #   1) The message target is a channel.
        #   2) A PyLink service client exists in the channel.
        #   3) The message starts with one of our fantasy prefixes.
        #   4) The sender is NOT a PyLink client (this prevents infinite
        #      message loops).
        for botname, sbot in world.services.copy().items():
            if botname not in world.services:  # Bot was removed during iteration
                continue

            # Check respond to nick options in this order:
            # 1) The service specific "respond_to_nick" option
            # 2) The global "pylink::respond_to_nick" option
            # 3) The (deprecated) global "bot::respondtonick" option.
            respondtonick = conf.conf.get(botname, {}).get('respond_to_nick',
                conf.conf['pylink'].get("respond_to_nick", conf.conf['bot'].get("respondtonick")))

            log.debug('(%s) fantasy: checking bot %s', irc.name, botname)
            servuid = sbot.uids.get(irc.name)
            if servuid in irc.channels[channel].users:

                # Look up a string prefix for this bot in either its own configuration block, or
                # in bot::prefixes::<botname>.
                prefixes = [conf.conf.get(botname, {}).get('prefix',
                            conf.conf['bot'].get('prefixes', {}).get(botname))]

                # If responding to nick is enabled, add variations of the current nick
                # to the prefix list: "<nick>," and "<nick>:"
                nick = irc.toLower(irc.users[servuid].nick)

                nick_prefixes = [nick+',', nick+':']
                if respondtonick:
                    prefixes += nick_prefixes

                if not any(prefixes):
                    # No prefixes were set, so skip.
                    continue

                lowered_text = irc.toLower(orig_text)
                for prefix in filter(None, prefixes):  # Cycle through the prefixes list we finished with.
                     if lowered_text.startswith(prefix):

                        # Cut off the length of the prefix from the text.
                        text = orig_text[len(prefix):]

                        # HACK: don't trigger on commands like "& help" to prevent false positives.
                        # Weird spacing like "PyLink:   help" and "/msg PyLink   help" should still
                        # work though.
                        if text.startswith(' ') and prefix not in nick_prefixes:
                            log.debug('(%s) fantasy: skipping trigger with text prefix followed by space', irc.name)
                            continue

                        # Finally, call the bot command and loop to the next bot.
                        sbot.call_cmd(irc, source, text, called_in=channel)
                        continue

utils.add_hook(handle_fantasy, 'PRIVMSG')
