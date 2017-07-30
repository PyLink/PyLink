# PyLink FAQ

### I get errors like "ImportError: No module named 'yaml'" when I start PyLink

You are missing dependencies - re-read https://github.com/GLolol/PyLink/blob/master/README.md#installation

### I get errors like "yaml.scanner.ScannerError: while scanning for the next token, found character '\t' that cannot start any token"

You must use SPACES and not tabs in your configuration! (`\t` is the escaped code for a tab, which is disallowed by YAML)

### I turned autoconnect for PyLink on, and now I'm getting errors!

PyLink does not support inbound connections - much like regular services such as Atheme or Anope, it only connects outwards *to* IRCds. (If you don't understand what this means, it means you should turn autoconnect OFF for PyLink)

### Clientbot doesn't relay both ways!

Load the `relay_clientbot` plugin. https://github.com/GLolol/PyLink/blob/e1fab8c/example-conf.yml#L303-L306

### Does everyone need to install PyLink Relay for it to work?

**No!** Only the PyLink administrator needs to host a PyLink instance, as each can connect to multiple networks. Everyone else only needs to add a link block on their IRCd.

InterJanus-style links between PyLink daemons are not supported yet; see https://github.com/GLolol/PyLink/issues/99 for any progress regarding that.

### What are PyLink's advantages over Janus?

PyLink provides, in no particular order:
- More complete support for modern IRCds (UnrealIRCd 4.x, InspIRCd 2.0, charybdis 4, Nefarious IRCu, etc.).
- A flexible, maintainable codebase extensible beyond Relay.
- Cross platform functionality (*nix, Windows, and probably others too).
- Proper protocol negotiation leading to fewer SQUIT/DoS possibilities:
    - Better support for channel modes such as +fjMOR, etc.
    - Proper support for nick length limits with relayed users.

### My IRCd SQUITs the relay server with errors like "Bad nickname introduced"!

First, check whether the SQUIT message includes the nick that triggered the netsplit. If this nick includes any characters not allowed in regular IRC, such as the slash ("/"), or is otherwise an invalid nick (e.g. beginning with a hyphen or number), this likely indicates a bug in PyLink Relay. These problems should be reported on the issue tracker!

However, if the nick mentioned is legal on IRC, this issue is likely caused by a max nick length misconfiguration: i.e. the relay server is introducing nicks too long for the target network. This can be fixed by setting the `maxnicklen` option in the affected network's PyLink `server:` block to the same value as that network's `005` `NICKLEN` (that is, the `NICKLEN=<num>` value in `/raw version`).
