# Writing plugins for PyLink

PyLink plugins are modules that extend its functionality by giving it something to do. Without any plugins loaded, PyLink can only sit on a server and do absolutely nothing.

This guide, along with the sample plugin [`plugin_example.py`](plugin_example.py), aim to show the basics of writing plugins for PyLink.

### Receiving data from IRC

Plugins have three main ways of communicating with IRC: hooks, WHOIS handlers, and commands sent in PM to the main PyLink client. A simple plugin can use one, or any mixture of these.

### Hooks

Hooks are probably the most versatile form of communication. Each hook payload is formatted as a Python `dict`, with different data keys depending on the command.
For example, a `PRIVMSG` payload would give you the fields `target` and `text`, while a `PART` payload would only give you `channels` and `reason` fields.

There are many hook types available (one for each supported IRC command), and you can read more about them in the [PyLink hooks reference](hooks-reference.md).

Plugins can bind to hooks using the `utils.add_hook()` function like so: `utils.add_hook(function_name, 'PRIVMSG')`, where `function_name` is your function definition, and `PRIVMSG` is whatever hook name you want to bind to. Once set up, `function_name` will be called whenever the protocol module receives a `PRIVMSG` command.

Each hook-bound function takes 4 arguments: `irc, source, command, args`.
- **irc**: The IRC object where the hook was called. Plugins are globally loaded, so there will be one of these per network.
- **source**: The numeric of the sender. This will usually be a UID (for users) or a SID (for server).
- **command**: The true command name where the hook originates. This may or may not be the same as the name of the hook, depending on context.
- **args**: The hook data (a `dict`) associated with the command. Again, the available data keys differ by hook name
(see the [hooks reference](hooks-reference.md) for a list of which can be used).

Hook functions do not return anything, and can raise exceptions to be caught by the core.

### PyLink commands

For plugins that interact with IRC users, there is also the option of binding to PM commands.

Commands are bound to using the `utils.add_cmd()` function: `utils.add_cmd(testcommand, "hello")`. Here, `testcommand` is the name of your function, and `hello` is the (optional) name of the command to bind to; if it is not specified, it'll use the same name as the function.
Now, your command function will be called whenever someone PMs the PyLink client with the command (e.g. `/msg PyLink hello`, case-insensitive).

Each command function takes 3 arguments: `irc, source, args`.
- **irc**: The IRC object where the command was called.
- **source**: The numeric of the sender. This will usually be a UID (for users) or a SID (for server).
- **args**: A `list` of space-separated command args (excluding the command name) that the command was called with. For example, `/msg PyLink hello world 1234` would give an `args` list of `['world', '1234']`

Command handlers do not return anything and can raise exceptions, which are caught by the core and automatically return an error message.

### WHOIS handlers

The third option, `WHOIS` handlers, are a lot more limited compared to the other options. They are solely used for `WHOIS` replies, **and only work on IRCds where WHOIS commands are sent to remote servers!** This includes Charybdis and UnrealIRCd, but **not** InspIRCd, which handles all `WHOIS` requests locally (the only thing sent between servers is an IDLE time query).

WHOIS replies are special in that any plugins wishing to add lines to a WHOIS reply must do so after the regular WHOIS lines (handled by the core), but before a special "End of WHOIS" line. This means that the regular hooks mechanism, which are only called after core handling, doesn't work here.

An example of a plugin WHOIS handler is in the relay plugin. WHOIS handler functions are added to the `world.whois_handlers` list using a simple `append()`. They should return either nothing or a two-length list: the first item being the WHOIS numeric, and the second the raw whois text.

```
def relayWhoisHandler(irc, target):
    user = irc.users[target]
    orig = getLocalUser(irc, target)
    if orig:
        network, remoteuid = orig
        remotenick = world.networkobjects[network].users[remoteuid].nick
        return [320, "%s :is a remote user connected via PyLink Relay. Home "
                     "network: %s; Home nick: %s" % (user.nick, network,
                                                     remotenick)]
world.whois_handlers.append(relayWhoisHandler)
```

### Sending data to IRC

Plugins receive data from the underlying protocol module, and communicate back using outgoing [command functions](pmodule-spec.md) implemented by the protocol module. They should *never* send raw data directly back to IRC, because that wouldn't be portable across different IRCds.

These functions are usually called in this fashion: `irc.proto.abcdClient(arg1, arg2)`. For example, the command `irc.proto.joinClient('10XAAAAAB', '#bots')` would join a PyLink client with UID `10XAAAAAB` to channel `#bots`.

For sending messages (e.g. replies to commands), a simpler form of `irc.msg(targetUID, text, notice=False, source=None)` is also used. The sender UID can be set here with the `source` argument, and defaults to the main PyLink client.
