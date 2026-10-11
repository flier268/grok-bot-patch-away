# grok-bot-patch-away

[中文](README.md)

About 10 minutes after the Grok Bot window leaves the foreground, or when the screen locks or the computer suspends, the app marks this computer as away. The cloud computer then goes to sleep, and the local command channel drops.

This script rewrites that check inside the local `app.asar` so none of those three count as away. The process is already frozen while the computer sleeps, and wake does not have to clear a stuck away state.

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

The script replaces that whole `return` with a same-length `return!1`. None of the three conditions remain. An older patch that only disabled the unfocused check is upgraded on the next run.

If this build does not match that shape, the script stops and does not write an asar that would fail the integrity check.

## Limits

Requires Python 3 and write access to the install directory. This edits the local client. It is not a Grok Bot setting. While the screen is locked or the computer is asleep, the cloud computer is not asked to sleep for that reason. Local commands still cannot run during real suspend, until the computer wakes.
