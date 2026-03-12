# VMod

VMod is a cleaned-up moderation cog package built from the older split mod / modplus design.

## What changed

- removed the old ModPlus notification subscription system
- uses Red's modlog framework for moderation cases and staff notes
- split into focused files for version control
- added comments and docstrings throughout
- added a setup panel with buttons, a dropdown menu, and modal forms

## Files

- `base.py` - config, helpers, modlog helpers, tempban expiry task
- `events.py` - listeners and bot-managed automod checks
- `settings.py` - config commands and setup dashboard
- `moderation.py` - moderation commands and member info utilities
- `views.py` - Discord UI for the control panel
- `vmod.py` - final cog class

## Main commands

### Moderation
- `[p]kick`
- `[p]ban`
- `[p]tempban`
- `[p]softban`
- `[p]unban`
- `[p]massban`
- `[p]slowmode`
- `[p]rename`
- `[p]userinfo`
- `[p]names`

### Setup
- `[p]vmodset show`
- `[p]vmodset panel`
- `[p]vmodset hierarchy`
- `[p]vmodset repeats`
- `[p]vmodset dmonaction`
- `[p]vmodset reinvite`
- `[p]vmodset defaultdays`
- `[p]vmodset defaulttempban`
- `[p]vmodset tracknicks`
- `[p]vmodset mentionspam ...`
- `[p]vmodset perms ...`
- `[p]vmodset ratelimit ...`

## Notes

- Informational events such as admin-role changes and bot joins are written to Red's configured modlog channel as embed notes.
- Prefix commands remain the main control surface, but `vmodset panel` is there for faster setup.
