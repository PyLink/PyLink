# PyLink FAQ

### Does everyone need to install PyLink Relay for it to work?

**No!** Only the link administrator needs to host a PyLink instance, as each can connect to multiple networks. Everyone else only needs to add a link block on their IRCd.

InterJanus-style links between PyLink daemons are not supported yet; see https://github.com/GLolol/PyLink/issues/99 for progress regarding that.

### Does PyLink support Clientbot relay like Janus?

Not yet; see https://github.com/GLolol/PyLink/issues/144

### What are PyLink Relay's benefits over Janus?

In no particular order:
- More complete support for modern IRCds (UnrealIRCd 4.x, InspIRCd 2.0, charybdis 4, Nefarious IRCu, etc.).
- Built upon a flexible, maintainable codebase.
- Cross platform (*nix and Windows).
- Proper protocol negotiation: better support for channel modes (+fjMOR, etc.), nick length limits, and WHOIS.

### I turned autoconnect for PyLink on, and now I'm getting errors!

PyLink does not support inbound connections - much like Atheme or Anope, it only connects outwards to IRCds. (If you don't understand what this means, it means you should turn autoconnect OFF for PyLink)

### I get errors like "ImportError: No module named 'yaml'" when I start PyLink
- You are missing dependencies - re-read https://github.com/GLolol/PyLink#installing-from-source-recommended
