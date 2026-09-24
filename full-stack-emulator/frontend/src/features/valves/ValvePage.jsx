import { useEffect, useMemo, useState } from 'react'

import Card from '../../components/common/Card'
import { convertValveProfile, createDefaultValve } from '../config/configDefaults'
import { updateConfigAtPath } from '../config/updateConfigAtPath'

function formatAnalogChannel(channel) {
  if (!channel || Number(channel.channel) < 1) {
    return 'Not Set'
  }
  return `Stack ${channel.stack}, Channel ${channel.channel}`
}

function formatFeedbackChannel(channel) {
  return `Stack ${channel.stack}, Relay ${channel.channel}`
}

function formatDetectorChannel(channel) {
  if (channel?.i2c_address === null || channel?.i2c_address === undefined || channel?.i2c_address === '') {
    return `Addr Not Set, Ch ${channel?.channel ?? ''}`.trim()
  }
  return `Addr 0x${Number(channel.i2c_address).toString(16).toUpperCase()}, Ch ${channel.channel}`
}

function formatI2cAddress(value) {
  return `0x${Number(value ?? 0x20).toString(16).toUpperCase()}`
}

function formatEditableI2cAddress(value) {
  if (value === '' || value === null || value === undefined) return ''
  const text = String(value).trim()
  if (!text) return ''
  if (text.toLowerCase().startsWith('0x')) return text
  const parsed = Number(text)
  return Number.isFinite(parsed) ? formatI2cAddress(parsed) : text
}

function formatHexWord(value) {
  if (value === null || value === undefined) return 'n/a'
  return `0x${Number(value).toString(16).toUpperCase().padStart(4, '0')}`
}

function getValveCardClass(configValve, valve) {
  if (valve.missing_board) return 'valve-card missing valve-card-alert'
  if (valve.error) return 'valve-card valve-card-warning'
  if (configValve.profile_type === 'ov') {
    if (valve.mode === 'WAIT_OPEN' || valve.mode === 'OPEN_FEEDBACK') return 'valve-card valve-card-opening'
    if (valve.mode === 'WAIT_CLOSE' || valve.mode === 'CLOSE_FEEDBACK') return 'valve-card valve-card-closing'
    if (valve.position === null || valve.position === undefined) return 'valve-card valve-card-warning'
    return 'valve-card'
  }
  if (!valve.detector_active) return 'valve-card valve-card-standby'
  if (valve.mode === 'RAMP_UP') return 'valve-card valve-card-opening'
  if (valve.mode === 'RAMP_DOWN') return 'valve-card valve-card-closing'
  return 'valve-card valve-card-tracking'
}

function formatCardError(error) {
  if (!error) return null
  return String(error)
}

function getOvSummary(valve, configValve) {
  if (valve.missing_board) return 'Board Not Detected'
  if (valve.error) return formatCardError(valve.error)
  if (valve.mode === 'OPEN_FEEDBACK') return 'ARRIVING AT OPEN'
  if (valve.mode === 'CLOSE_FEEDBACK') return 'ARRIVING AT CLOSED'
  if (valve.pending_action) return `WAIT ${String(valve.pending_action).toUpperCase()}`
  if (valve.position === null || valve.position === undefined) return 'MID-TRAVEL'
  return String(valve.position).toUpperCase()
}

function getCvSummary(valve) {
  if (valve.missing_board) return 'Board Not Detected'
  if (valve.error) return formatCardError(valve.error)
  if (!valve.detector_active) return 'DETECTOR OFF'
  if (valve.mode === 'RAMP_UP' || valve.mode === 'RAMP_DOWN') return 'MOVING TO TARGET'
  return 'AT TARGET'
}

function getCvSubtitle(valve) {
  if (valve.error) return `Mode ${valve.mode}`
  if (!valve.detector_active) return 'Detector OFF, analog feedback at 0V'
  if (valve.mode === 'RAMP_UP' || valve.mode === 'RAMP_DOWN') return 'Detector ON, tracking analog input'
  return 'Detector ON, holding matched position'
}

function getCvPositionLabel(valve) {
  return valve.detector_active ? 'Target Open' : 'Open'
}

function getCvVinLabel() {
  return 'VIN'
}

function formatCvOpenPercentage(voltage, behavior) {
  const vMin = Number(behavior?.v_min ?? 2)
  const vMax = Number(behavior?.v_max ?? 10)
  const value = Number(voltage ?? 0)
  const span = Math.max(0.000001, vMax - vMin)
  const percent = Math.max(0, Math.min(100, ((value - vMin) / span) * 100))
  return {
    percent: `${percent.toFixed(0)}%`,
    voltage: `(${value.toFixed(2)}V)`,
  }
}

function getSchedulingTransition(runtime, valveId) {
  if (runtime.rtd.playback.mode !== 'slow' || runtime.rtd.playback.slow_reason !== 'csv_valve_change') {
    return null
  }
  return runtime.rtd.playback.valve_transitions[valveId] ?? null
}

function coerceDraftValue(draft, template) {
  if (Array.isArray(template)) {
    return Array.isArray(draft) ? draft.map((item, index) => coerceDraftValue(item, template[index] ?? template[0])) : template
  }
  if (template && typeof template === 'object') {
    const result = {}
    const source = draft && typeof draft === 'object' ? draft : {}
    Object.keys(template).forEach((key) => {
      result[key] = coerceDraftValue(source[key], template[key])
    })
    return result
  }
  if (typeof template === 'number') {
    const text = String(draft ?? '').trim()
    if (!text) return template
    const parsed = text.toLowerCase().startsWith('0x') ? Number.parseInt(text, 16) : Number(text)
    return Number.isFinite(parsed) ? parsed : template
  }
  if (template === null && typeof draft === 'string') {
    const text = draft.trim()
    if (!text) return null
    const parsed = text.toLowerCase().startsWith('0x') ? Number.parseInt(text, 16) : Number(text)
    return Number.isFinite(parsed) ? parsed : null
  }
  if (typeof template === 'boolean') {
    return Boolean(draft)
  }
  return draft ?? template
}

function buildFallbackRuntimeValve(valve) {
  if (valve.profile_type === 'ov') {
    return {
      ...valve,
      missing_board: true,
      mode: 'UNKNOWN',
      error: 'Awaiting runtime sync',
      position: valve.behavior.default_position,
      pending_action: null,
      detector_open_active: false,
      detector_close_active: false,
      feedback_open_active: false,
      feedback_close_active: false,
      open_feedback_output_on: valve.behavior.default_position === 'open',
      close_feedback_output_on: valve.behavior.default_position === 'closed',
      open_detector_address: valve.open_detector.i2c_address,
      open_detector_channel: valve.open_detector.channel,
      close_detector_address: valve.close_detector.i2c_address,
      close_detector_channel: valve.close_detector.channel,
      open_feedback_stack: valve.open_feedback.stack,
      open_feedback_channel: valve.open_feedback.channel,
      close_feedback_stack: valve.close_feedback.stack,
      close_feedback_channel: valve.close_feedback.channel,
    }
  }

  return {
    ...valve,
    missing_board: true,
    mode: 'UNKNOWN',
    vin: 0,
    vout: 0,
    target_vout: 0,
    detector_active: false,
    detector_address: valve.relay_detector?.i2c_address,
    detector_channel: valve.relay_detector?.channel,
    input_stack: valve.input_channel.stack,
    input_channel: valve.input_channel.channel,
    output_stack: valve.output_channel.stack,
    output_channel: valve.output_channel.channel,
    error: 'Awaiting runtime sync',
    override_active: false,
  }
}

function ValveConfigDialog({ valve, valveIndex, valveConfigs, config, onConfigChange, onClose }) {
  const [draftValve, setDraftValve] = useState(valve)
  const [saveError, setSaveError] = useState('')

  useEffect(() => {
    setDraftValve(valve)
    setSaveError('')
  }, [valve])

  if (!valve || !draftValve) return null

  const updateValve = (path, value) => {
    setSaveError('')
    setDraftValve((current) => updateConfigAtPath(current, path, value))
  }

  const replaceValve = (nextValve) => {
    setDraftValve(nextValve)
  }

  const handleProfileChange = (profileType) => {
    replaceValve(convertValveProfile(valveConfigs, draftValve, profileType))
  }

  const applyValveUpdate = async () => {
    const nextValve = coerceDraftValue(draftValve, valve)
    try {
      await onConfigChange(updateConfigAtPath(config, ['valves', 'ball_valves', valveIndex], nextValve))
      setDraftValve(nextValve)
      setSaveError('')
    } catch (error) {
      setSaveError(error.message || 'Valve config update failed')
    }
  }

  return (
    <div className="modal-backdrop">
      <div className="modal-card">
        <div className="inline-row spread">
          <div>
            <h3>{draftValve.id} Ball Valve Config</h3>
            <p>Edit this valve only. Changes stay local until you press Update.</p>
          </div>
          <div className="inline-row wrap">
            <button className="button-secondary" onClick={applyValveUpdate}>Update</button>
            <button onClick={onClose}>Close</button>
          </div>
        </div>
        {saveError ? <div className="error-text config-error">{saveError}</div> : null}

        <div className="form-grid">
          <label>
            <span>Valve ID</span>
            <input value={draftValve.id} onChange={(event) => updateValve(['id'], event.target.value)} />
          </label>

          <label>
            <span>Valve Name</span>
            <input value={draftValve.name} onChange={(event) => updateValve(['name'], event.target.value)} />
          </label>

          <label>
            <span>Enabled</span>
            <input type="checkbox" checked={!!draftValve.enabled} onChange={(event) => updateValve(['enabled'], event.target.checked)} />
          </label>

          <label>
            <span>Profile Type</span>
            <select value={draftValve.profile_type} onChange={(event) => handleProfileChange(event.target.value)}>
              <option value="cv">cv</option>
              <option value="ov">ov</option>
            </select>
          </label>
        </div>

        {draftValve.profile_type === 'cv' ? (
          <div className="form-grid">
            <label>
              <span>Relay Detector Address</span>
              <input value={formatEditableI2cAddress(draftValve.relay_detector.i2c_address)} onChange={(event) => updateValve(['relay_detector', 'i2c_address'], event.target.value)} />
            </label>
            <label>
              <span>Relay Detector Channel</span>
              <input value={draftValve.relay_detector.channel} onChange={(event) => updateValve(['relay_detector', 'channel'], event.target.value)} />
            </label>
            <label>
              <span>Input Stack</span>
              <input value={draftValve.input_channel.stack} onChange={(event) => updateValve(['input_channel', 'stack'], event.target.value)} />
            </label>
            <label>
              <span>Input Channel</span>
              <input value={draftValve.input_channel.channel} onChange={(event) => updateValve(['input_channel', 'channel'], event.target.value)} />
            </label>
            <label>
              <span>Output Stack</span>
              <input value={draftValve.output_channel.stack} onChange={(event) => updateValve(['output_channel', 'stack'], event.target.value)} />
            </label>
            <label>
              <span>Output Channel</span>
              <input value={draftValve.output_channel.channel} onChange={(event) => updateValve(['output_channel', 'channel'], event.target.value)} />
            </label>
            <label>
              <span>Ramp Seconds</span>
              <input value={draftValve.behavior.ramp_seconds} onChange={(event) => updateValve(['behavior', 'ramp_seconds'], event.target.value)} />
            </label>
            <label>
              <span>Minimum Feedback Voltage</span>
              <input value={draftValve.behavior.v_min} onChange={(event) => updateValve(['behavior', 'v_min'], event.target.value)} />
            </label>
            <label>
              <span>Maximum Feedback Voltage</span>
              <input value={draftValve.behavior.v_max} onChange={(event) => updateValve(['behavior', 'v_max'], event.target.value)} />
            </label>
            <label>
              <span>Command Detect Threshold</span>
              <input value={draftValve.behavior.cmd_threshold} onChange={(event) => updateValve(['behavior', 'cmd_threshold'], event.target.value)} />
            </label>
            <label>
              <span>Target Deadband</span>
              <input value={draftValve.behavior.target_deadband} onChange={(event) => updateValve(['behavior', 'target_deadband'], event.target.value)} />
            </label>
          </div>
        ) : (
          <div className="form-grid">
            <label>
              <span>Open Detector Address</span>
              <input value={formatEditableI2cAddress(draftValve.open_detector.i2c_address)} onChange={(event) => updateValve(['open_detector', 'i2c_address'], event.target.value)} />
            </label>
            <label>
              <span>Open Detector Relay Channel</span>
              <input value={draftValve.open_detector.channel} onChange={(event) => updateValve(['open_detector', 'channel'], event.target.value)} />
            </label>
            <label>
              <span>Close Detector Address</span>
              <input value={formatEditableI2cAddress(draftValve.close_detector.i2c_address)} onChange={(event) => updateValve(['close_detector', 'i2c_address'], event.target.value)} />
            </label>
            <label>
              <span>Close Detector Relay Channel</span>
              <input value={draftValve.close_detector.channel} onChange={(event) => updateValve(['close_detector', 'channel'], event.target.value)} />
            </label>
            <label>
              <span>Open Feedback Stack</span>
              <input value={draftValve.open_feedback.stack} onChange={(event) => updateValve(['open_feedback', 'stack'], event.target.value)} />
            </label>
            <label>
              <span>Open Feedback Relay Channel</span>
              <input value={draftValve.open_feedback.channel} onChange={(event) => updateValve(['open_feedback', 'channel'], event.target.value)} />
            </label>
            <label>
              <span>Close Feedback Stack</span>
              <input value={draftValve.close_feedback.stack} onChange={(event) => updateValve(['close_feedback', 'stack'], event.target.value)} />
            </label>
            <label>
              <span>Close Feedback Relay Channel</span>
              <input value={draftValve.close_feedback.channel} onChange={(event) => updateValve(['close_feedback', 'channel'], event.target.value)} />
            </label>
            <label>
              <span>Relay Response Delay (s)</span>
              <input value={draftValve.behavior.detector_delay_seconds} onChange={(event) => updateValve(['behavior', 'detector_delay_seconds'], event.target.value)} />
            </label>
            <label>
              <span>Relay Closing/Opening Window (s)</span>
              <input value={draftValve.behavior.feedback_hold_seconds} onChange={(event) => updateValve(['behavior', 'feedback_hold_seconds'], event.target.value)} />
            </label>
            <label>
              <span>Default Valve Position</span>
              <select value={draftValve.behavior.default_position} onChange={(event) => updateValve(['behavior', 'default_position'], event.target.value)}>
                <option value="open">open</option>
                <option value="closed">closed</option>
              </select>
            </label>
          </div>
        )}
      </div>
    </div>
  )
}

function DetectorIndicator({ label, active, tone = 'neutral' }) {
  return (
    <div className={`signal-card ${active ? 'active' : ''} ${tone}`}>
      <span className="signal-label">{label}</span>
      <strong className="signal-value">{active ? 'ON' : 'OFF'}</strong>
      <span className="signal-meta">{active ? '1' : '0'}</span>
    </div>
  )
}

function MetricCard({ label, value, tone = 'neutral', accent = false }) {
  const classes = ['metric-card']
  if (accent) classes.push('accent')
  if (tone !== 'neutral') classes.push(tone)
  return (
    <div className={classes.join(' ')}>
      <span className="metric-label">{label}</span>
      <strong className="metric-value">{value}</strong>
    </div>
  )
}

function CvOpenMetric({ label, voltage, behavior, tone = 'neutral' }) {
  const classes = ['metric-card', 'cv-open-metric']
  if (tone !== 'neutral') classes.push(tone)
  const display = formatCvOpenPercentage(voltage, behavior)

  return (
    <div className={classes.join(' ')}>
      <span className="metric-label">{label}</span>
      <strong className="metric-value">{display.percent}</strong>
      <span className="cv-open-voltage">{display.voltage}</span>
    </div>
  )
}

function BulkValveConfigDialog({ profileType, valveConfigs, config, onConfigChange, onClose, open }) {
  const [draftValves, setDraftValves] = useState(valveConfigs)
  const [saveError, setSaveError] = useState('')
  const activeValves = Array.isArray(draftValves) ? draftValves : valveConfigs

  useEffect(() => {
    if (!open || !Array.isArray(valveConfigs)) {
      return
    }
    setDraftValves(valveConfigs)
    setSaveError('')
  }, [open, profileType, valveConfigs])

  if (!profileType || !Array.isArray(valveConfigs) || !Array.isArray(activeValves)) return null

  const updateValve = (index, path, value) => {
    setSaveError('')
    setDraftValves((current) => current.map((valve, valveIndex) => (
      valveIndex === index ? updateConfigAtPath(valve, path, value) : valve
    )))
  }

  const applyBulkUpdate = async () => {
    const nextValves = activeValves.map((valve, index) => coerceDraftValue(valve, valveConfigs[index]))
    const nextById = new Map(nextValves.map((valve) => [valve.id, valve]))
    const mergedValves = config.valves.ball_valves.map((valve) => nextById.get(valve.id) ?? valve)
    try {
      await onConfigChange(updateConfigAtPath(config, ['valves', 'ball_valves'], mergedValves))
      setDraftValves(nextValves)
      setSaveError('')
    } catch (error) {
      setSaveError(error.message || 'Bulk valve config update failed')
    }
  }

  return (
    <div className="modal-backdrop">
      <div className="modal-card modal-card-wide">
        <div className="inline-row spread">
          <div>
            <h3>{profileType.toUpperCase()} Valve Bulk Config</h3>
            <p>Edits stay local until you press Update. These fields match the individual ball valve card editor.</p>
          </div>
          <div className="inline-row wrap">
            <button className="button-secondary" onClick={applyBulkUpdate}>Update</button>
            <button onClick={onClose}>Close</button>
          </div>
        </div>
        {saveError ? <div className="error-text config-error">{saveError}</div> : null}

        <div className="table-wrap tall">
          <table>
            <thead>
              <tr>
                <th>Valve ID</th>
                <th>Valve Name</th>
                <th>Enabled</th>
                <th>Mapping</th>
                <th>Behavior</th>
              </tr>
            </thead>
            <tbody>
              {activeValves.map((valve, index) => (
                <tr key={`${valve.id}-${index}`}>
                  <td>
                    <input value={valve.id} onChange={(event) => updateValve(index, ['id'], event.target.value)} />
                  </td>
                  <td>
                    <input value={valve.name} onChange={(event) => updateValve(index, ['name'], event.target.value)} />
                  </td>
                  <td>
                    <input type="checkbox" checked={!!valve.enabled} onChange={(event) => updateValve(index, ['enabled'], event.target.checked)} />
                  </td>
                  <td>
                    {profileType === 'cv' ? (
                      <div className="table-cell-grid">
                        <label>
                          <span>Relay Detector Address</span>
                          <input value={formatEditableI2cAddress(valve.relay_detector.i2c_address)} onChange={(event) => updateValve(index, ['relay_detector', 'i2c_address'], event.target.value)} />
                        </label>
                        <label>
                          <span>Relay Detector Channel</span>
                          <input value={valve.relay_detector.channel} onChange={(event) => updateValve(index, ['relay_detector', 'channel'], event.target.value)} />
                        </label>
                        <label>
                          <span>Input Stack</span>
                          <input value={valve.input_channel.stack} onChange={(event) => updateValve(index, ['input_channel', 'stack'], event.target.value)} />
                        </label>
                        <label>
                          <span>Input Channel</span>
                          <input value={valve.input_channel.channel} onChange={(event) => updateValve(index, ['input_channel', 'channel'], event.target.value)} />
                        </label>
                        <label>
                          <span>Output Stack</span>
                          <input value={valve.output_channel.stack} onChange={(event) => updateValve(index, ['output_channel', 'stack'], event.target.value)} />
                        </label>
                        <label>
                          <span>Output Channel</span>
                          <input value={valve.output_channel.channel} onChange={(event) => updateValve(index, ['output_channel', 'channel'], event.target.value)} />
                        </label>
                      </div>
                    ) : (
                      <div className="table-cell-grid">
                        <label>
                          <span>Open Detector Address</span>
                          <input value={formatEditableI2cAddress(valve.open_detector.i2c_address)} onChange={(event) => updateValve(index, ['open_detector', 'i2c_address'], event.target.value)} />
                        </label>
                        <label>
                          <span>Open Detector Relay Channel</span>
                          <input value={valve.open_detector.channel} onChange={(event) => updateValve(index, ['open_detector', 'channel'], event.target.value)} />
                        </label>
                        <label>
                          <span>Close Detector Address</span>
                          <input value={formatEditableI2cAddress(valve.close_detector.i2c_address)} onChange={(event) => updateValve(index, ['close_detector', 'i2c_address'], event.target.value)} />
                        </label>
                        <label>
                          <span>Close Detector Relay Channel</span>
                          <input value={valve.close_detector.channel} onChange={(event) => updateValve(index, ['close_detector', 'channel'], event.target.value)} />
                        </label>
                        <label>
                          <span>Open Feedback Stack</span>
                          <input value={valve.open_feedback.stack} onChange={(event) => updateValve(index, ['open_feedback', 'stack'], event.target.value)} />
                        </label>
                        <label>
                          <span>Open Feedback Relay Channel</span>
                          <input value={valve.open_feedback.channel} onChange={(event) => updateValve(index, ['open_feedback', 'channel'], event.target.value)} />
                        </label>
                        <label>
                          <span>Close Feedback Stack</span>
                          <input value={valve.close_feedback.stack} onChange={(event) => updateValve(index, ['close_feedback', 'stack'], event.target.value)} />
                        </label>
                        <label>
                          <span>Close Feedback Relay Channel</span>
                          <input value={valve.close_feedback.channel} onChange={(event) => updateValve(index, ['close_feedback', 'channel'], event.target.value)} />
                        </label>
                      </div>
                    )}
                  </td>
                  <td>
                    {profileType === 'cv' ? (
                      <div className="table-cell-grid">
                        <label>
                          <span>Ramp Seconds</span>
                          <input value={valve.behavior.ramp_seconds} onChange={(event) => updateValve(index, ['behavior', 'ramp_seconds'], event.target.value)} />
                        </label>
                        <label>
                          <span>Minimum Feedback Voltage</span>
                          <input value={valve.behavior.v_min} onChange={(event) => updateValve(index, ['behavior', 'v_min'], event.target.value)} />
                        </label>
                        <label>
                          <span>Maximum Feedback Voltage</span>
                          <input value={valve.behavior.v_max} onChange={(event) => updateValve(index, ['behavior', 'v_max'], event.target.value)} />
                        </label>
                        <label>
                          <span>Command Detect Threshold</span>
                          <input value={valve.behavior.cmd_threshold} onChange={(event) => updateValve(index, ['behavior', 'cmd_threshold'], event.target.value)} />
                        </label>
                        <label>
                          <span>Target Deadband</span>
                          <input value={valve.behavior.target_deadband} onChange={(event) => updateValve(index, ['behavior', 'target_deadband'], event.target.value)} />
                        </label>
                      </div>
                    ) : (
                      <div className="table-cell-grid">
                        <label>
                          <span>Relay Response Delay (s)</span>
                          <input value={valve.behavior.detector_delay_seconds} onChange={(event) => updateValve(index, ['behavior', 'detector_delay_seconds'], event.target.value)} />
                        </label>
                        <label>
                          <span>Relay Closing/Opening Window (s)</span>
                          <input value={valve.behavior.feedback_hold_seconds} onChange={(event) => updateValve(index, ['behavior', 'feedback_hold_seconds'], event.target.value)} />
                        </label>
                        <label>
                          <span>Default Valve Position</span>
                          <select value={valve.behavior.default_position} onChange={(event) => updateValve(index, ['behavior', 'default_position'], event.target.value)}>
                            <option value="open">open</option>
                            <option value="closed">closed</option>
                          </select>
                        </label>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

export default function ValvePage({ runtime, config, onConfigChange, onValveOverride }) {
  const [drafts, setDrafts] = useState({})
  const [editingValveId, setEditingValveId] = useState(null)
  const [bulkEditingType, setBulkEditingType] = useState(null)
  const [targetCounts, setTargetCounts] = useState({ cv: '0', ov: '0' })

  const valveConfigs = config.valves.ball_valves
  const runtimeValves = runtime.valves?.ball_valves ?? []
  const runtimeById = useMemo(
    () => Object.fromEntries(runtimeValves.map((valve) => [valve.id, valve])),
    [runtimeValves],
  )

  const detectors = runtime.valves?.relay_detectors ?? []
  const valveIndex = valveConfigs.findIndex((item) => item.id === editingValveId)
  const editingValve = valveIndex >= 0 ? valveConfigs[valveIndex] : null
  const cvValves = useMemo(
    () => valveConfigs.filter((valve) => valve.profile_type === 'cv'),
    [valveConfigs],
  )
  const ovValves = useMemo(
    () => valveConfigs.filter((valve) => valve.profile_type === 'ov'),
    [valveConfigs],
  )
  const bulkEditingValves = useMemo(() => {
    if (bulkEditingType === 'cv') return cvValves
    if (bulkEditingType === 'ov') return ovValves
    return null
  }, [bulkEditingType, cvValves, ovValves])

  useEffect(() => {
    setTargetCounts({
      cv: String(cvValves.length),
      ov: String(ovValves.length),
    })
  }, [cvValves.length, ovValves.length])

  const addValve = (profileType = 'cv') => {
    const nextValve = createDefaultValve(valveConfigs, profileType)
    onConfigChange({
      ...config,
      valves: {
        ...config.valves,
        ball_valves: [...valveConfigs, nextValve],
      },
    })
    setEditingValveId(nextValve.id)
  }

  const deleteValve = (id) => {
    onConfigChange({
      ...config,
      valves: {
        ...config.valves,
        ball_valves: valveConfigs.filter((valve) => valve.id !== id),
      },
    })
    if (editingValveId === id) {
      setEditingValveId(null)
    }
  }

  const resizeValveCollection = async (profileType) => {
    const requestedCount = Number(targetCounts[profileType])
    if (!Number.isInteger(requestedCount) || requestedCount < 0) {
      return
    }

    const matchingValves = valveConfigs.filter((valve) => valve.profile_type === profileType)
    const otherValves = valveConfigs.filter((valve) => valve.profile_type !== profileType)
    let nextMatching = [...matchingValves]

    if (requestedCount < nextMatching.length) {
      nextMatching = nextMatching.slice(0, requestedCount)
    } else {
      while (nextMatching.length < requestedCount) {
        nextMatching.push(createDefaultValve([...otherValves, ...nextMatching], profileType))
      }
    }

    await onConfigChange({
      ...config,
      valves: {
        ...config.valves,
        ball_valves: [...otherValves, ...nextMatching],
      },
    })
  }

  const renderValveSection = (title, subtitle, valves, addProfileType) => (
    <Card
      title={title}
      subtitle={subtitle}
      collapsible
      defaultExpanded
      actions={(
        <div className="inline-row wrap">
          <input
            className="count-input"
            type="number"
            min="0"
            value={targetCounts[addProfileType] ?? '0'}
            onChange={(event) => setTargetCounts((current) => ({ ...current, [addProfileType]: event.target.value }))}
          />
          <button className="button-secondary" onClick={() => resizeValveCollection(addProfileType)}>Set Count</button>
          <button className="button-secondary" onClick={() => setBulkEditingType(addProfileType)}>Bulk Config</button>
        </div>
      )}
    >
      <div className="valve-grid">
        {valves.map((configValve) => {
          const valve = runtimeById[configValve.id] ?? buildFallbackRuntimeValve(configValve)
          const schedulingTransition = getSchedulingTransition(runtime, configValve.id)

          return (
            <div key={configValve.id} className={getValveCardClass(configValve, valve)}>
              <div className="inline-row spread">
                <div>
                  <strong>{configValve.name}</strong>
                  <div className="valve-meta">{configValve.id}</div>
                </div>
                <div className="inline-row wrap">
                  <span className={`profile-chip ${configValve.profile_type}`}>{configValve.profile_type.toUpperCase()}</span>
                  {schedulingTransition ? <span className="status-chip slow">{schedulingTransition}</span> : null}
                </div>
              </div>

              {configValve.profile_type === 'cv' ? (
                <>
                  <div className="valve-state-banner">
                    <span className="valve-state-label">CV State</span>
                    <strong className="valve-state-value">{getCvSummary(valve)}</strong>
                    <span className="valve-state-subtitle">{schedulingTransition ? `CSV marker transition ${schedulingTransition}` : getCvSubtitle(valve)}</span>
                  </div>
                  <div className="valve-metric-grid">
                    <DetectorIndicator label="Relay Detector" active={valve.detector_active} tone="cv" />
                    <MetricCard label={getCvVinLabel(valve)} value={`${Number(valve.vin).toFixed(2)}V`} tone="cv" accent={valve.detector_active} />
                    <MetricCard label="FB Vout" value={`${Number(valve.vout).toFixed(2)}V`} tone={valve.detector_active ? 'open' : 'standby'} accent />
                    <CvOpenMetric
                      label={getCvPositionLabel(valve)}
                      voltage={valve.target_vout}
                      behavior={configValve.behavior}
                      tone={valve.detector_active ? 'open' : 'standby'}
                    />
                  </div>
                  <div className="valve-detail-list subdued">
                    <div className="inline-row spread"><span>Relay Detector</span><span>{formatDetectorChannel(configValve.relay_detector)}</span></div>
                    <div className="inline-row spread"><span>Input VIN</span><span>{formatAnalogChannel(configValve.input_channel)}</span></div>
                    <div className="inline-row spread"><span>Output VOUT</span><span>{formatAnalogChannel(configValve.output_channel)}</span></div>
                    <div className="inline-row spread"><span>Ramp Time</span><span>{Number(configValve.behavior.ramp_seconds).toFixed(0)} s full travel</span></div>
                  </div>
                  <div className="inline-row wrap">
                    <input
                      type="number"
                      step="0.1"
                      placeholder="Override VIN"
                      value={drafts[configValve.id] ?? ''}
                      onChange={(event) => setDrafts((prev) => ({ ...prev, [configValve.id]: event.target.value }))}
                    />
                    <button onClick={() => onValveOverride(configValve.id, drafts[configValve.id] === '' ? null : Number(drafts[configValve.id]))}>Set</button>
                    <button onClick={() => { setDrafts((prev) => ({ ...prev, [configValve.id]: '' })); onValveOverride(configValve.id, null) }}>Clear</button>
                  </div>
                </>
              ) : (
                <>
                  <div className="valve-state-banner">
                    <span className="valve-state-label">OV State</span>
                    <strong className="valve-state-value">{getOvSummary(valve, configValve)}</strong>
                    <span className="valve-state-subtitle">{schedulingTransition ? `CSV marker transition ${schedulingTransition}` : `Mode ${valve.mode}`}</span>
                  </div>
                  <div className="valve-signal-grid">
                    <DetectorIndicator label="Open Detector" active={valve.detector_open_active} tone="open" />
                    <DetectorIndicator label="Close Detector" active={valve.detector_close_active} tone="close" />
                    <DetectorIndicator label="Open Feedback Relay" active={valve.open_feedback_output_on} tone="open" />
                    <DetectorIndicator label="Close Feedback Relay" active={valve.close_feedback_output_on} tone="close" />
                  </div>
                  <div className="valve-detail-list subdued">
                    <div className="inline-row spread"><span>Position</span><span>{valve.position ? String(valve.position).toUpperCase() : 'MID-TRAVEL'}</span></div>
                    <div className="inline-row spread"><span>Pending</span><span>{valve.pending_action ? valve.pending_action.toUpperCase() : 'None'}</span></div>
                    <div className="inline-row spread"><span>Open Detect</span><span>{formatDetectorChannel(configValve.open_detector)}</span></div>
                    <div className="inline-row spread"><span>Close Detect</span><span>{formatDetectorChannel(configValve.close_detector)}</span></div>
                    <div className="inline-row spread"><span>Open Feedback</span><span>{formatFeedbackChannel(configValve.open_feedback)}</span></div>
                    <div className="inline-row spread"><span>Close Feedback</span><span>{formatFeedbackChannel(configValve.close_feedback)}</span></div>
                  </div>
                </>
              )}

              <div className="inline-row wrap valve-actions">
                <button className="button-secondary" onClick={() => setEditingValveId(configValve.id)}>Ball Valve Config</button>
                <button className="button-danger" onClick={() => deleteValve(configValve.id)}>Delete</button>
              </div>
              <div className="error-text">{valve.error || (valve.override_active ? 'Software override active' : 'OK')}</div>
            </div>
          )
        })}

        <button className="add-card" onClick={() => addValve(addProfileType)}>
          <span className="add-card-mark">+</span>
          <strong>Add Ball Valve</strong>
          <span>Creates a new {addProfileType.toUpperCase()} valve and keeps bulk config synchronized.</span>
        </button>
      </div>
    </Card>
  )

  return (
    <>
      <div className="page-grid">
        {renderValveSection('CV Valves', 'Continuous valves use a relay detector gate. Detector ON restores the last matched position and tracks analog VIN; detector OFF forces analog feedback to 0V.', cvValves, 'cv')}
        {renderValveSection('OV Valves', 'Open-close valves use relay detector inputs. Feedback relays are ON (5V) at the matching end, OFF (0V) otherwise. Both OFF indicates mid-travel.', ovValves, 'ov')}

        <Card title="Relay Detectors" subtitle="Configured MCP23017 detector boards and their latest 16-channel word.">
          <div className="analog-output-grid">
            {detectors.map((detector) => (
              <div key={`${detector.i2c_address}-${detector.i2c_bus}`} className={detector.available ? 'analog-output-card' : 'analog-output-card missing'}>
                <strong>{formatI2cAddress(detector.i2c_address)}</strong>
                <span>Bus {detector.i2c_bus}</span>
                <span>Word {formatHexWord(detector.last_word)}</span>
                <span>{detector.available ? 'Available' : (detector.error || 'Unavailable')}</span>
              </div>
            ))}
          </div>
        </Card>
      </div>

      <ValveConfigDialog
        valve={editingValve}
        valveIndex={valveIndex}
        valveConfigs={valveConfigs}
        config={config}
        onConfigChange={onConfigChange}
        onClose={() => setEditingValveId(null)}
      />
      <BulkValveConfigDialog
        profileType={bulkEditingType}
        valveConfigs={bulkEditingValves}
        config={config}
        onConfigChange={onConfigChange}
        open={Boolean(bulkEditingType)}
        onClose={() => setBulkEditingType(null)}
      />
    </>
  )
}
