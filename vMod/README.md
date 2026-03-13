# VMod

VMod is a comprehensive moderation cog for Red-DiscordBot, rebuilt with features
inspired by **modP** and the **modulus (modplus)** system from dgarner-cg/tl-cogs.

## What's new in v4

- **Notification system** — modulus-style DM and channel subscriptions for every
  moderation event (kick, ban, mute, warn, bot joins, admin role escalations, etc.)
- **Expanded permission keys** — `kick`, `ban`, `mute`, `warn`, `channelperms`,
  `editchannel`, and `deletemessages` (matching modplus)
- **Rate-limit enforcement** — when a moderator exceeds their rate limit, their
  mod roles are stripped and all `ratelimit` subscribers are notified
- **Warn system** — `warn`, `warnings`, `clearwarns` commands with per-member
  warning history and milestone role assignment
- **Timeout / mute** — `timeout` (`mute`) and `untimeout` (`unmute`) using
  Discord's native timeout feature
- **Purge** — `clean` command to bulk-delete up to 100 messages
- **Pin** — `pin` command for pinning messages
- **Warning milestone roles** — automatically apply roles on 1st, 2nd, and 3rd+
  warning (configurable via `vmodroles`)
- **Beautiful embeds** — consistent colour scheme and field layout across all
  command responses

## Files

| File | Purpose |
|------|---------|
| `base.py` | Config, helpers, modlog helpers, notification system, tempban expiry |
| `events.py` | Automod listeners, name tracking, notification dispatch |
| `moderation.py` | All moderation and info commands |
| `settings.py` | Settings, permissions, roles, and notification subscriptions |
| `views.py` | Interactive settings dashboard UI |
| `vmod.py` | Combined cog class |
| `constants.py` | Action keys, notification keys, embed text |
| `converters.py` | `RawUserIds` argument converter |

## Commands

### Moderation
| Command | Description |
|---------|-------------|
| `[p]kick @user [reason]` | Kick a member |
| `[p]ban @user [days] [reason]` | Ban a member |
| `[p]tempban @user [duration] [reason]` | Temporarily ban a member |
| `[p]softban @user [reason]` | Ban + unban to clear recent messages |
| `[p]unban <user_id> [reason]` | Unban a user by ID |
| `[p]massban <ids...> [reason]` | Ban multiple users by ID |
| `[p]timeout @user [duration] [reason]` | Timeout (mute) a member |
| `[p]untimeout @user [reason]` | Remove a member's timeout early |
| `[p]warn @user [reason]` | Issue a formal warning |
| `[p]warnings [@user]` | Show a member's warnings |
| `[p]clearwarns @user` | Clear all warnings for a member |
| `[p]clean <amount> [@user]` | Bulk-delete messages |
| `[p]pin [message]` | Pin a message |
| `[p]slowmode [interval]` | Set channel slowmode |
| `[p]rename @user [nick]` | Change a member's nickname |
| `[p]userinfo [@user]` | Show detailed member info |

### Configuration (`vmodset`)
| Command | Description |
|---------|-------------|
| `[p]vmodset show` | Show all current settings |
| `[p]vmodset panel` | Open the interactive settings panel |
| `[p]vmodset hierarchy` | Toggle role hierarchy checks |
| `[p]vmodset dmonaction <bool>` | Toggle DM before kick/ban |
| `[p]vmodset reinvite <bool>` | Toggle reinvite on unban |
| `[p]vmodset repeats <n>` | Set repeat-message deletion threshold |
| `[p]vmodset defaultdays <n>` | Default message-delete days on ban |
| `[p]vmodset defaulttempban <dur>` | Default tempban duration |
| `[p]vmodset tracknicks <bool>` | Toggle nickname history tracking |
| `[p]vmodset mentionspam warn/kick/ban/strict` | Configure mention-spam thresholds |

### Permissions (`vmodperms`)
| Command | Description |
|---------|-------------|
| `[p]vmodperms info` | Show permission system info |
| `[p]vmodperms add @role <key>` | Grant a permission key to a role |
| `[p]vmodperms remove @role <key>` | Revoke a permission key from a role |
| `[p]vmodperms list [key]` | List role permissions |
| `[p]vmodperms byrole @role` | Show all keys a role has |

### Roles (`vmodroles`)
| Command | Description |
|---------|-------------|
| `[p]vmodroles warning1 [@role]` | Set the 1st-warning milestone role |
| `[p]vmodroles warning2 [@role]` | Set the 2nd-warning milestone role |
| `[p]vmodroles warning3 [@role]` | Set the 3rd+-warning milestone role |
| `[p]vmodroles muted [@role]` | Set the fallback muted role |
| `[p]vmodroles show` | Show all configured roles |

### Rate Limits (`vmodratelimit`)
| Command | Description |
|---------|-------------|
| `[p]vmodratelimit show` | Show current rate limits |
| `[p]vmodratelimit set <key> <n> <secs>` | Set a rate limit |

### Notifications (`vmodnotifs`)
| Command | Description |
|---------|-------------|
| `[p]vmodnotifs info` | Show notification system info |
| `[p]vmodnotifs add <key> [@user]` | Subscribe to a notification key |
| `[p]vmodnotifs remove <key> [@user]` | Unsubscribe from a key |
| `[p]vmodnotifs list [@user]` | Show a user's subscriptions |
| `[p]vmodnotifs channel add <key> #ch` | Subscribe a channel |
| `[p]vmodnotifs channel remove <key> #ch` | Unsubscribe a channel |
| `[p]vmodnotifs channel list #ch` | Show a channel's subscriptions |

## Permission keys

`kick` • `ban` • `mute` • `warn` • `channelperms` • `editchannel` • `deletemessages`

## Notification keys

`kick` • `ban` • `mute` • `warn` • `channelperms` • `editchannel` • `deletemessages`
• `ratelimit` • `adminrole` • `bot`

