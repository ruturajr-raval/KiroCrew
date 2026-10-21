import type { Notification } from '../../types'
import { noteMember } from './CrewmateNoteFace'
import { KIND_META, DEFAULT_META } from './notifMeta'

/**
 * The stack a note joins in the feed, or null when it stands alone.
 *
 * A producer's own `group_key` wins: it names the thing being reported (an
 * incident, a failing source). Without one, notes stack by who sent them, the
 * way macOS Notification Center stacks by app: the publishing crewmate, then
 * the cron job, then the channel narrowed to the session that raised it.
 *
 * An approval without a `group_key` never stacks. Each one is its own
 * decision, and a deck would hide every command but the newest behind it.
 *
 * Persisted rows are untrusted, so every field is shape-checked before it
 * becomes part of a key.
 */
export function stackKeyOf(n: Notification): string | null {
  if (typeof n.group_key === 'string' && n.group_key) return `group:${n.group_key}`
  if (n.kind === 'approval') return null
  const member = noteMember(n)
  if (member) return `member:${member.slug}`
  if (typeof n.job_id === 'string' && n.job_id) return `cron:${n.job_id}`
  if (typeof n.channel === 'string' && n.channel) {
    return typeof n.session_key === 'string' && n.session_key
      ? `channel:${n.channel}:${n.session_key}`
      : `channel:${n.channel}`
  }
  return null
}

/**
 * The name an expanded stack's header row shows, like the app name macOS puts
 * above a stack: the crewmate who sent it, else the app that sent it, else the
 * kind of note ("Cron Job", "Agent"). The cards under it carry the specifics.
 */
export function stackLabelOf(n: Notification): string {
  const member = noteMember(n)
  if (member) return member.name
  if (typeof n.source === 'string' && n.source && n.source !== 'system') return n.source
  return (KIND_META[n.kind] || DEFAULT_META).label
}
