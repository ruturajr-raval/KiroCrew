/**
 * The **Dynamic capabilities** switch (`dashboard.crewmate_dynamic_capabilities`),
 * drawn INSIDE the Crewmate 2.0 switch (`CrewmateV2Toggle.tsx`) and only while
 * Crewmate 2.0 is on: the third level under Settings > Developer > Feature
 * Previews > Crew Members.
 *
 * On, a crewmate can find new skills or tools for its worker and ask for them on
 * a card in its chat. Off (the default), only the user adds them, in the
 * crewmate's advanced settings. Server config, PATCHed and read back through the
 * shared `['kirocrewConfig']` query; the gateway reads it once at startup
 * (`kiro_crew/crewmate_dynamic_capabilities.py`), so a change says "restart to
 * apply".
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../../api/client'
import ErrorNotice from '../../components/ErrorNotice'
import { SettingsToggle } from '../../components/settings'
import { SchemaRestartBadge } from '../../components/settingRef/RestartRequiredBadge'
import { i18nT } from '../../i18n/t'

/** The config path the toggle writes; read once by the gateway at startup. */
export const CREWMATE_DYNAMIC_CAPABILITIES_CONFIG_KEY = 'dashboard.crewmate_dynamic_capabilities'

type KirocrewConfigShape = { dashboard?: { crewmate_dynamic_capabilities?: boolean } }

export function CrewmateDynamicCapabilitiesToggle() {
  const qc = useQueryClient()
  const cfgQ = useQuery<KirocrewConfigShape>({
    queryKey: ['kirocrewConfig'],
    queryFn: () => api.kirocrewConfig(),
  })
  const [changed, setChanged] = useState(false)
  const [saveError, setSaveError] = useState('')
  const on = cfgQ.data?.dashboard?.crewmate_dynamic_capabilities === true
  const mut = useMutation({
    mutationFn: (v: boolean) => api.patchConfig(CREWMATE_DYNAMIC_CAPABILITIES_CONFIG_KEY, v),
    onSuccess: () => {
      setSaveError('')
      setChanged(true)
      void qc.invalidateQueries({ queryKey: ['kirocrewConfig'] })
    },
    onError: () =>
      setSaveError(i18nT('pages.developer.featurePreviewsTab.crewmate_dynamic_capabilities_failed_to_save')),
  })
  return (
    <div data-testid="crewmate-dynamic-capabilities-toggle" className="mt-2 border-l-2 border-border pl-3">
      <SettingsToggle
        label={i18nT('pages.developer.featurePreviewsTab.crewmate_dynamic_capabilities')}
        hint={i18nT('pages.developer.featurePreviewsTab.crewmate_dynamic_capabilities_desc')}
        checked={on}
        onChange={v => mut.mutate(v)}
        disabled={!cfgQ.isSuccess || mut.isPending}
        configKey={CREWMATE_DYNAMIC_CAPABILITIES_CONFIG_KEY}
      />
      <div className="pt-1">
        <SchemaRestartBadge configKey={CREWMATE_DYNAMIC_CAPABILITIES_CONFIG_KEY} />
      </div>
      {changed && (
        <p data-testid="crewmate-dynamic-capabilities-restart" role="status" className="text-[12px] text-muted pt-1">
          {i18nT('pages.developer.featurePreviewsTab.crewmate_v2_restart')}
        </p>
      )}
      {saveError && (
        <ErrorNotice
          message={saveError}
          onDismiss={() => setSaveError('')}
          className="mt-2"
          testId="crewmate-dynamic-capabilities-save-error"
        />
      )}
    </div>
  )
}
