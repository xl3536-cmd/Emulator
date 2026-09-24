import { useEffect, useMemo, useState } from 'react'

import { api } from './api/client'
import Shell from './components/layout/Shell'
import ArcticHpPage from './features/arcticHp/ArcticHpPage'
import DashboardPage from './features/dashboard/DashboardPage'
import LeakSensorPage from './features/leakSensor/LeakSensorPage'
import RtdPage from './features/rtd/RtdPage'
import SchedulingPage from './features/scheduling/SchedulingPage'
import ValvePage from './features/valves/ValvePage'

const TABS = [
  { id: 'dashboard', label: 'Dashboard' },
  { id: 'scheduling', label: 'Scheduling' },
  { id: 'rtd', label: 'RTD' },
  { id: 'valves', label: 'Valves' },
  { id: 'leak-sensors', label: 'Leak Sensor' },
  { id: 'arctic', label: 'Arctic HP' },
]

const DEFAULT_TAB = 'dashboard'

function resolveInitialTab() {
  if (typeof window === 'undefined') return DEFAULT_TAB
  const stored = window.localStorage.getItem('full-stack-emulator-active-tab')
  return TABS.some((tab) => tab.id === stored) ? stored : DEFAULT_TAB
}

function defaultRuntime() {
  return {
    rtd: {
      board_count: 0,
      invert_bits: false,
      reverse_byte_order: true,
      hardware_available: false,
      hardware_error: null,
      output_source: 'manual',
      board_bits: [],
      frame_bytes: [],
      current_rtd_codes: {},
      current_valve_states: {},
      playback: {
        loaded: false,
        loaded_filename: null,
        playing: false,
        row_index: -1,
        row_count: 0,
        mode: 'fast',
        header: [],
        matched_rtd_columns: {},
        matched_valve_columns: {},
        slow_reason: null,
        valve_transitions: {},
      },
    },
    valves: { ball_valves: [], relay_detectors: [] },
    leak_sensors: { sensors: [] },
    arctic_hp: { server: { running: false, transport_available: false, port: '', message: '' }, devices: [] },
  }
}

export default function App() {
  const [activeTab, setActiveTab] = useState(resolveInitialTab)
  const [config, setConfig] = useState(null)
  const [runtime, setRuntime] = useState(defaultRuntime())
  const [status, setStatus] = useState('Loading...')
  const [saving, setSaving] = useState(false)

  const loadAll = async () => {
    const [configData, runtimeData] = await Promise.all([api.getConfig(), api.getRuntime()])
    setConfig(configData)
    setRuntime(runtimeData)
    setStatus('Connected to backend')
  }

  useEffect(() => {
    loadAll().catch((error) => setStatus(error.message || 'Backend unavailable'))
  }, [])

  useEffect(() => {
    const timer = setInterval(() => {
      api.getRuntime().then(setRuntime).catch(() => {})
    }, 1000)
    return () => clearInterval(timer)
  }, [])

  useEffect(() => {
    if (typeof window === 'undefined') return
    window.localStorage.setItem('full-stack-emulator-active-tab', activeTab)
  }, [activeTab])

  const handleConfigChange = async (nextConfig) => {
    setSaving(true)
    try {
      const saved = await api.putConfig(nextConfig)
      setConfig(saved)
      const runtimeData = await api.getRuntime()
      setRuntime(runtimeData)
      setStatus('Config updated')
      return saved
    } catch (error) {
      setStatus(error.message || 'Config save failed')
      throw error
    } finally {
      setSaving(false)
    }
  }

  const page = useMemo(() => {
    if (!config) return null
    if (activeTab === 'dashboard') return <DashboardPage runtime={runtime} />
    if (activeTab === 'scheduling') return <SchedulingPage config={config} runtime={runtime} onConfigChange={handleConfigChange} onLoadCsv={async (payload) => { await api.loadCsv(payload); setRuntime(await api.getRuntime()) }} onSetPlayback={async (playing) => { await api.setPlayback(playing); setRuntime(await api.getRuntime()) }} onClearCsv={async () => { await api.clearCsv(); setRuntime(await api.getRuntime()) }} />
    if (activeTab === 'rtd') return <RtdPage config={config} runtime={runtime} onConfigChange={handleConfigChange} onSetBoardBits={async (boardIndex, bits) => { await api.setBoardBits(boardIndex, bits); setRuntime(await api.getRuntime()) }} />
    if (activeTab === 'valves') return <ValvePage config={config} runtime={runtime} onConfigChange={handleConfigChange} onValveOverride={async (valveId, voltage) => { await api.setValveOverride(valveId, voltage); setRuntime(await api.getRuntime()) }} />
    if (activeTab === 'leak-sensors') return <LeakSensorPage config={config} runtime={runtime} onConfigChange={handleConfigChange} onSetVoltage={async (sensorId, voltage) => { await api.setLeakSensorVoltage(sensorId, voltage); setRuntime(await api.getRuntime()) }} />
    if (activeTab === 'arctic') return <ArcticHpPage config={config} runtime={runtime} onConfigChange={handleConfigChange} onStartServer={async () => { await api.startArcticServer(); setRuntime(await api.getRuntime()) }} onStopServer={async () => { await api.stopArcticServer(); setRuntime(await api.getRuntime()) }} onSetRegister={async (deviceId, address, value) => { await api.setArcticRegister(deviceId, address, value); setRuntime(await api.getRuntime()) }} onResetDevice={async (deviceId) => { await api.resetArcticDevice(deviceId); setRuntime(await api.getRuntime()) }} />
    return <DashboardPage runtime={runtime} />
  }, [activeTab, config, runtime])

  return (
    <Shell
      tabs={TABS}
      activeTab={activeTab}
      onTabChange={setActiveTab}
      status={saving ? 'Saving...' : status}
    >
      {page}
    </Shell>
  )
}
