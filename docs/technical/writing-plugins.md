# Writing plugins for PyLink

PyLink plugins are modules that extend its functionality by giving it something to do. Without any plugins loaded, PyLink can only sit on a server and do absolutely nothing.

This guide, along with the sample plugins [`plugins/example.py`](../../plugins/example.py), and [`plugins/service.py`](../../plugins/demo_service.py) aim to show the basics of writing plugins for PyLink.

## Receiving data from IRC

Plugins have two ways of communicating with IRC: hooks, and commands sent in PM to the main PyLink client. A simple plugin can use one, or any mixture of these.

### Hooks

Hooks are probably the most versatile form of communication. The data in each hook payload is formatted as a Python `dict`, with different data keys depending on the command.
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

### Bot commands

For plugins that interact with regular users, you can also write commands for the PyLink bot, or [create service bots with their own command set](services-api.md). This section only details the former:

Plugins can add commands by including something like `utils.add_cmd(testcommand, "hello")`. Here, `testcommand` is the name of your function, and `hello` is the (optional) name of the command. If no command name is specified, it will use the same name as the function.
Now, your command function will be called whenever someone PMs the PyLink client with the command (e.g. `/msg PyLink hello`, case-insensitive).

Each command function takes 3 arguments: `irc, source, args`.
- **irc**: The IRC object where the command was called.
- **source**: The numeric of the sender. This will usually be a UID (for users) or a SID (for server).
- **args**: A `list` of space-separated command arguments (excluding the command name) that the command was called with. For example, `/msg PyLink hello world 1234` would give an `args` list of `['world', '1234']`

(Unfortunately, this means that for now, any fancy argument parsing has to be done manually.)

Command handlers do not return anything and can raise exceptions, which are caught by the core and automatically return an error message.

## Sending data to IRC

Plugins receive data from the underlying protocol module, and communicate back using outgoing [command functions](pmodule-spec.md) implemented by the protocol module. They should *never* send raw data directly back to IRC, because that wouldn't be portable across different IRCds.

These functions are usually called in this fashion: `irc.proto.command(arg1, arg2, ...)`. For example, the command `irc.proto.join('10XAAAAAB', '#bots')` would join a PyLink client with UID `10XAAAAAB` to channel `#bots`.

For sending messages (e.g. replies to commands), simpler forms of:

- `irc.reply(text, notice=False, source=None)`
- and `irc.msg(targetUID, text, notice=False, source=None)`

are preferred.

`irc.reply()` is a special form of `irc.msg` in that it automatically finds the target to reply to. If the command was called in a channel using fantasy, it will send the reply in that channel. Otherwise, the reply will be sent in a PM to the caller.

The sender UID for both can be set using the `source` argument, and defaults to the main PyLink client.

## Special triggers for plugin (un)loading

The following functions can also be defined in the body of a plugin to hook onto plugin loading / unloading.

`main(irc=None)`: Called on plugin load. `irc` is only defined when the plugin is being reloaded from a network: otherwise, it means that PyLink has just been started.
`die(irc=None)`: Called on plugin unload or daemon shutdown. `irc` is only defined when the shutdown or unload was called from an IRC network.
