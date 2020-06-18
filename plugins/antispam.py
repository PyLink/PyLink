# antispam.py: Basic services-side spamfilters for IRC

from pylinkirc import conf, utils
from pylinkirc.log import log

mydesc = ("Provides anti-spam functionality.")
sbot = utils.register_service("antispam", default_nick="AntiSpam", desc=mydesc)

def die(irc=None):
    utils.unregister_service("antispam")

_UNICODE_CHARMAP = {
    'A': 'AΑАᎪᗅᴀ𝐀𝐴𝑨𝒜𝓐𝔄𝔸𝕬𝖠𝗔𝘈𝘼𝙰𝚨𝛢𝜜𝝖𝞐',
    'B': 'BʙΒВвᏴᗷᛒℬ𐌁𝐁𝐵𝑩𝓑𝔅𝔹𝕭𝖡𝗕𝘉𝘽𝙱𝚩𝛣𝜝𝝗𝞑',
    'C': 'CϹСᏟℂℭⅭⲤ𐌂𝐂𝐶𝑪𝒞𝓒𝕮𝖢𝗖𝘊𝘾𝙲',
    'D': 'DᎠᗞᗪᴅⅅⅮ𝐃𝐷𝑫𝒟𝓓𝔇𝔻𝕯𝖣𝗗𝘋𝘿𝙳',
    'E': 'EΕЕᎬᴇℰ⋿ⴹ𝐄𝐸𝑬𝓔𝔈𝔼𝕰𝖤𝗘𝘌𝙀𝙴𝚬𝛦𝜠𝝚𝞔',
    'F': 'FϜᖴℱ𝐅𝐹𝑭𝓕𝔉𝔽𝕱𝖥𝗙𝘍𝙁𝙵𝟊',
    'G': 'GɢԌԍᏀᏳ𝐆𝐺𝑮𝒢𝓖𝔊𝔾𝕲𝖦𝗚𝘎𝙂𝙶',
    'H': 'HʜΗНнᎻᕼℋℌℍⲎ𝐇𝐻𝑯𝓗𝕳𝖧𝗛𝘏𝙃𝙷𝚮𝛨𝜢𝝜𝞖',
    'J': 'JЈᎫᒍᴊ𝐉𝐽𝑱𝒥𝓙𝔍𝕁𝕵𝖩𝗝𝘑𝙅𝙹',
    'K': 'KΚКᏦᛕKⲔ𝐊𝐾𝑲𝒦𝓚𝔎𝕂𝕶𝖪𝗞𝘒𝙆𝙺𝚱𝛫𝜥𝝟𝞙',
    'L': 'LʟᏞᒪℒⅬ𝐋𝐿𝑳𝓛𝔏𝕃𝕷𝖫𝗟𝘓𝙇𝙻',
    'M': 'MΜϺМᎷᗰᛖℳⅯⲘ𐌑𝐌𝑀𝑴𝓜𝔐𝕄𝕸𝖬𝗠𝘔𝙈𝙼𝚳𝛭𝜧𝝡𝞛',
    'N': 'NɴΝℕⲚ𝐍𝑁𝑵𝒩𝓝𝔑𝕹𝖭𝗡𝘕𝙉𝙽𝚴𝛮𝜨𝝢𝞜',
    'P': 'PΡРᏢᑭᴘᴩℙⲢ𝐏𝑃𝑷𝒫𝓟𝔓𝕻𝖯𝗣𝘗𝙋𝙿𝚸𝛲𝜬𝝦𝞠',
    'Q': 'Qℚⵕ𝐐𝑄𝑸𝒬𝓠𝔔𝕼𝖰𝗤𝘘𝙌𝚀',
    'R': 'RƦʀᎡᏒᖇᚱℛℜℝ𝐑𝑅𝑹𝓡𝕽𝖱𝗥𝘙𝙍𝚁',
    'S': 'SЅՏᏕᏚ𝐒𝑆𝑺𝒮𝓢𝔖𝕊𝕾𝖲𝗦𝘚𝙎𝚂',
    'T': 'TΤτТтᎢᴛ⊤⟙Ⲧ𐌕𝐓𝑇𝑻𝒯𝓣𝔗𝕋𝕿𝖳𝗧𝘛𝙏𝚃𝚻𝛕𝛵𝜏𝜯𝝉𝝩𝞃𝞣𝞽',
    'U': 'UՍሀᑌ∪⋃𝐔𝑈𝑼𝒰𝓤𝔘𝕌𝖀𝖴𝗨𝘜𝙐𝚄',
    'V': 'VѴ٧۷ᏙᐯⅤⴸ𝐕𝑉𝑽𝒱𝓥𝔙𝕍𝖁𝖵𝗩𝘝𝙑𝚅',
    'W': 'WԜᎳᏔ𝐖𝑊𝑾𝒲𝓦𝔚𝕎𝖂𝖶𝗪𝘞𝙒𝚆',
    'X': 'XΧХ᙭ᚷⅩ╳Ⲭⵝ𐌗𐌢𝐗𝑋𝑿𝒳𝓧𝔛𝕏𝖃𝖷𝗫𝘟𝙓𝚇𝚾𝛸𝜲𝝬𝞦',
    'Y': 'YΥϒУҮᎩᎽⲨ𝐘𝑌𝒀𝒴𝓨𝔜𝕐𝖄𝖸𝗬𝘠𝙔𝚈𝚼𝛶𝜰𝝪𝞤',
    'Z': 'ZΖᏃℤℨ𝐙𝑍𝒁𝒵𝓩𝖅𝖹𝗭𝘡𝙕𝚉𝚭𝛧𝜡𝝛𝞕',
    'a': 'aɑαа⍺𝐚𝑎𝒂𝒶𝓪𝔞𝕒𝖆𝖺𝗮𝘢𝙖𝚊𝛂𝛼𝜶𝝰𝞪',
    'b': 'bƄЬᏏᖯ𝐛𝑏𝒃𝒷𝓫𝔟𝕓𝖇𝖻𝗯𝘣𝙗𝚋',
    'c': 'cϲсᴄⅽⲥ𝐜𝑐𝒄𝒸𝓬𝔠𝕔𝖈𝖼𝗰𝘤𝙘𝚌',
    'd': 'ⅾdԁᏧᑯⅆⅾ𝐝𝑑𝒅𝒹𝓭𝔡𝕕𝖉𝖽𝗱𝘥𝙙𝚍',
    'e': 'eеҽ℮ℯⅇ𝐞𝑒𝒆𝓮𝔢𝕖𝖊𝖾𝗲𝘦𝙚𝚎ᥱ',
    'f': 'fſϝքẝ𝐟𝑓𝒇𝒻𝓯𝔣𝕗𝖋𝖿𝗳𝘧𝙛𝚏𝟋',
    'g': 'gƍɡցᶃℊ𝐠𝑔𝒈𝓰𝔤𝕘𝖌𝗀𝗴𝘨𝙜𝚐',
    'h': 'hһհᏂℎ𝐡𝒉𝒽𝓱𝔥𝕙𝖍𝗁𝗵𝘩𝙝𝚑',
    'i': 'iıɩɪιіӏᎥℹⅈⅰ⍳ꙇ𝐢𝑖𝒊𝒾𝓲𝔦𝕚𝖎𝗂𝗶𝘪𝙞𝚒𝚤𝛊𝜄𝜾𝝸𝞲',
    'j': 'jϳјⅉ𝐣𝑗𝒋𝒿𝓳𝔧𝕛𝖏𝗃𝗷𝘫𝙟𝚓',
    'k': 'k𝐤𝑘𝒌𝓀𝓴𝔨𝕜𝖐𝗄𝗸𝘬𝙠𝚔',
    'l': 'ⅼ',
    'm': 'ⅿm',
    'n': 'nոռ𝐧𝑛𝒏𝓃𝓷𝔫𝕟𝖓𝗇𝗻𝘯𝙣𝚗ᥒ',
    'o': 'ⲟഠοо',
    'p': 'pρϱр⍴ⲣ𝐩𝑝𝒑𝓅𝓹𝔭𝕡𝖕𝗉𝗽𝘱𝙥𝚙𝛒𝛠𝜌𝜚𝝆𝝔𝞀𝞎𝞺𝟈',
    'q': 'qԛգզ𝐪𝑞𝒒𝓆𝓺𝔮𝕢𝖖𝗊𝗾𝘲𝙦𝚚',
    'r': 'rгᴦⲅ𝐫𝑟𝒓𝓇𝓻𝔯𝕣𝖗𝗋𝗿𝘳𝙧𝚛',
    's': 'sƽѕꜱ𝐬𝑠𝒔𝓈𝓼𝔰𝕤𝖘𝗌𝘀𝘴𝙨𝚜',
    't': 't𝐭𝑡𝒕𝓉𝓽𝔱𝕥𝖙𝗍𝘁𝘵𝙩𝚝',
    'u': 'uʋυսᴜ𝐮𝑢𝒖𝓊𝓾𝔲𝕦𝖚𝗎𝘂𝘶𝙪𝚞𝛖𝜐𝝊𝞄𝞾ᥙ',
    'v': 'vνѵטᴠⅴ∨⋁𝐯𝑣𝒗𝓋𝓿𝔳𝕧𝖛𝗏𝘃𝘷𝙫𝚟𝛎𝜈𝝂𝝼𝞶',
    'w': 'wɯѡԝաᴡ𝐰𝑤𝒘𝓌𝔀𝔴𝕨𝖜𝗐𝘄𝘸𝙬𝚠',
    'x': 'x×хᕁᕽ᙮ⅹ⤫⤬⨯𝐱𝑥𝒙𝓍𝔁𝔵𝕩𝖝𝗑𝘅𝘹𝙭𝚡',
    'y': 'yɣʏγуүყᶌỿℽ𝐲𝑦𝒚𝓎𝔂𝔶𝕪𝖞𝗒𝘆𝘺𝙮𝚢𝛄𝛾𝜸𝝲𝞬',
    'z': 'zᴢ𝐳𝑧𝒛𝓏𝔃𝔷𝕫𝖟𝗓𝘇𝘻𝙯𝚣',
    '/': '᜵⁄∕⧸／',
    '\\': '⧵﹨⧹＼',
    ' ': '\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\xa0\u202f\u205f',
    '.': '․．',
    '-': '˗╴﹣－−⎼',
    '!': '﹗！ǃⵑ︕',
    ':': ':˸։፡᛬⁚∶⠆︓﹕',
    '#': '＃﹟'
}

def _prep_maketrans(data):
    from_s = ''
    to_s = ''
    for target, chars in data.items():
        from_s += chars
        to_s += target * len(chars)

    return str.maketrans(from_s, to_s)

UNICODE_CHARMAP = _prep_maketrans(_UNICODE_CHARMAP)

PUNISH_OPTIONS = ['kill', 'ban', 'quiet', 'kick', 'block']
EXEMPT_OPTIONS = ['voice', 'halfop', 'op']
DEFAULT_EXEMPT_OPTION = 'halfop'
def _punish(irc, target, channel, punishment, reason):
    """Punishes the target user. This function returns True if the user was successfully punished."""
    if target not in irc.users:
        log.warning("(%s) antispam: got target %r that isn't a user?", irc.name, target)
        return False
    elif irc.is_oper(target):
        log.debug("(%s) antispam: refusing to punish oper %s/%s", irc.name, target, irc.get_friendly_name(target))
        return False

    target_nick = irc.get_friendly_name(target)

    if channel:
        c = irc.channels[channel]
        exempt_level = irc.get_service_option('antispam', 'exempt_level', DEFAULT_EXEMPT_OPTION).lower()

        if exempt_level not in EXEMPT_OPTIONS:
            log.error('(%s) Antispam exempt %r is not a valid setting, '
                      'falling back to defaults; accepted settings include: %s',
                      irc.name, exempt_level, ', '.join(EXEMPT_OPTIONS))
            exempt_level = DEFAULT_EXEMPT_OPTION

        if exempt_level == 'voice' and c.is_voice_plus(target):
            log.debug("(%s) antispam: refusing to punish voiced and above %s/%s", irc.name, target, target_nick)
            return False
        elif exempt_level == 'halfop' and c.is_halfop_plus(target):
            log.debug("(%s) antispam: refusing to punish halfop and above %s/%s", irc.name, target, target_nick)
            return False
        elif exempt_level == 'op' and c.is_op_plus(target):
            log.debug("(%s) antispam: refusing to punish op and above %s/%s", irc.name, target, target_nick)
            return False

    my_uid = sbot.uids.get(irc.name)
    # XXX workaround for single-bot protocols like Clientbot
    if irc.pseudoclient and not irc.has_cap('can-spawn-clients'):
        my_uid = irc.pseudoclient.uid

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
    successful_punishments = 0
    for action in set(punishment.split('+')):
        if action not in PUNISH_OPTIONS:
            log.error('(%s) Antispam punishment %r is not a valid setting; '
                      'accepted settings include: %s OR any combination of '
                      'these joined together with a "+".',
                      irc.name, punishment, ', '.join(PUNISH_OPTIONS))
            return
        elif action == 'block':
            # We only need to increment this for this function to return True
            successful_punishments += 1
        elif action == 'kill':
            kill = True  # Delay kills so that the user data doesn't disappear.
        # XXX factorize these blocks
        elif action == 'kick' and channel:
            try:
                _kick()
            except NotImplementedError:
                log.warning("(%s) antispam: Kicks are not supported on this network, skipping; "
                            "target was %s/%s", irc.name, target_nick, channel)
            else:
                successful_punishments += 1
        elif action == 'ban' and channel:
            try:
                _ban()
            except (ValueError, NotImplementedError):
                log.warning("(%s) antispam: Bans are not supported on this network, skipping; "
                            "target was %s/%s", irc.name, target_nick, channel)
            else:
                successful_punishments += 1
        elif action == 'quiet' and channel:
            try:
                _quiet()
            except (ValueError, NotImplementedError):
                log.warning("(%s) antispam: Quiet is not supported on this network, skipping; "
                            "target was %s/%s", irc.name, target_nick, channel)
            else:
                successful_punishments += 1

    if bans:  # Set all bans at once to prevent spam
        irc.mode(my_uid, channel, bans)
        irc.call_hooks([my_uid, 'ANTISPAM_BAN',
                        {'target': channel, 'modes': bans, 'parse_as': 'MODE'}])
    if kill:
        try:
            _kill()
        except NotImplementedError:
            log.warning("(%s) antispam: Kills are not supported on this network, skipping; "
                        "target was %s/%s", irc.name, target_nick, channel)
        else:
            successful_punishments += 1

    if not successful_punishments:
        log.warning('(%s) antispam: Failed to punish %s with %r, target was %s', irc.name,
                    target_nick, punishment, channel or 'a PM')

    return bool(successful_punishments)

MASSHIGHLIGHT_DEFAULTS = {
    'min_length': 50,
    'min_nicks': 5,
    'reason': "Mass highlight spam is prohibited",
    'punishment': 'kick+ban',
    'enabled': False
}
def handle_masshighlight(irc, source, command, args):
    """Handles mass highlight attacks."""
    channel = args['target']
    text = args['text']
    mhl_settings = irc.get_service_option('antispam', 'masshighlight',
                                          MASSHIGHLIGHT_DEFAULTS)

    if not mhl_settings.get('enabled', False):
        return

    my_uid = sbot.uids.get(irc.name)

    # XXX workaround for single-bot protocols like Clientbot
    if irc.pseudoclient and not irc.has_cap('can-spawn-clients'):
        my_uid = irc.pseudoclient.uid

    if (not irc.connected.is_set()) or (not my_uid):
        # Break if the network isn't ready.
        log.debug("(%s) antispam.masshighlight: skipping processing; network isn't ready", irc.name)
        return
    elif not irc.is_channel(channel):
        # Not a channel - mass highlight blocking only makes sense within channels
        log.debug("(%s) antispam.masshighlight: skipping processing; %r is not a channel", irc.name, channel)
        return
    elif irc.is_internal_client(source):
        # Ignore messages from our own clients.
        log.debug("(%s) antispam.masshighlight: skipping processing message from internal client %s", irc.name, source)
        return
    elif source not in irc.users:
        log.debug("(%s) antispam.masshighlight: ignoring message from non-user %s", irc.name, source)
        return
    elif channel not in irc.channels or my_uid not in irc.channels[channel].users:
        # We're not monitoring this channel.
        log.debug("(%s) antispam.masshighlight: skipping processing message from channel %r we're not in", irc.name, channel)
        return
    elif len(text) < mhl_settings.get('min_length', MASSHIGHLIGHT_DEFAULTS['min_length']):
        log.debug("(%s) antispam.masshighlight: skipping processing message %r; it's too short", irc.name, text)
        return

    if irc.get_service_option('antispam', 'strip_formatting', True):
        text = utils.strip_irc_formatting(text)

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
            # Get the punishment and reason.
            punishment = mhl_settings.get('punishment', MASSHIGHLIGHT_DEFAULTS['punishment']).lower()
            reason = mhl_settings.get('reason', MASSHIGHLIGHT_DEFAULTS['reason'])

            log.info("(%s) antispam: punishing %s => %s for mass highlight spam",
                     irc.name,
                     irc.get_friendly_name(source),
                     channel)
            punished = _punish(irc, source, channel, punishment, reason)
            break

    log.debug('(%s) antispam.masshighlight: got %s/%s nicks on message to %r', irc.name,
              len(nicks_caught), min_nicks, channel)
    return not punished  # Filter this message from relay, etc. if it triggered protection

utils.add_hook(handle_masshighlight, 'PRIVMSG', priority=1000)
utils.add_hook(handle_masshighlight, 'NOTICE', priority=1000)

TEXTFILTER_DEFAULTS = {
    'reason': "Spam is prohibited",
    'punishment': 'kick+ban+block',
    'watch_pms': False,
    'enabled': False,
    'munge_unicode': True,
}
def handle_textfilter(irc, source, command, args):
    """Antispam text filter handler."""
    target = args['target']
    text = args['text']
    txf_settings = irc.get_service_option('antispam', 'textfilter',
                                          TEXTFILTER_DEFAULTS)

    if not txf_settings.get('enabled', False):
        return

    my_uid = sbot.uids.get(irc.name)

    # XXX workaround for single-bot protocols like Clientbot
    if irc.pseudoclient and not irc.has_cap('can-spawn-clients'):
        my_uid = irc.pseudoclient.uid

    if (not irc.connected.is_set()) or (not my_uid):
        # Break if the network isn't ready.
        log.debug("(%s) antispam.textfilters: skipping processing; network isn't ready", irc.name)
        return
    elif irc.is_internal_client(source):
        # Ignore messages from our own clients.
        log.debug("(%s) antispam.textfilters: skipping processing message from internal client %s", irc.name, source)
        return
    elif source not in irc.users:
        log.debug("(%s) antispam.textfilters: ignoring message from non-user %s", irc.name, source)
        return

    if irc.is_channel(target):
        channel_or_none = target
        if target not in irc.channels or my_uid not in irc.channels[target].users:
            # We're not monitoring this channel.
            log.debug("(%s) antispam.textfilters: skipping processing message from channel %r we're not in", irc.name, target)
            return
    else:
        channel_or_none = None
        watch_pms = txf_settings.get('watch_pms', TEXTFILTER_DEFAULTS['watch_pms'])

        if watch_pms == 'services':
            if not irc.get_service_bot(target):
                log.debug("(%s) antispam.textfilters: skipping processing; %r is not a service bot (watch_pms='services')", irc.name, target)
                return
        elif watch_pms == 'all':
            log.debug("(%s) antispam.textfilters: checking all PMs (watch_pms='all')", irc.name)
            pass
        else:
            # Not a channel.
            log.debug("(%s) antispam.textfilters: skipping processing; %r is not a channel and watch_pms is disabled", irc.name, target)
            return

    # Merge together global and local textfilter lists.
    txf_globs = set(conf.conf.get('antispam', {}).get('textfilter_globs', [])) | \
                set(irc.serverdata.get('antispam_textfilter_globs', []))

    punishment = txf_settings.get('punishment', TEXTFILTER_DEFAULTS['punishment']).lower()
    reason = txf_settings.get('reason', TEXTFILTER_DEFAULTS['reason'])

    if irc.get_service_option('antispam', 'strip_formatting', True):
        text = utils.strip_irc_formatting(text)
    if txf_settings.get('munge_unicode', TEXTFILTER_DEFAULTS['munge_unicode']):
        text = str.translate(text, UNICODE_CHARMAP)

    punished = False
    for filterglob in txf_globs:
        if utils.match_text(filterglob, text):
            log.info("(%s) antispam: punishing %s => %s for text filter %r",
                     irc.name,
                     irc.get_friendly_name(source),
                     irc.get_friendly_name(target),
                     filterglob)
            punished = _punish(irc, source, channel_or_none, punishment, reason)
            break

    return not punished  # Filter this message from relay, etc. if it triggered protection

utils.add_hook(handle_textfilter, 'PRIVMSG', priority=999)
utils.add_hook(handle_textfilter, 'NOTICE', priority=999)

PARTQUIT_DEFAULTS = {
    'watch_quits': True,
    'watch_parts': True,
    'part_filter_message': "Reason filtered",
    'quit_filter_message': "Reason filtered",
}
def handle_partquit(irc, source, command, args):
    """Antispam part/quit message filter."""
    text = args.get('text')
    pq_settings = irc.get_service_option('antispam', 'partquit',
                                         PARTQUIT_DEFAULTS)

    if not text:
        return  # No text to match against
    elif command == 'QUIT' and not pq_settings.get('watch_quits', True):
        return  # Not enabled
    elif command == 'PART' and not pq_settings.get('watch_parts', True):
        return

    # Merge together global and local partquit filter lists.
    pq_globs = set(conf.conf.get('antispam', {}).get('partquit_globs', [])) | \
               set(irc.serverdata.get('antispam_partquit_globs', []))
    if not pq_globs:
        return

    for filterglob in pq_globs:
        if utils.match_text(filterglob, text):
            # For parts, also log the affected channels
            if command == 'PART':
                filtered_message = pq_settings.get('part_filter_message', PARTQUIT_DEFAULTS['part_filter_message'])
                log.info('(%s) antispam: filtered part message from %s on %s due to part/quit filter glob %s',
                         irc.name, irc.get_hostmask(source), ','.join(args['channels']), filterglob)
            else:
                filtered_message = pq_settings.get('quit_filter_message', PARTQUIT_DEFAULTS['quit_filter_message'])
                log.info('(%s) antispam: filtered quit message from %s due to part/quit filter glob %s',
                         irc.name, args['userdata'].nick, filterglob)
            args['text'] = filtered_message
            break
utils.add_hook(handle_partquit, 'PART', priority=999)
utils.add_hook(handle_partquit, 'QUIT', priority=999)
