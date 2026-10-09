import { useEffect, useState } from 'react'
import Card from '../../components/common/Card'

const CONTROL_MODES = { 1: 'Constant Curve', 2: 'Constant Pressure', 3: 'Proportional Pressure', 4: 'Auto Adapt', 5: 'Constant Flow', 6: 'Constant Temperature', 9: 'Flow Adapt', 12: 'Differential Temperature' }
const OPERATING_MODES = { 1: 'Start', 2: 'Stop', 3: 'Minimum', 4: 'Maximum' }
const INITIAL_FIELDS = [
  ['control_mode', 'Control mode', CONTROL_MODES], ['operating_mode', 'Operating mode', OPERATING_MODES],
  ['setpoint', 'Setpoint (%)'], ['fault_code', 'Fault code'], ['warning_code', 'Warning code'],
  ['operating_hours', 'Operating time (h)'], ['on_hours', 'Powered time (h)'],
]
const READING_FIELDS = [
  ['flow_gpm', 'Nominal flow (GPM)'], ['pressure_psi', 'Nominal pressure (PSI)'],
  ['power_w', 'Nominal power (W)'], ['current_a', 'Nominal current (A)'],
  ['temperature_c', 'Liquid temperature (°C)'], ['remote_temperature_c', 'Remote temperature (°C)'],
  ['electronics_temperature_c', 'Electronics temperature (°C)'],
]
const BASIC_FIELDS = [
  ['name', 'Name', 'pump'], ['id', 'Card ID', 'pump'], ['device_id', 'BACnet device instance', 'pump'],
  ['mac', 'MS/TP MAC', 'pump'], ['serial_port', 'RS485 adapter', null],
  ['baud', 'Baud rate', null], ['router_mac', 'BASrouter MAC', null],
  ['max_master', 'Max Master', null], ['max_info_frames', 'Max Info Frames', null],
]

function newDevice(devices) {
  const id = Math.max(0, ...devices.map((d) => Number(d.pump.id) || 0)) + 1
  const first = devices[0]
  const serial_port = first?.serial_port || '/dev/ttyUSB0'
  const router_mac = first?.router_mac ?? 10
  const used = new Set(devices.filter((d) => d.serial_port === serial_port).map((d) => Number(d.pump.mac)))
  let mac = 11
  while (used.has(mac) || mac === Number(router_mac)) mac += 1
  let device_id = 227000 + mac
  while (devices.some((d) => Number(d.pump.device_id) === device_id)) device_id += 1
  return {
    _key: `new-${Date.now()}-${id}`, _savedId: null,
    serial_port, baud: first?.baud ?? 9600, max_master: first?.max_master ?? 127,
    max_info_frames: 1, router_mac,
    pump: { id, name: `Grundfos Pump ${id}`, mac, device_id },
    initial: { bus_control: false, control_mode: 1, operating_mode: 2, setpoint: 50, fault_code: 0, warning_code: 0, operating_hours: 0, on_hours: 0 },
    readings: { flow_gpm: 40, pressure_psi: 15, power_w: 150, current_a: 1.2, temperature_c: 23, remote_temperature_c: 24, electronics_temperature_c: 35 },
  }
}

function numeric(value) {
  if (String(value).trim() === '' || !Number.isFinite(Number(value))) throw new Error('Enter a finite number in every numeric field.')
  return Number(value)
}

function normalize(device) {
  const { _key, _savedId, ...settings } = device
  return {
    ...settings,
    ...Object.fromEntries(['baud', 'max_master', 'max_info_frames', 'router_mac'].map((field) => [field, numeric(device[field])])),
    pump: { ...device.pump, ...Object.fromEntries(['id', 'mac', 'device_id'].map((field) => [field, numeric(device.pump[field])])) },
    initial: { ...Object.fromEntries(INITIAL_FIELDS.map(([field]) => [field, numeric(device.initial[field])])), bus_control: device.initial.bus_control },
    readings: Object.fromEntries(READING_FIELDS.map(([field]) => [field, numeric(device.readings[field])])),
  }
}

function draftDevices(devices) {
  return devices.map((device) => ({ ...device, _key: `saved-${device.pump.id}`, _savedId: device.pump.id }))
}

function withoutDraftKeys(device) {
  const { _key, _savedId, ...settings } = device
  return settings
}

function Editor({ value, onChange, choices, disabled = false, label, minimum, maximum }) {
  return choices ? (
    <select aria-label={label} disabled={disabled} value={value ?? ''} onChange={(event) => onChange(event.target.value)}>
      {value == null ? <option value="">Select value</option> : null}
      {Object.entries(choices).map(([key, text]) => <option key={key} value={key}>{key} — {text}</option>)}
    </select>
  ) : <input aria-label={label} disabled={disabled} type="number" step="any" min={minimum} max={maximum} value={value ?? ''} onChange={(event) => onChange(event.target.value)} />
}

function display(value, point) {
  if (value == null) return '—'
  if (point.choices) return `${value} — ${point.choices[value] ?? 'Unknown'}`
  return `${Number(value).toLocaleString(undefined, { maximumFractionDigits: 3 })} ${point.unit || ''}`
}

export default function GrundfosPage({ config, runtime, onConfigChange, onStartGroup, onStopGroup, onSetValue }) {
  const savedDevices = config.grundfos?.devices ?? []
  const [devices, setDevices] = useState(() => draftDevices(savedDevices))
  const [values, setValues] = useState({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const pumpRuntime = runtime.grundfos ?? { devices: [], points: [], groups: [], simulation_fields: [] }

  useEffect(() => { setDevices(draftDevices(config.grundfos?.devices ?? [])); setValues({}) }, [config.grundfos])
  const unsaved = JSON.stringify(devices.map(withoutDraftKeys)) !== JSON.stringify(savedDevices)

  const action = async (fn, message) => {
    setBusy(true)
    setError('')
    setNotice('')
    try { await fn(); setNotice(message) } catch (err) { setError(err.message || 'Pump action failed') } finally { setBusy(false) }
  }
  const update = (index, section, field, value) => setDevices((current) => current.map((device, i) => i !== index ? device : (
    section ? { ...device, [section]: { ...device[section], [field]: value } } : { ...device, [field]: value }
  )))
  const applyValue = (pid, field, fallback, release = false) => action(async () => {
    const key = `${pid}:${field}`
    await onSetValue(pid, field, release ? null : numeric(values[key] ?? fallback ?? ''))
    setValues((current) => { const next = { ...current }; delete next[key]; return next })
  }, release ? 'Released. Live values reflect the engine state.' : 'Pump engine acknowledged the change.')

  return <div className="page-grid">
    <Card title="Grundfos BACnet MS/TP Pumps" subtitle="One card per pump. Pumps sharing an RS485 adapter start and stop together."
      actions={<div className="button-row">
        <button disabled={busy} className="button-secondary" onClick={() => setDevices((current) => [...current, newDevice(current)])}>Add Pump</button>
        <button disabled={busy} onClick={() => action(() => onConfigChange({ ...config, grundfos: { devices: devices.map(normalize) } }), 'Pump configuration saved. Start an adapter group to go online.')}>Save Pump Config</button>
      </div>}>
      <p>{pumpRuntime.message || 'Loading pump transport status…'}</p>
      <p>Connect the emulator adapter to the BASrouter MS/TP trunk. The controller keeps its BASrouter IP and network settings in <code>src/utils/bacnet_routers.py</code>; match the pump MAC and device instance here.</p>
      <p>Save startup settings before starting. Live edits last until the adapter group is restarted. Starting this module does not confirm that the controller can reach it.</p>
      <p>Original controller compatibility: BI31 mirrors BusControl. An active bus AO5 command is in GPM and makes AI5 echo that command after the controller's ×4.4 conversion, even while stopped. Release AO5 to restore simulated flow. Use commands with at most two decimal places for the controller's confirmation.</p>
      {error ? <p className="error-text" role="alert">{error}</p> : null}
      {notice ? <p role="status">{notice}</p> : null}
    </Card>

    {devices.map((device, index) => {
      const saved = savedDevices.find((d) => d.pump.id === device._savedId)
      const state = pumpRuntime.devices.find((d) => d.id === saved?.pump.id)
      const pid = saved?.pump.id
      const live = Boolean(state?.live)
      const changed = !saved || JSON.stringify(withoutDraftKeys(device)) !== JSON.stringify(saved)
      const points = pumpRuntime.points ?? []
      const currentValues = state?.values ?? {}
      return <Card key={device._key} title={device.pump.name || 'New pump'}
        subtitle={`Device ${device.pump.device_id} · MAC ${device.pump.mac} · ${state?.active ? (live ? 'Running' : 'Starting / stale state') : 'Stopped'}${changed ? ' · Unsaved edits' : ''}`}
        actions={<div className="button-row">
          <button disabled={busy || unsaved || state?.active || !pumpRuntime.transport_available} onClick={() => action(() => onStartGroup(pid), 'Adapter group started. Verify reads from the controller.')}>Start Adapter Group</button>
          <button disabled={busy || !state?.active} onClick={() => action(() => onStopGroup(pid), 'Adapter group stopped.')}>Stop Adapter Group</button>
          <button className="button-secondary" disabled={busy || state?.active} onClick={() => setDevices((current) => current.filter((_, i) => i !== index))}>Remove Card</button>
        </div>}>
        {state?.error ? <p className="error-text">{state.error}</p> : null}
        {!live ? <p>Values below are {Object.keys(currentValues).length ? 'the last received snapshot' : 'unavailable until this pump is started'}.</p> : null}
        <details className="arctic-advanced-block" open={!state?.active}>
          <summary>Device settings and saved starting values</summary>
          <fieldset disabled={busy || state?.active} className="grundfos-config-fields">
            <div className="form-grid compact">
              {BASIC_FIELDS.map(([field, label, section]) => <label key={field}><span>{label}</span>
                <input type={['name', 'serial_port'].includes(field) ? 'text' : 'number'} value={(section ? device[section][field] : device[field]) ?? ''}
                  onChange={(event) => update(index, section, field, event.target.value)} />
              </label>)}
              <label><span>Start in bus control</span><select value={String(device.initial.bus_control)} onChange={(event) => update(index, 'initial', 'bus_control', event.target.value === 'true')}><option value="false">Local</option><option value="true">Bus</option></select></label>
              {INITIAL_FIELDS.map(([field, label, choices]) => <label key={field}><span>{label}</span><Editor label={label} value={device.initial[field]} choices={choices} onChange={(value) => update(index, 'initial', field, value)} /></label>)}
              {READING_FIELDS.map(([field, label]) => <label key={field}><span>{label}</span><Editor label={label} value={device.readings[field]} onChange={(value) => update(index, 'readings', field, value)} /></label>)}
            </div>
          </fieldset>
        </details>

        <div className="arctic-summary-grid">
          {['binaryInput,0', 'multiStateInput,1', 'analogInput,9', 'analogInput,5', 'analogInput,4', 'analogInput,13'].map((object) => {
            const point = points.find((p) => p.object === object)
            if (!point) return null
            return <article className="arctic-summary-card" key={object}><span>{point.name}</span><strong>{display(currentValues[object], point)}</strong><small>{object}</small></article>
          })}
        </div>

        <h4>Controller-writable commands</h4>
        <p>Enable BusControl to apply remote commands. Card and controller writes both use priority 1; the latest write wins. Release clears that priority slot, including a value last written by the controller.</p>
        <div className="arctic-register-grid">
          {points.filter((p) => p.writable).map((point) => {
            const key = `${pid}:${point.field}`
            return <article className="arctic-register-card" key={point.object}>
              <h5>{point.name}</h5><small>{point.object}</small><p>Current: {display(currentValues[point.object], point)}</p>
              <Editor label={`${device.pump.name} ${point.name}`} value={values[key] ?? currentValues[point.object]} choices={point.choices} minimum={point.minimum} maximum={point.maximum} disabled={busy || !live}
                onChange={(value) => setValues((current) => ({ ...current, [key]: value }))} />
              <div className="button-row"><button disabled={busy || !live} onClick={() => applyValue(pid, point.field, currentValues[point.object])}>Apply</button><button className="button-secondary" disabled={busy || !live} onClick={() => applyValue(pid, point.field, null, true)}>Release</button></div>
            </article>
          })}
        </div>

        <details className="arctic-advanced-block">
          <summary>Readable BACnet values and measurement overrides</summary>
          <p>Inputs remain read-only over BACnet. Card edits inject simulated measurements. Overrides stay fixed until Release or restart; a new AO5 command also clears the flow override so the original controller can confirm it. AI5 and pressure use m³/h and bar; the controller displays GPM (×4.4) and PSI (×14.5). BI31 follows BusControl for controller compatibility.</p>
          <div className="table-wrap"><table><thead><tr><th>Object</th><th>Reading</th><th>Current</th><th>New value</th><th>Action</th></tr></thead><tbody>
            {points.filter((p) => !p.writable).map((point) => {
              const key = `${pid}:${point.field}`
              const overridden = state?.overrides?.includes(point.field)
              return <tr key={point.object}><td>{point.object}</td><td>{point.name}{overridden ? ' (overridden)' : ''}</td><td>{display(currentValues[point.object], point)}</td>
                <td>{point.field ? <Editor label={`${device.pump.name} ${point.name}`} value={values[key] ?? currentValues[point.object]} choices={point.choices} minimum={point.minimum} maximum={point.maximum} disabled={busy || !live}
                  onChange={(value) => setValues((current) => ({ ...current, [key]: value }))} /> : 'Follows commands'}</td>
                <td>{point.field ? <div className="button-row"><button disabled={busy || !live} onClick={() => applyValue(pid, point.field, currentValues[point.object])}>Apply</button>{point.field.startsWith('ai_') ? <button className="button-secondary" disabled={busy || !live || !overridden} onClick={() => applyValue(pid, point.field, null, true)}>Release</button> : null}</div> : null}</td>
              </tr>
            })}
          </tbody></table></div>
        </details>
        <details className="arctic-advanced-block">
          <summary>Live nominal readings and local controls</summary>
          <p>Nominal flow, pressure, power and current scale with pump operation and setpoint. Local mode and setpoint apply when BusControl is Local. Set powered hours before increasing operating hours.</p>
          <div className="arctic-register-grid">{(pumpRuntime.simulation_fields ?? []).map((field) => {
            const key = `${pid}:${field.field}`
            const current = state?.simulation?.[field.field]
            return <article className="arctic-register-card" key={field.field}><h5>{field.name}</h5><p>Current: {current ?? '—'}</p>
              <Editor label={`${device.pump.name} ${field.name}`} value={values[key] ?? current} choices={field.choices} minimum={field.minimum} maximum={field.maximum} disabled={busy || !live} onChange={(value) => setValues((previous) => ({ ...previous, [key]: value }))} />
              <button disabled={busy || !live} onClick={() => applyValue(pid, field.field, current)}>Apply</button>
            </article>
          })}</div>
        </details>
      </Card>
    })}
    {(pumpRuntime.groups ?? []).map((group) => <Card key={group.serial_port} title={`Adapter: ${group.serial_port}`} subtitle={group.error || (group.running ? 'MS/TP engine running' : 'Stopped')}>
      <details><summary>Recent adapter messages</summary><pre className="grundfos-log">{group.logs.join('\n') || 'No messages'}</pre></details>
    </Card>)}
  </div>
}
