import { createRef } from 'react'
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import { renderWithProviders, createTestStore } from './helpers'
import NotificationFeed from '../components/notifications/NotificationFeed'
import NotificationClearButton from '../components/notifications/NotificationClearButton'
import { uiLocation } from '../uiLocations/uiLocation'
import { registeredCopies } from '../uiLocations/targetRegistry'
import { stackKeyOf } from '../components/notifications/notificationStacks'
import type { RootState } from '../store'
import type { Notification } from '../types'

const mockDeleteNotification = vi.fn().mockResolvedValue({})
const mockClearNotifications = vi.fn().mockResolvedValue({})

vi.mock('../api/client', () => ({
  api: {
    notifications: vi.fn().mockResolvedValue({ notifications: [] }),
    ackNotification: vi.fn().mockResolvedValue({}),
    deleteNotification: (...args: unknown[]) => mockDeleteNotification(...args),
    clearNotifications: (...args: unknown[]) => mockClearNotifications(...args),
    updateNotificationChannelSettings: vi.fn().mockResolvedValue({}),
  },
}))

// The dust animation is not what these tests are about; resolve it at once.
vi.mock('../lib/disintegrate', () => ({ disintegrate: () => Promise.resolve() }))

globalThis.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} } as unknown as typeof ResizeObserver

// Every note lands in the "Today" group: the clock sits 30 s after the latest.
const NOW = '2026-07-24T11:00:30Z'
const mkN = (over: Partial<Notification>): Notification => ({
  kind: 'cron', ts: '2026-07-24T11:00:00Z', title: 'Note', body: 'body', acked: false, ...over,
})

function renderFeed(notifs: Notification[], variant: 'panel' | 'mac' = 'panel') {
  const store = createTestStore({ notifications: { items: notifs, clearSeq: 0 } as RootState['notifications'] })
  return renderWithProviders(<NotificationFeed selectedTs={null} onSelect={() => {}} variant={variant} />, { store })
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(new Date(NOW))
  localStorage.clear()
  mockDeleteNotification.mockClear()
  mockClearNotifications.mockClear()
})

afterEach(() => {
  vi.useRealTimers()
})

describe('stackKeyOf', () => {
  it('prefers the producer group_key over the sender', () => {
    expect(stackKeyOf(mkN({ group_key: 'inc-1', job_id: 'job-a' }))).toBe('group:inc-1')
  })
  it('never stacks an approval that carries no group_key', () => {
    expect(stackKeyOf(mkN({ kind: 'approval', channel: 'system.approval' }))).toBeNull()
  })
  it('stacks by crewmate, then cron job, then channel and session', () => {
    expect(stackKeyOf(mkN({ member: { slug: 'ada', name: 'Ada' }, job_id: 'job-a' }))).toBe('member:ada')
    expect(stackKeyOf(mkN({ job_id: 'job-a', channel: 'system.cron' }))).toBe('cron:job-a')
    expect(stackKeyOf(mkN({ channel: 'system.agent', session_key: 's1' }))).toBe('channel:system.agent:s1')
    expect(stackKeyOf(mkN({ channel: 'oncall-radar.ticket' }))).toBe('channel:oncall-radar.ticket')
  })
  it('leaves a note with no sender on its own', () => {
    expect(stackKeyOf(mkN({}))).toBeNull()
  })
  it('ignores sender fields of the wrong shape on a persisted row', () => {
    expect(stackKeyOf(mkN({ job_id: 42 as unknown as string }))).toBeNull()
  })
})

describe('NotificationFeed: stacks by sender', () => {
  it('stacks notes from one cron job and keeps another job apart', () => {
    renderFeed([
      mkN({ ts: '2026-07-24T10:58:00Z', title: 'Triage 1', job_id: 'triage' }),
      mkN({ ts: '2026-07-24T10:59:00Z', title: 'Triage 2', job_id: 'triage' }),
      mkN({ ts: '2026-07-24T11:00:00Z', title: 'Digest', job_id: 'digest' }),
    ])
    expect(screen.getByText('Triage 2')).toBeTruthy()
    expect(screen.queryByText('Triage 1')).toBeNull()
    expect(screen.getByText('Digest')).toBeTruthy()
    expect(screen.getAllByRole('button', { name: /1 more/ })).toHaveLength(1)
  })

  it('closing a collapsed deck clears every note in it', async () => {
    renderFeed([
      mkN({ ts: '2026-07-24T10:58:00Z', title: 'Triage 1', job_id: 'triage' }),
      mkN({ ts: '2026-07-24T10:59:00Z', title: 'Triage 2', job_id: 'triage' }),
      mkN({ ts: '2026-07-24T11:00:00Z', title: 'Digest', job_id: 'digest' }),
    ], 'mac')
    fireEvent.click(screen.getByRole('button', { name: 'Clear this group' }))
    await waitFor(() => expect(mockDeleteNotification).toHaveBeenCalledTimes(2))
    expect(mockDeleteNotification.mock.calls.map(c => c[0]).sort()).toEqual(['2026-07-24T10:58:00Z', '2026-07-24T10:59:00Z'])
  })
})

describe('NotificationFeed: expanded stack header row (macOS style)', () => {
  const triage = [
    mkN({ ts: '2026-07-24T10:58:00Z', title: 'Triage 1', job_id: 'triage' }),
    mkN({ ts: '2026-07-24T10:59:00Z', title: 'Triage 2', job_id: 'triage' }),
    mkN({ ts: '2026-07-24T11:00:00Z', title: 'Triage 3', job_id: 'triage' }),
  ]

  for (const variant of ['mac', 'panel'] as const) {
    it(`${variant}: expanding shows a header with the sender, Show less and clear`, () => {
      renderFeed(triage, variant)
      expect(screen.queryByRole('button', { name: 'Clear Cron Job' })).toBeNull()
      fireEvent.click(variant === 'mac'
        ? screen.getByRole('button', { name: /Expand 3 grouped notifications/ })
        : screen.getByRole('button', { name: /2 more/ }))
      expect(screen.getByText('Cron Job')).toBeTruthy()
      expect(screen.getAllByRole('button', { name: 'Show less' })).toHaveLength(1)
      expect(screen.getByRole('button', { name: 'Clear Cron Job' })).toBeTruthy()
      fireEvent.click(screen.getByRole('button', { name: 'Show less' }))
      expect(screen.queryByText('Triage 1')).toBeNull()
      expect(screen.queryByRole('button', { name: 'Clear Cron Job' })).toBeNull()
    })
  }

  it('the header clear arms first, then deletes every note in the stack', async () => {
    renderFeed(triage, 'mac')
    fireEvent.click(screen.getByRole('button', { name: /Expand 3 grouped notifications/ }))
    const clear = screen.getByRole('button', { name: 'Clear Cron Job' })
    fireEvent.click(clear)
    expect(mockDeleteNotification).not.toHaveBeenCalled()
    fireEvent.click(clear)
    await waitFor(() => expect(mockDeleteNotification).toHaveBeenCalledTimes(3))
  })

  it('the header clear says "Clear" at rest and names its scope when armed', () => {
    renderFeed(triage, 'mac')
    fireEvent.click(screen.getByRole('button', { name: /Expand 3 grouped notifications/ }))
    const clear = screen.getByRole('button', { name: 'Clear Cron Job' })
    // Text, not a bare ⓧ that could mean "hide" beside Show less.
    expect(within(clear).getByText('Clear')).toBeTruthy()
    expect(clear.querySelector('svg')).toBeNull()
    fireEvent.click(clear)
    expect(clear.getAttribute('data-armed')).toBe('true')
    // Never the inbox-wide "Clear all".
    expect(within(clear).getByText('Clear this group')).toBeTruthy()
    expect(within(clear).queryByText('Clear all')).toBeNull()
  })

  it('names a crewmate stack by the crewmate', () => {
    renderFeed([
      mkN({ ts: '2026-07-24T10:59:00Z', title: 'Hi', kind: 'agent', member: { slug: 'ada', name: 'Ada' } }),
      mkN({ ts: '2026-07-24T11:00:00Z', title: 'Done', kind: 'agent', member: { slug: 'ada', name: 'Ada' } }),
    ], 'mac')
    fireEvent.click(screen.getByRole('button', { name: /Expand 2 grouped notifications/ }))
    expect(screen.getByRole('button', { name: 'Clear Ada' })).toBeTruthy()
  })
})

describe('NotificationFeed: clear sits on what it clears', () => {
  const notes = [
    mkN({ ts: '2026-07-24T10:59:00Z', title: 'First' }),
    mkN({ ts: '2026-07-24T11:00:00Z', title: 'Second' }),
  ]

  it('the date group clear arms on the first press and clears on the second', async () => {
    renderFeed(notes)
    const clear = screen.getByRole('button', { name: 'Clear Today' })
    fireEvent.click(clear)
    expect(mockDeleteNotification).not.toHaveBeenCalled()
    expect(clear.getAttribute('data-armed')).toBe('true')
    expect(within(clear).getByText('Clear')).toBeTruthy()
    fireEvent.click(clear)
    await waitFor(() => expect(mockDeleteNotification).toHaveBeenCalledTimes(2))
  })

  it('leaving an armed clear turns it back without clearing', () => {
    renderFeed(notes)
    const clear = screen.getByRole('button', { name: 'Clear Today' })
    fireEvent.click(clear)
    fireEvent.mouseLeave(clear)
    expect(clear.getAttribute('data-armed')).toBeNull()
    fireEvent.click(clear)
    expect(mockDeleteNotification).not.toHaveBeenCalled()
  })

  it('Escape disarms an armed clear', () => {
    renderFeed(notes)
    const clear = screen.getByRole('button', { name: 'Clear Today' })
    fireEvent.click(clear)
    fireEvent.keyDown(clear, { key: 'Escape' })
    expect(clear.getAttribute('data-armed')).toBeNull()
  })

  it('the bell sheet clear-all needs two presses and no native confirm', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm')
    renderFeed(notes, 'mac')
    const clearAll = screen.getByRole('button', { name: 'Clear all notifications?' })
    // A trash can at rest: an ⓧ in the sheet's corner reads as "close".
    expect(clearAll.querySelector('svg.lucide-trash-2')).toBeTruthy()
    expect(clearAll.querySelector('svg.lucide-x')).toBeNull()
    fireEvent.click(clearAll)
    expect(mockClearNotifications).not.toHaveBeenCalled()
    expect(within(clearAll).getByText('Clear all')).toBeTruthy()
    fireEvent.click(clearAll)
    await waitFor(() => expect(mockClearNotifications).toHaveBeenCalledTimes(1))
    expect(confirmSpy).not.toHaveBeenCalled()
    confirmSpy.mockRestore()
  })

  it('the page clear-all keeps its visible label and needs two presses', async () => {
    renderFeed(notes)
    const clearAll = screen.getByRole('button', { name: 'Clear' })
    fireEvent.click(clearAll)
    expect(mockClearNotifications).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Clear all' }))
    await waitFor(() => expect(mockClearNotifications).toHaveBeenCalledTimes(1))
  })
})

describe('NotificationClearButton: UI location ref', () => {
  it('forwards its ref to the <button>', () => {
    const ref = createRef<HTMLButtonElement>()
    render(<NotificationClearButton ref={ref} aria-label="Clear x" confirmText="Clear" onClick={() => {}} />)
    const button = screen.getByRole('button', { name: 'Clear x' })
    expect(ref.current).toBe(button)
  })

  it('registers a spread uiLocation on the <button> itself', () => {
    render(<NotificationClearButton aria-label="Clear y" {...uiLocation('notifications.clear-all')} confirmText="Clear" onClick={() => {}} />)
    const button = screen.getByRole('button', { name: 'Clear y' })
    expect(button.getAttribute('data-ui-location')).toBe('notifications.clear-all')
    expect(registeredCopies('location', 'notifications.clear-all')).toEqual([button])
  })

  it('both feed clear-all call sites register their location', () => {
    const notes = [mkN({ ts: '2026-07-24T11:00:00Z', title: 'Only' })]
    const { unmount } = renderFeed(notes, 'mac')
    expect(registeredCopies('location', 'notifications.clear-all')).toEqual([screen.getByRole('button', { name: 'Clear all notifications?' })])
    unmount()
    renderFeed(notes, 'panel')
    expect(registeredCopies('location', 'notifications.page-clear-all')).toEqual([screen.getByRole('button', { name: 'Clear' })])
  })
})

describe.each(['mac', 'panel'] as const)('NotificationFeed: clear failures (%s)', variant => {
  const failureMessage = 'Some notifications could not be cleared. Try again.'
  const notes = [
    mkN({ ts: '2026-07-24T10:59:00Z', title: 'First' }),
    mkN({ ts: '2026-07-24T11:00:00Z', title: 'Second' }),
  ]

  it('a failed day clear keeps the rows and a successful day clear removes the notice', async () => {
    mockDeleteNotification.mockRejectedValueOnce(new Error('offline')).mockRejectedValueOnce(new Error('offline'))
    renderFeed(notes, variant)
    const clear = screen.getByRole('button', { name: 'Clear Today' })
    fireEvent.click(clear)
    fireEvent.click(clear)
    expect(await screen.findByRole('alert')).toHaveTextContent(failureMessage)
    expect(screen.getAllByRole('alert')).toHaveLength(1)
    expect(screen.getByText('First')).toBeTruthy()
    expect(screen.getByText('Second')).toBeTruthy()
    expect(mockDeleteNotification).toHaveBeenCalledTimes(2)

    fireEvent.click(clear)
    fireEvent.click(clear)
    await waitFor(() => expect(screen.queryByRole('alert')).toBeNull())
    expect(screen.queryByText('First')).toBeNull()
    expect(screen.queryByText('Second')).toBeNull()
    expect(mockDeleteNotification).toHaveBeenCalledTimes(4)
  })

  it('a partial day clear keeps the failed row and reports one failure', async () => {
    mockDeleteNotification.mockRejectedValueOnce(new Error('offline'))
    renderFeed(notes, variant)
    const clear = screen.getByRole('button', { name: 'Clear Today' })
    fireEvent.click(clear)
    fireEvent.click(clear)
    expect(await screen.findByRole('alert')).toHaveTextContent(failureMessage)
    expect(screen.getAllByRole('alert')).toHaveLength(1)
    expect(screen.queryByText('First')).toBeNull()
    expect(screen.getByText('Second')).toBeTruthy()
    expect(mockDeleteNotification).toHaveBeenCalledTimes(2)
  })

  it('a partial stack-header clear keeps the failed row and reports the failure', async () => {
    mockDeleteNotification.mockRejectedValueOnce(new Error('offline'))
    renderFeed(notes.map(n => ({ ...n, job_id: 'triage' })), variant)
    fireEvent.click(screen.getByRole('button', { name: variant === 'mac' ? /Expand 2 grouped notifications/ : /1 more/ }))
    const clear = screen.getByRole('button', { name: 'Clear Cron Job' })
    fireEvent.click(clear)
    fireEvent.click(clear)
    expect(await screen.findByRole('alert')).toHaveTextContent(failureMessage)
    expect(screen.queryByText('First')).toBeNull()
    expect(screen.getByText('Second')).toBeTruthy()
    expect(mockDeleteNotification).toHaveBeenCalledTimes(2)
  })

  it('a partial deck clear restores the failed head after its dismissal animation', async () => {
    const animation = await import('../lib/disintegrate')
    vi.spyOn(animation, 'disintegrate').mockImplementationOnce(async row => {
      if (row) {
        row.style.opacity = '0'
        row.style.filter = 'blur(1.6px)'
        row.style.maskImage = 'linear-gradient(transparent, transparent)'
        row.style.webkitMaskImage = 'linear-gradient(transparent, transparent)'
        row.style.willChange = 'mask, filter, opacity'
      }
    })
    mockDeleteNotification.mockRejectedValueOnce(new Error('offline'))
    renderFeed(notes.map(n => ({ ...n, job_id: 'triage' })), variant)
    const row = screen.getByText('Second').closest<HTMLElement>('[data-notif-row]')!
    const previousStyle = row.style.cssText
    fireEvent.click(screen.getByRole('button', { name: 'Clear this group' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(failureMessage)
    expect(screen.queryByText('First')).toBeNull()
    expect(screen.getByText('Second')).toBeTruthy()
    expect(row.style.cssText).toBe(previousStyle)
    expect(mockDeleteNotification).toHaveBeenCalledTimes(2)
  })

  it('a failed clear-all keeps the rows and a successful clear-all removes the notice', async () => {
    mockClearNotifications.mockRejectedValueOnce(new Error('offline'))
    renderFeed(notes, variant)
    const clear = screen.getByRole('button', { name: variant === 'mac' ? 'Clear all notifications?' : 'Clear' })
    fireEvent.click(clear)
    fireEvent.click(clear)
    expect(await screen.findByRole('alert')).toHaveTextContent(failureMessage)
    expect(screen.getAllByRole('alert')).toHaveLength(1)
    expect(screen.getByText('First')).toBeTruthy()
    expect(screen.getByText('Second')).toBeTruthy()
    expect(mockClearNotifications).toHaveBeenCalledTimes(1)

    fireEvent.click(clear)
    fireEvent.click(clear)
    await waitFor(() => expect(screen.queryByRole('alert')).toBeNull())
    expect(screen.queryByText('First')).toBeNull()
    expect(screen.queryByText('Second')).toBeNull()
    expect(mockClearNotifications).toHaveBeenCalledTimes(2)
  })
})
