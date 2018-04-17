# Advanced Configuration for PyLink Relay

PyLink Relay provides a few advanced configuration options not documented in the example configuration, either because they have limited use, or are too complicated to be described briefly.

**This guide assumes that you are relatively familiar with the way YAML syntax works (lists, named arrays/dicts, etc.).** For the purposes of this document, configuration options will be referred to in the format `a::b::c`, which represents the "`c`" configuration key in a "`b`" block, all within an "`a`" block.

### Custom Clientbot Styles

Custom Clientbot styles can be applied for any of Clientbot's supported events, by defining keys in the format `relay::clientbot_styles::<event name>`. See below for a list of supported events and their default values (as of 1.3-beta1).

These options take template strings as documented here: https://docs.python.org/3/library/string.html#template-strings. Supported substitution values differ by event, but usually include the [hook values for each](technical/hooks-reference.md#irc-command-hooks), *plus* the following:

- For all events:
    - `$netname`: origin network name
    - `$sender`: nick of sender
    - `$sender_identhost`: ident@host string of sender
    - `$colored_sender`: color hashed version of `$sender`
    - `$colored_netname`: color hashed version of `$netname`
- For KICK, and other events that have a `$target` field corresponding to a user:
    - `$target_nick`: nick of target (as opposed to `$target`, which is an UID)
- For events that have a `$channel` field attached (e.g. JOIN, PART):
    - `$local_channel`: the LOCAL channel name (of the clientbot network)
    - `$channel`: the real channel on the sender's network
- For SJOIN, SQUIT:
    - `$nicks`: a comma-joined list of nicks that were bursted
    - `$colored_nicks`: a comma-joined list of each bursted nick, color hashed

To disable relaying for any specific event, set the template string to an empty string (`''`).

#### List of supported events

|Event name|Default value|
| :---: | :--- |
MESSAGE  | \x02[$colored\_netname]\x02 <$colored\_sender> $text
KICK     | \x02[$colored\_netname]\x02 - $colored_sender$sender\_identhost has kicked $target_nick from $channel ($text)
PART     | \x02[$colored\_netname]\x02 - $colored_sender$sender\_identhost has left $channel ($text)
JOIN     | \x02[$colored\_netname]\x02 - $colored_sender$sender\_identhost has joined $channel
NICK     | \x02[$colored\_netname]\x02 - $colored_sender$sender\_identhost is now known as $newnick
QUIT     | \x02[$colored\_netname]\x02 - $colored_sender$sender\_identhost has quit ($text)
ACTION   | \x02[$colored\_netname]\x02 * $colored\_sender $text
NOTICE   | \x02[$colored\_netname]\x02 - Notice from $colored\_sender: $text
SQUIT    | \x02[$colored\_netname]\x02 - Netsplit lost users: $colored\_nicks
SJOIN    | \x02[$colored\_netname]\x02 - Netjoin gained users: $colored\_nicks
PM       | PM from $sender on $netname: $text
PNOTICE  | <$sender> $text

- Note: the `PM` and `PNOTICE` events represent private messages and private notices respectively, when they're relayed to users behind a Clientbot link.
- Note 2: as of 1.1.x, all public channel events are sent to channels as PRIVMSG, while `PM` and `PNOTICE` are relayed privately as NOTICE.

### Misc. options
- `relay::clientbot_startup_delay`: Defines the amount of seconds Clientbot should wait after startup, before relaying any non-PRIVMSG events. This is used to prevent excess floods when the bot connects. Defaults to 5 seconds.
- `servers::NETNAME::relay_force_slashes`: This network specific option forces Relay to use `/` in nickname separators. You should only use this option on TS6 or P10 variants that are less strict with nickname validation, as **it will cause protocol violations** on most IRCds. UnrealIRCd and InspIRCd users do not need to set this either, as `/` in nicks is automatically enabled.
