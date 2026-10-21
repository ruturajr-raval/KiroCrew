/**
 * The Dynamic capabilities switch sits inside the Crewmate 2.0 switch and only
 * while Crewmate 2.0 is on; it writes `dashboard.crewmate_dynamic_capabilities`
 * and says a restart applies it.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'

import { api } from '../../api/client'
import { PREVIEW_CREW } from '../../utils/previewFlags'
import { FeaturePreviewsSection } from './FeaturePreviewsSection'
import { CREWMATE_DYNAMIC_CAPABILITIES_CONFIG_KEY } from './CrewmateDynamicCapabilitiesToggle'
import { i18nT } from '../../i18n/t'

const L = (k: string) => i18nT(`pages.developer.featurePreviewsTab.${k}`)

type Cfg = { dashboard?: { crewmate_v2?: boolean; crewmate_dynamic_capabilities?: boolean } }

describe('Dynamic capabilities toggle', () => {
  let cfg: Cfg
  beforeEach(() => {
    localStorage.clear()
    localStorage.setItem(PREVIEW_CREW, '1')
    cfg = { dashboard: { crewmate_v2: true, crewmate_dynamic_capabilities: false } }
    vi.spyOn(api, 'dashboardConfig').mockResolvedValue({ decisions_enabled: false } as never)
    vi.spyOn(api, 'kirocrewConfig').mockImplementation(async () => cfg as never)
    vi.spyOn(api, 'getDecisionsConsent').mockResolvedValue({
      enabled: false, endpoint: '', configured_endpoint: '', permits: false,
    })
  })
  afterEach(() => {
    vi.restoreAllMocks()
    localStorage.clear()
  })

  const renderTab = () =>
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter><FeaturePreviewsSection /></MemoryRouter>
      </QueryClientProvider>,
    )

  it('is hidden while Crewmate 2.0 is off', async () => {
    cfg = { dashboard: { crewmate_v2: false, crewmate_dynamic_capabilities: true } }
    renderTab()
    const v2 = within(await screen.findByTestId('crewmate-v2-toggle'))
      .getByRole('switch', { name: L('crewmate_v2') })
    await waitFor(() => expect(v2.getAttribute('aria-disabled')).not.toBe('true'))
    expect(screen.queryByTestId('crewmate-dynamic-capabilities-toggle')).toBeNull()
    expect(screen.queryByRole('switch', { name: L('crewmate_dynamic_capabilities') })).toBeNull()
  })

  it('shows, off, nested under Crewmate 2.0 while 2.0 is on', async () => {
    renderTab()
    const outer = await screen.findByTestId('crewmate-v2-toggle')
    const nested = await within(outer).findByTestId('crewmate-dynamic-capabilities-toggle')
    const dyn = within(nested).getByRole('switch', { name: L('crewmate_dynamic_capabilities') })
    await waitFor(() => expect(dyn.getAttribute('aria-disabled')).not.toBe('true'))
    expect(dyn.getAttribute('aria-checked')).toBe('false')
  })

  it('writes the config key and says a restart applies it', async () => {
    const patch = vi.spyOn(api, 'patchConfig').mockImplementation(async (_p, v) => {
      cfg = { dashboard: { crewmate_v2: true, crewmate_dynamic_capabilities: v as boolean } }
      return { ok: true } as never
    })
    renderTab()
    const nested = await screen.findByTestId('crewmate-dynamic-capabilities-toggle')
    const dyn = within(nested).getByRole('switch', { name: L('crewmate_dynamic_capabilities') })
    await waitFor(() => expect(dyn.getAttribute('aria-disabled')).not.toBe('true'))
    await act(async () => { dyn.click() })
    expect(patch).toHaveBeenCalledWith(CREWMATE_DYNAMIC_CAPABILITIES_CONFIG_KEY, true)
    expect((await screen.findByTestId('crewmate-dynamic-capabilities-restart')).textContent)
      .toBe(L('crewmate_v2_restart'))
    await waitFor(() => expect(dyn.getAttribute('aria-checked')).toBe('true'))
  })
})
