# antispam.py: Basic services-side spamfilters for IRC

from pylinkirc import utils, world, conf
from pylinkirc.log import log

mydesc = ("Provides anti-spam functionality.")
sbot = utils.register_service("antispam", default_nick="AntiSpam", desc=mydesc)

def die(irc=None):
    utils.unregister_service("antispam")

PUNISH_OPTIONS = ['kill', 'ban', 'quiet', 'kick']
EXEMPT_OPTIONS = ['voice', 'halfop', 'op']
DEFAULT_EXEMPT_OPTION = 'halfop'
def _punish(irc, target, channel, reason):
    """Punishes the target user. This function returns True if the user was successfully punished."""
    if irc.is_oper(target, allowAuthed=False):
        log.debug("(%s) antispam: refusing to punish oper %s/%s", irc.name, target, irc.get_friendly_name(target))
        return False

    exempt_level = irc.get_service_option('antispam', 'exempt_level', DEFAULT_EXEMPT_OPTION).lower()
    c = irc.channels[channel]

    if exempt_level not in EXEMPT_OPTIONS:
        log.error('(%s) Antispam exempt %r is not a valid setting, '
                  'falling back to defaults; accepted settings include: %s',
                  irc.name, exempt_level, ', '.join(EXEMPT_OPTIONS))
        exempt_level = DEFAULT_EXEMPT_OPTION

    if exempt_level == 'voice' and c.is_voice_plus(target):
        log.debug("(%s) antispam: refusing to punish voiced and above %s/%s", irc.name, target, irc.get_friendly_name(target))
        return False
    elif exempt_level == 'halfop' and c.is_halfop_plus(target):
        log.debug("(%s) antispam: refusing to punish halfop and above %s/%s", irc.name, target, irc.get_friendly_name(target))
        return False
    elif exempt_level == 'op' and c.is_op_plus(target):
        log.debug("(%s) antispam: refusing to punish op and above %s/%s", irc.name, target, irc.get_friendly_name(target))
        return False

    my_uid = sbot.uids.get(irc.name)
    # XXX workaround for single-bot protocols like Clientbot
    if irc.pseudoclient and not irc.has_cap('can-spawn-clients'):
        my_uid = irc.pseudoclient.uid

    punishment = irc.get_service_option('antispam', 'punishment',
                                        'kick+ban').lower()
    bans = set()
    log.debug('(%s) antispam: got %r as punishment for %s/%s', irc.name, punishment,
              target, irc.get_friendly_name(target))

    def _ban():
        bans.add(irc.make_channel_ban(target))
    def _quiet():
        bans.add(irc.make_channel_ban(target, ban_type='quiet'))
    def _kick():
        irc.kick(my_uid, channel, target, reason)
        irc.call_hooks([my_uid, 'ANTISPAM_KICK', {'channel': channel, 'text': reason, 'target': target,
                                                  'parse_as': 'KICK'}])
    def _kill():
        if target not in irc.users:
            log.debug('(%s) antispam: not killing %s/%s; they already left', irc.name, target,
                      irc.get_friendly_name(target))
            return
        userdata = irc.users[target]
        irc.kill(my_uid, target, reason)
        irc.call_hooks([my_uid, 'ANTISPAM_KILL', {'target': target, 'text': reason,
                                                  'userdata': userdata, 'parse_as': 'KILL'}])

    kill = False
    for action in set(punishment.split('+')):
        if action not in PUNISH_OPTIONS:
            log.error('(%s) Antispam punishment %r is not a valid setting; '
                      'accepted settings include: %s OR any combination of '
                      'these joined together with a "+".',
                      irc.name, punishment, ', '.join(PUNISH_OPTIONS))
            return
        elif action == 'kill':
            kill = True  # Delay kills so that the user data doesn't disappear.
        elif action == 'kick':
            _kick()
        elif action == 'ban':
            _ban()
        elif action == 'quiet':
            _quiet()

    if bans:  # Set all bans at once to prevent spam
        irc.mode(my_uid, channel, bans)
        irc.call_hooks([my_uid, 'ANTISPAM_BAN',
                        {'target': channel, 'modes': bans, 'parse_as': 'MODE'}])
    if kill:
        _kill()
    return True

MASSHIGHLIGHT_DEFAULTS = {
    'min_length': 50,
    'min_nicks': 5,
    'reason': "Mass highlight spam is prohibited"
}
def handle_masshighlight(irc, source, command, args):
    """Handles mass highlight attacks."""
    channel = args['target']
    text = args['text']
    mhl_settings = irc.get_service_option('antispam', 'masshighlight',
                                          MASSHIGHLIGHT_DEFAULTS)
    my_uid = sbot.uids.get(irc.name)

    # XXX workaround for single-bot protocols like Clientbot
    if irc.pseudoclient and not irc.has_cap('can-spawn-clients'):
        my_uid = irc.pseudoclient.uid

    if (not irc.connected.is_set()) or (not my_uid):
        # Break if the network isn't ready.
        log.debug("(%s) antispam: skipping processing; network isn't ready", irc.name)
        return
    elif not irc.is_channel(channel):
        # Not a channel.
        log.debug("(%s) antispam: skipping processing; %r is not a channel", irc.name, channel)
        return
    elif irc.is_internal_client(source):
        # Ignore messages from our own clients.
        log.debug("(%s) antispam: skipping processing message from internal client %s", irc.name, source)
        return
    elif channel not in irc.channels or my_uid not in irc.channels[channel].users:
        # We're not monitoring this channel.
        log.debug("(%s) antispam: skipping processing message from channel %r we're not in", irc.name, channel)
        return
    elif len(text) < mhl_settings.get('min_length', MASSHIGHLIGHT_DEFAULTS['min_length']):
        log.debug("(%s) antispam: skipping processing message %r; it's too short", irc.name, text)
        return

    # Strip :, from potential nicks
    words = [word.rstrip(':,') for word in text.split()]

    userlist = [irc.users[uid].nick for uid in irc.channels[channel].users.copy()]
    min_nicks = mhl_settings.get('min_nicks', MASSHIGHLIGHT_DEFAULTS['min_nicks'])

    # Don't allow repeating the same nick to trigger punishment
    nicks_caught = set()

    punished = False
    for word in words:
        if word in userlist:
            nicks_caught.add(word)
        if len(nicks_caught) >= min_nicks:
            reason = mhl_settings.get('reason', MASSHIGHLIGHT_DEFAULTS['reason'])
            log.debug('(%s) antispam: calling _punish on %s/%s', irc.name,
                      source, irc.get_friendly_name(source))
            punished = _punish(irc, source, channel, reason)
            break

    log.debug('(%s) antispam: got %s/%s nicks on message to %r', irc.name, len(nicks_caught), min_nicks, channel)
    return not punished  # Filter this message from relay, etc. if it triggered protection

utils.add_hook(handle_masshighlight, 'PRIVMSG', priority=1000)
utils.add_hook(handle_masshighlight, 'NOTICE', priority=1000)
