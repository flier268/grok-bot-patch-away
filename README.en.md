# grok-bot-patch-away

[中文](README.md)

About 10 minutes after the Grok Bot window leaves the foreground, the app marks this computer as away. The cloud computer then goes to sleep, and the local command channel drops. This still happens while the app is open and you are using another window.

This script rewrites that check inside the local `app.asar` so "the window is unfocused" is never true. Suspend and screen lock still count as away.

It finds the check by the stable property names `isSuspended`, `isScreenLocked`, and `unfocusedSinceMs`. It does not depend on minified function names or byte offsets, and it recomputes that file's asar SHA256. A header with 0 to 3 bytes of alignment padding is accepted.

## Usage

Quit Grok Bot completely, then:

```bash
sudo python3 grok-bot-patch-away.py
```

Show which file would change, without writing:

```bash
python3 grok-bot-patch-away.py --dry-run
```

If the install is not in a default location, pass `app.asar`:

```bash
sudo python3 grok-bot-patch-away.py "/opt/Grok Bot/resources/app.asar"
```

Default search paths:

- Linux: `/opt/Grok Bot/resources/app.asar`
- macOS: `/Applications/Grok Bot.app/Contents/Resources/app.asar`
- Windows: `%LOCALAPPDATA%\Programs\Grok Bot\resources\app.asar`

The first run leaves `app.asar.bak-before-away-patch` in the same directory. Running it again on an already patched file does nothing. Restore with:

```bash
sudo python3 grok-bot-patch-away.py --restore
```

A Grok Bot update replaces `app.asar`. Run the script again after updating.

Restart Grok Bot after patching. A process that is already running keeps the old code.

## What it changes

The original condition is roughly:

```text
isSuspended || isScreenLocked || unfocusedSinceMs !== null && elapsed >= 10 minutes
```

The script replaces only `unfocusedSinceMs !== null` with a same-length comparison that is never true (a comparison with `Infinity`). Suspend and screen lock stay in place.

If this build does not match that shape, the script stops and does not write an asar that would fail the integrity check.

## Limits

Requires Python 3 and write access to the install directory. This edits the local client. It is not a Grok Bot setting.
