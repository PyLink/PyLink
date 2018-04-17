# Advanced Configuration for PyLink Relay

PyLink Relay provides a few configuration options not documented in the example configuration, either because they have limited use or are too complicated to be described briefly.

**This guide assumes that you are relatively familiar with the way YAML syntax works (lists, named arrays/dicts, etc.).** In this document, configuration options will be referred to in the format `a::b::c`, which represents the "`c`" option inside a "`b`" config block, all within an "`a`" config block.

In actual YAML, that translates to this:

```yaml
a:
    b:
        c: "some value"
```

### Custom Clientbot Styles

Custom Clientbot styles can be applied for any of Clientbot's supported events, by defining keys in the format `relay::clientbot_styles::<event name>`. See below for a list of supported events and their default values (as of 1.3-beta1).

These options take template strings as documented here: https://docs.python.org/3/library/string.html#template-strings. Supported substitution values differ by event, but usually include the [hook values for each](technical/hooks-reference.md#irc-command-hooks), *plus* the following:

- For all events:
    - `$netname`: origin network name
    - `$sender`: nick of sender
    - `$sender_identhost`: ident@host string of the sender
    - `$colored_sender`: color hashed version of `$sender`
    - `$colored_netname`: color hashed version of `$netname`
- For KICK, and other events that have a `$target` field corresponding to a user:
    - `$target_nick`: the nick of the target (as opposed to `$target`, which is an user ID)
- For events that have a `$channel` field attached (e.g. JOIN, PART):
    - `$local_channel`: the *local* channel name (i.e. the channel on the clientbot network)
    - `$channel`: the real channel name on the sender's network
- For SJOIN, SQUIT:
    - `$nicks`: a comma-joined list of nicks that were bursted
    - `$colored_nicks`: a comma-joined list of each bursted nick, color hashed

To disable relaying for any specific event, set the template string to an empty string (`''`).

To disable color for all events, see [here](https://github.com/GLolol/PyLink/blob/master/docs/advanced-relay-config.md#custom-clientbot-styles)
```yaml

# ...
server:
  # ...
    #...
relay:
  clientbot_styles:
    # ...
plugins:
  # ...
```

#### List of supported events

| Event name | Default value|
| :--------: | :----------- |
ACTION   | \x02[$colored\_netname]\x02 * $colored\_sender $text
JOIN     | \x02[$colored\_netname]\x02 - $colored_sender$sender\_identhost has joined $channel
KICK     | \x02[$colored\_netname]\x02 - $colored_sender$sender\_identhost has kicked $target_nick from $channel ($text)
MESSAGE  | \x02[$colored\_netname]\x02 <$colored\_sender> $text
NICK     | \x02[$colored\_netname]\x02 - $colored_sender$sender\_identhost is now known as $newnick
NOTICE   | \x02[$colored\_netname]\x02 - Notice from $colored\_sender: $text
PART     | \x02[$colored\_netname]\x02 - $colored_sender$sender\_identhost has left $channel ($text)
PM       | PM from $sender on $netname: $text
PNOTICE  | <$sender> $text
QUIT     | \x02[$colored\_netname]\x02 - $colored_sender$sender\_identhost has quit ($text)
SJOIN    | \x02[$colored\_netname]\x02 - Netjoin gained users: $colored\_nicks
SQUIT    | \x02[$colored\_netname]\x02 - Netsplit lost users: $colored\_nicks

- Note: the `PM` and `PNOTICE` events represent private messages and private notices respectively, when they're relayed to users behind a Clientbot link.
- Note 2: as of 1.1.x, all public channel events are sent to channels as PRIVMSG, while `PM` and `PNOTICE` are relayed privately as NOTICE.

### Misc. options
- `relay::clientbot_startup_delay`: Defines the amount of seconds Clientbot should wait after startup, before relaying any non-PRIVMSG events. This is used to prevent excess floods when the bot connects. Defaults to 5 seconds.
- `servers::NETNAME::relay_force_slashes`: This network specific option forces Relay to use `/` in nickname separators. You should only use this option on TS6 or P10 variants that are less strict with nickname validation, as **it will cause protocol violations** on most IRCds. UnrealIRCd and InspIRCd users do not need to set this either, as `/` in nicks is automatically enabled.

### Disabling Color/Control Codes

If you don't want the messages PyLink sends for clientbot messages to be emboldened or colored,
then remove the 'escape sequences' seen as `\x02` etc. This also includes colored varients of certain substitutions.
These are what style the strings.

Or you can use the following, its a stripped version of the default template.
Place it inside the `relay::` block as seen above.

```yaml
  clientbot_styles:
    ACTION: "[$netname] * $sender $text"
    JOIN: "[$netname] - $sender$sender_identhost has joined $channel"
    KICK: "[$netname] - $sender$sender_identhost has kicked $target_nick from $channel ($text)"
    MESSAGE: "[$netname] <$sender> $text"
    NICK: "[$netname] - $sender$sender_identhost is now known as $newnick"
    NOTICE: "[$netname] - Notice from $sender: $text"
    PART: "[$netname] - $sender$sender_identhost has left $channel ($text)"
    PM: "PM from $sender on $netname: $text"
    PNOTICE: "<$sender> $text"
    QUIT: "[$netname] - $sender$sender_identhost has quit ($text)"
    SJOIN: "[$netname] - Netjoin gained users: $nicks"
    SQUIT: "[$netname] - Netsplit lost users: $nicks"
```
