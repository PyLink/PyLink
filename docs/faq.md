# PyLink FAQ

### I get errors like "ImportError: No module named 'yaml'" when I start PyLink

You are missing dependencies - re-read https://github.com/GLolol/PyLink#dependencies

### I get errors like "yaml.scanner.ScannerError: while scanning for the next token, found character '\t' that cannot start any token"

You must use SPACES and not tabs in your configuration! (`\t` is the escaped code for a tab, which is disallowed by YAML)

### I turned autoconnect for PyLink on, and now I'm getting errors!

PyLink does not support inbound connections - much like regular services such as Atheme or Anope, it only connects outwards *to* IRCds. (If you don't understand what this means, it means you should turn autoconnect OFF for PyLink)

### Does PyLink support Clientbot relay like Janus?

Yes. However, Clientbot support is in alpha stages as of PyLink 0.10 and is far from complete: [Clientbot TODO](https://github.com/GLolol/PyLink/issues?q=is%3Aissue+is%3Aopen+label%3Aprotocols%2Fclientbot).

### Clientbot doesn't relay both ways!

Load the `relay_clientbot` plugin. https://github.com/GLolol/PyLink/blob/e1fab8c/example-conf.yml#L303-L306

### Does everyone need to install PyLink Relay for it to work?

**No!** Only the PyLink administrator needs to host a PyLink instance, as each can connect to multiple networks. Everyone else only needs to add a link block on their IRCd.

InterJanus-style links between PyLink daemons are not supported yet; see https://github.com/GLolol/PyLink/issues/99 for any progress regarding that.

### What are PyLink Relay's benefits over Janus?

In no particular order:
- More complete support for modern IRCds (UnrealIRCd 4.x, InspIRCd 2.0, charybdis 4, Nefarious IRCu, etc.).
- PyLink is built upon a flexible, maintainable codebase.
- Cross platform (*nix, Windows, and probably others too).
- Proper protocol negotiation leading to fewer DoS possibilities:
    - Better support for channel modes such as +fjMOR, etc.
    - Configurable nick length limits for relayed users.
