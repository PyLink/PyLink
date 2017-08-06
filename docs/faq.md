# PyLink FAQ

## Startup errors

### I get errors like "ImportError: No module named 'yaml'" when I start PyLink

You are missing dependencies - re-read https://github.com/GLolol/PyLink/blob/master/README.md#installation

### I get errors like "yaml.scanner.ScannerError: while scanning for the next token, found character '\t' that cannot start any token"

You must use **spaces** and not tabs to indent your configuration file! (`\t` is the escaped code for a tab, which is disallowed by YAML)

## Linking / Connection issues

### PyLink won't connect to my network!

As a general guide, you should check the following before asking for support:

- Is the target network's IRCd showing failed connection attempts?
    - If not:
        1) Is PyLink connecting to the right port (i.e. one the IRCd is listening on?)
        2) Is the target network's IRCd actually binding to the port you're trying to use? If there is a port conflict with another program, the IRCd may fail to bind but *still start* on other ports that are free.
        3) Is the target port firewalled on the target machine?
        4) Is there a working connection between the source and target servers? Use ping to test this, as sometimes routing issues between providers can cause servers to become unreachable.
            - If your servers are purposely blocking ping, it's up to you to find another way to test this! 😬

    - If so:
        1) Check for recvpass/sendpass/server hostname/IP mismatches - usually the IRCd will tell you if you're running into one of these, provided you have the right server notices enabled (consult your IRCd documentation for how to do this).
        2) Make sure you're not connecting with SSL on a non-SSL port, or vice versa.

If these steps haven't helped you so far, it doesn't hurt to ask for help. :)

### My networks keep disconnecting with SSL errors!

See https://github.com/GLolol/PyLink/issues/463 - this seems to be caused by a regression in OpenSSL 1.0.2, which ships with distros such as Ubuntu 16.04 LTS. Unfortunately, the only workarounds so far are to either disable SSL/TLS, or wrap a plain IRC connection in an external service (stunnel, OpenVPN, etc.)

### I turned autoconnect for PyLink on, and now I'm getting errors!

PyLink does not support inbound connections - much like regular services such as Atheme or Anope, it only connects outwards *to* IRCds. (If you don't understand what this means, it means you should turn autoconnect **off** for PyLink)

## Relay issues

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

First, check whether the SQUIT message includes the nick that triggered the netsplit. If this nick includes any characters not allowed in regular IRC, such as the slash ("/"), or is otherwise an invalid nick (e.g. beginning with a hyphen or number), this likely indicates a bug in PyLink Relay. These problems should be reported on the issue tracker.

However, if the nick mentioned is legal on IRC, this issue is likely caused by a max nick length misconfiguration: i.e. the relay server is introducing nicks too long for the target network. This can be fixed by setting the `maxnicklen` option in the affected network's PyLink `server:` block to the same value as that network's `005` `NICKLEN` (that is, the `NICKLEN=<num>` value in `/raw version`).

### Clientbot doesn't relay both ways!

Load the `relay_clientbot` plugin. https://github.com/GLolol/PyLink/blob/e1fab8c/example-conf.yml#L303-L306

Also, make sure that nothing is blocking the Clientbot from actually sending text, such as blockcolor/regmoderated modes or bans. Temporarily setting the PyLink log level to DEBUG can assist in debugging.

Future PyLink versions will have better handling for these errors; see https://github.com/GLolol/PyLink/issues/497.

### Relay is occasionally dropping users from channels!

This usually indicates a serious bug in either Relay or PyLink's protocol modules, and should be reported as an issue. When asking for help, please state which IRCds your PyLink instance is linking to: specifically, which IRCd the missing users are *from* and which IRCd the users are missing *on*. Also, be prepared to send debug logs as you reproduce the issue!
