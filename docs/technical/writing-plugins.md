# Writing plugins for PyLink

Most features in PyLink (Relay, Automode, etc.) are implemented as plugins, which can be mix-and-matched on any particular instance. Without any plugins loaded, PyLink can connect to servers but won't accomplish anything useful.

This guide, along with the sample plugin [`example.py`](../../plugins/example.py) aim to show the basics of writing plugins for PyLink.

## Receiving data from IRC

Plugins have two ways of communicating with IRC: hooks, and commands directed towards service clients. Any plugin can use one or a combination of these.

### Hook events

PyLink's hooks system is designed as a protocol-independent method for protocol modules to communicate with plugins (and to a lesser extend, for plugins to communicate with each other). Hook events are the most versatile form of communication available, with each individual event generally corresponding to a specific chat or server event (e.g. `PRIVMSG`, `JOIN`, `KICK`). Each hook payload includes 4 parts:

1) The corresponding network object (IRC object) where the event took place (**type**: a subclass of `pylinkirc.classes.PyLinkNetworkCore`)
2) The numeric ID† of the sender (**type**: `str`)
3) An identifier for the command name, which may or may not be the same as the name of the hook depending on context (**type**: `str`)
4) A freeform `dict` of arguments, where data keys vary by command - see the [PyLink hooks reference](hooks-reference.md) for what's available where.

Functions intended to be hook handlers therefore take in 4 arguments corresponding to the ones listed above: `irc`, `source`, `command`, and `args`.

#### Return codes for hook handlers

As of PyLink 2.0-alpha3, the return value of hook handlers are used to determine how the original event will be passed on to further handlers (that is, those created by plugins loaded later, or hook handlers registered with a lower priority).

The following return values are supported so far:

- `None` or `True`: passthrough the event unchanged to further handlers (the default behavior)
- `False`: block the event from reaching other handlers

Hook handlers may raise exceptions without blocking the event from reaching further handlers; these are caught by PyLink and logged appropriately.

### Hook priorities
TODO

### Bot commands

Plugins can also define service bot commands, either for the main PyLink service bot or for one created by the plugin itself. This section only details the former - see the [Services API Guide](services-api.md) for details on the latter.

Commands are registered by calling `utils.add_cmd()` with one or two arguments. Ex)
- `utils.add_cmd(testcommand, "hello")` registers a function named `testcommand` as the command handler for `hello` (i.e. `/msg PyLink hello`)
- `utils.add_cmd(testcommand)` registers a function named `testcommand` as the command handler for `testcommand`.

`utils.add_cmd(...)` also takes some keyword arguments, described in the [services API guide](services-api.md#service-bots-and-commands) (replace `myservice.add_cmd` with `utils.add_cmd`). Decorator syntax (`@utils.add_cmd`) can also be used for the second example above.


Each command handler function takes 3 arguments: `irc, source, args`.
- **irc**: The network object where the command was called.
- **source**: The numeric ID (or pseudo-ID) of the sender.
- **args**: A `list` of command arguments (not including the command name) that the command was called with. For example, `/msg PyLink hello world 1234` would give an `args` list of `['world', '1234']`

As of PyLink 1.2, there are two ways for a plugin to parse arguments: as a raw list of strings, or with `utils.IRCParser` (an [argparse](https://docs.python.org/3/library/argparse.html) wrapper). `IRCParser()` is documented in the ["using IRCParser"](using-ircparser.md) page.

Command handlers do not return anything and can raise exceptions, which are caught by the core and automatically return an error message.

## Sending data to IRC

Plugins receive data from the underlying protocol module, and communicate back using outgoing [command functions](pmodule-spec.md) implemented by the protocol module. They should *never* send raw data directly back to IRC, because that wouldn't be portable across different IRCds.

These functions are called in the form: `irc.command(arg1, arg2, ...)`. For example, the command `irc.join('10XAAAAAB', '#bots')` would join a PyLink client with UID `10XAAAAAB` to the channel `#bots`.

For sending messages (e.g. replies to commands), simpler forms of:

- `irc.reply(text, notice=False, source=None)`
- `irc.error(text, notice=False, source=None)`
- and `irc.msg(targetUID, text, notice=False, source=None)`

are preferred.

`irc.reply()` is a frontend to `irc.msg()` which automatically finds the right target to reply to: that is, the channel for fantasy commands and the caller for PMs. `irc.error()` is in turn a wrapper around `irc.reply()` which prefixes the given text with `Error: `.

The sender UID for all of these can be set using the `source` argument, and defaults to the main PyLink client.

## Access checking for commands

See the [Permissions API documentation](permissions-api.md) on how to restrict commands to certain users.

## Special triggers for plugin (un)loading

The following functions can also be defined in the body of a plugin to hook onto plugin loading / unloading.

- `main(irc=None)`: Called on plugin load. `irc` is only defined when the plugin is being reloaded from a network: otherwise, it means that PyLink has just been started.
- `die(irc=None)`: Called on plugin unload or daemon shutdown. `irc` is only defined when the shutdown or unload was called from an IRC network.

## Other tips

### Logging

Use PyLink's [global logger](https://docs.python.org/3/library/logging.html) (`from pylinkirc.log import log`) instead of print statements.

### Some useful attributes

- **`world.networkobjects`** provides a dict mapping network names (case sensitive) to their corresponding network objects/protocol module instances.
- **`irc.connected`** is a [`threading.Event()`](https://docs.python.org/3/library/threading.html#event-objects) object that is set when a network finishes bursting.
- `world.started` is a [`threading.Event()`](https://docs.python.org/3/library/threading.html#event-objects) object that is set when all networks have been initialized.
- `world.plugins` provides a dict mapping loaded plugins' names (case sensitive) to their module objects. This is the preferred way to call another plugins's methods if need be (while of course, forcing you to check whether the other plugin is already loaded).
- `world.services` provides a dict mapping service bot names to their `utils.ServiceBot` instances.

### Useful modules

`classes.py`, `utils.py` and `structures.py` all provide a ton of public methods which aren't documented here for conciseness. In `classes.py`, `PyLinkNetworkCore` and `PyLinkNetworkCoreUtils` (which all protocol modules inherit from) are where many utility and state-checking functions sit.
