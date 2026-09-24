import { useEffect, useState } from 'react'

import Card from '../../components/common/Card'

const MODE_LABELS = {
  0: 'Cooling',
  1: 'Underfloor Heat',
  2: 'Fan Coil Heat',
  5: 'Hot Water',
  6: 'Auto',
}

const PRIMARY_SUMMARY = [
  { address: 2000, label: 'Power State' },
  { address: 2001, label: 'Working Mode' },
  { address: 2002, label: 'Cooling Setpoint' },
  { address: 2003, label: 'Heating Setpoint' },
  { address: 2004, label: 'Hot Water Setpoint' },
  { address: 2110, label: 'Outdoor Ambient' },
  { address: 2102, label: 'Outlet Water' },
  { address: 2103, label: 'Inlet Water' },
  { address: 2100, label: 'Water Tank' },
  { address: 2118, label: 'Compressor Freq' },
]

const SECONDARY_CONTROL_ADDRESSES = [2052, 2053, 2054, 2056, 2057]
const POWER_METRIC_ADDRESSES = [2120, 2121, 2122, 2123]
const TEMPERATURE_UNIT = '\u00B0C'

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
    const parsed = Number(text)
    return Number.isFinite(parsed) ? parsed : template
  }
  return draft ?? template
}

function formatNumber(value) {
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return '--'
  if (Number.isInteger(numeric)) return String(numeric)
  return numeric.toFixed(Math.abs(numeric) >= 100 ? 0 : 1).replace(/\.0$/, '')
}

function getRegister(device, address) {
  return device.registers.find((register) => register.address === address) ?? null
}

function getAccessLabel(register) {
  return register.access === 'writable' ? 'Writable' : 'Read Only'
}

function getPowerLabel(register) {
  if (!register) return '--'
  return Number(register.value) === 1 ? 'ON' : 'OFF'
}

function getModeLabel(register) {
  if (!register) return '--'
  const numeric = Number(register.value)
  const label = MODE_LABELS[numeric]
  return label ? `${label} (${numeric})` : formatNumber(register.value)
}

function formatRegisterValue(register, includeUnit = true) {
  if (!register) return '--'
  if (register.address === 2000) return getPowerLabel(register)
  if (register.address === 2001) return getModeLabel(register)
  const value = formatNumber(register.value)
  if (!includeUnit || !register.unit || value === '--') return value
  return `${value} ${register.unit}`
}

function getRegisterNote(register) {
  if (!register) return ''
  return register.bitfield_text || register.note || ''
}

function isTemperatureRegister(register) {
  return register?.unit === TEMPERATURE_UNIT
}

function buildSummaryItems(device) {
  return PRIMARY_SUMMARY
    .map(({ address, label }) => {
      const register = getRegister(device, address)
      if (!register) return null
      return {
        address,
        label,
        value: formatRegisterValue(register),
        raw: register.raw,
        note: getRegisterNote(register),
        access: getAccessLabel(register),
      }
    })
    .filter(Boolean)
}

function buildSecondaryItems(device, addresses) {
  return addresses
    .map((address) => getRegister(device, address))
    .filter(Boolean)
}

export default function ArcticHpPage({ config, runtime, onConfigChange, onStartServer, onStopServer, onSetRegister, onResetDevice }) {
  const [portDraft, setPortDraft] = useState(config.arctic_hp.port)
  const [deviceDrafts, setDeviceDrafts] = useState(config.arctic_hp.devices)
  const [registerDrafts, setRegisterDrafts] = useState({})
  const [configError, setConfigError] = useState('')
  const [registerError, setRegisterError] = useState('')

  useEffect(() => {
    setPortDraft(config.arctic_hp.port)
    setDeviceDrafts(config.arctic_hp.devices)
    setConfigError('')
  }, [config])

  const updatePortDraft = (field, value) => {
    setConfigError('')
    setPortDraft((current) => ({ ...current, [field]: value }))
  }

  const updateDeviceDraft = (deviceId, field, value) => {
    setConfigError('')
    setDeviceDrafts((current) => current.map((device) => (
      device.device_id === deviceId ? { ...device, [field]: value } : device
    )))
  }

  const applyConfig = async () => {
    const nextConfig = {
      ...config,
      arctic_hp: {
        ...config.arctic_hp,
        port: coerceDraftValue(portDraft, config.arctic_hp.port),
        devices: deviceDrafts.map((device, index) => coerceDraftValue(device, config.arctic_hp.devices[index] ?? config.arctic_hp.devices[0])),
      },
    }
    try {
      await onConfigChange(nextConfig)
      setConfigError('')
    } catch (error) {
      setConfigError(error.message || 'Arctic config update failed')
    }
  }

  const applyRegister = async (deviceId, register) => {
    const key = `${deviceId}:${register.address}`
    const nextValue = registerDrafts[key] ?? register.value
    try {
      await onSetRegister(deviceId, register.address, Number(nextValue))
      setRegisterDrafts((current) => {
        const next = { ...current }
        delete next[key]
        return next
      })
      setRegisterError('')
    } catch (error) {
      setRegisterError(error.message || 'Register update failed')
    }
  }

  const server = runtime.arctic_hp.server

  return (
    <div className="page-grid">
      <Card
        title="Arctic HP Emulator"
        subtitle="Important values stay visible at the top. Manual edits stay limited to readable sensor and status registers."
        actions={(
          <div className="button-row">
            <button className="button-secondary" onClick={applyConfig}>Update Config</button>
            <button onClick={onStartServer}>Start</button>
            <button onClick={onStopServer}>Stop</button>
          </div>
        )}
      >
        {configError ? <div className="error-text config-error">{configError}</div> : null}
        {registerError ? <div className="error-text config-error">{registerError}</div> : null}

        <div className="arctic-status-grid">
          <article className={`arctic-status-card ${server.running ? 'is-live' : 'is-idle'}`}>
            <span className="arctic-status-label">Server</span>
            <strong>{server.running ? 'Running' : 'Stopped'}</strong>
            <p>{server.message || 'No status message'}</p>
          </article>
          <article className={`arctic-status-card ${server.transport_available ? 'is-live' : 'is-warning'}`}>
            <span className="arctic-status-label">Transport</span>
            <strong>{server.transport_available ? 'Available' : 'Offline Edit Mode'}</strong>
            <p>{server.port || portDraft.serial_file}</p>
          </article>
          <article className="arctic-status-card">
            <span className="arctic-status-label">Baud Rate</span>
            <strong>{server.baudrate ?? portDraft.baudrate}</strong>
            <p>{portDraft.bytesize} / {portDraft.parity} / {portDraft.stopbits}</p>
          </article>
          <article className="arctic-status-card">
            <span className="arctic-status-label">Configured Timeout</span>
            <strong>{formatNumber(portDraft.timeout)}</strong>
            <p>seconds</p>
          </article>
        </div>

        <details className="arctic-advanced-block">
          <summary>Serial Port And Transport Settings</summary>
          <div className="form-grid compact arctic-form-block">
            <label>
              <span>Serial Port</span>
              <input value={portDraft.serial_file ?? ''} onChange={(event) => updatePortDraft('serial_file', event.target.value)} />
            </label>
            <label>
              <span>Baud Rate</span>
              <input value={portDraft.baudrate ?? ''} onChange={(event) => updatePortDraft('baudrate', event.target.value)} />
            </label>
            <label>
              <span>Bytesize</span>
              <input value={portDraft.bytesize ?? ''} onChange={(event) => updatePortDraft('bytesize', event.target.value)} />
            </label>
            <label>
              <span>Parity</span>
              <select value={portDraft.parity ?? 'E'} onChange={(event) => updatePortDraft('parity', event.target.value)}>
                <option value="N">N</option>
                <option value="E">E</option>
                <option value="O">O</option>
              </select>
            </label>
            <label>
              <span>Stopbits</span>
              <input value={portDraft.stopbits ?? ''} onChange={(event) => updatePortDraft('stopbits', event.target.value)} />
            </label>
            <label>
              <span>Timeout (s)</span>
              <input value={portDraft.timeout ?? ''} onChange={(event) => updatePortDraft('timeout', event.target.value)} />
            </label>
          </div>
        </details>
      </Card>

      {runtime.arctic_hp.devices.map((device) => {
        const draftDevice = deviceDrafts.find((item) => item.device_id === device.device_id) ?? device
        const summaryItems = buildSummaryItems(device)
        const controllerRegisters = buildSecondaryItems(device, SECONDARY_CONTROL_ADDRESSES)
        const powerRegisters = buildSecondaryItems(device, POWER_METRIC_ADDRESSES)
        const manualRegisters = device.registers.filter((register) => register.manual_editable)
        const writableCount = device.registers.filter((register) => register.access === 'writable').length

        return (
          <Card
            key={device.device_id}
            title={device.name}
            subtitle={`Unit ID ${device.unit_id} | ${device.display_side} side | ${writableCount} controller-writable registers`}
            actions={<button onClick={() => onResetDevice(device.device_id)}>Reset Defaults</button>}
          >
            <div className="arctic-device-head">
              <div className="arctic-device-badges">
                <span className="arctic-badge">{draftDevice.name}</span>
                <span className="arctic-badge arctic-badge-muted">Unit {draftDevice.unit_id}</span>
                <span className="arctic-badge arctic-badge-muted">{draftDevice.display_side}</span>
              </div>
              <p className="arctic-device-copy">
                Writable values below are display-only reflections of controller-facing registers. Manual apply is only available on readable sensor and status values.
              </p>
            </div>

            <div className="arctic-summary-grid">
              {summaryItems.map((item) => (
                <article key={item.address} className="arctic-summary-card">
                  <span className="arctic-summary-kicker">{item.label}</span>
                  <strong>{item.value}</strong>
                  <div className="arctic-summary-meta">
                    <span>Addr {item.address}</span>
                    <span>{item.access}</span>
                    <span>RAW {item.raw}</span>
                  </div>
                  {item.note ? <p>{item.note}</p> : null}
                </article>
              ))}
            </div>

            {controllerRegisters.length ? (
              <div className="arctic-section-block">
                <div className="arctic-section-heading">
                  <h4>Controller-Facing Settings</h4>
                  <span>Readback only</span>
                </div>
                <div className="arctic-chip-grid">
                  {controllerRegisters.map((register) => (
                    <article key={register.address} className="arctic-chip-card">
                      <span>{register.name}</span>
                      <strong>{formatRegisterValue(register)}</strong>
                      <small>Addr {register.address} | RAW {register.raw}</small>
                    </article>
                  ))}
                </div>
              </div>
            ) : null}

            {powerRegisters.length ? (
              <div className="arctic-section-block">
                <div className="arctic-section-heading">
                  <h4>Electrical Snapshot</h4>
                  <span>Live reflected values</span>
                </div>
                <div className="arctic-chip-grid">
                  {powerRegisters.map((register) => (
                    <article key={register.address} className="arctic-chip-card arctic-chip-card-accent">
                      <span>{register.name}</span>
                      <strong>{formatRegisterValue(register)}</strong>
                      <small>Addr {register.address} | RAW {register.raw}</small>
                    </article>
                  ))}
                </div>
              </div>
            ) : null}

            <div className="arctic-section-block">
              <div className="arctic-section-heading">
                <h4>Manual Sensor And Status Overrides</h4>
                <span>{manualRegisters.length} editable registers</span>
              </div>
              <div className="arctic-register-grid">
                {manualRegisters.map((register) => {
                  const key = `${device.device_id}:${register.address}`
                  return (
                    <article key={register.address} className="arctic-register-card">
                      <div className="arctic-register-topline">
                        <div>
                          <span className="arctic-register-address">Addr {register.address}</span>
                          <h5>{register.name}</h5>
                        </div>
                        <span className="arctic-badge arctic-badge-editable">Manual</span>
                      </div>
                      <div className="arctic-register-readback">
                        <span>Current: {formatRegisterValue(register)}</span>
                        <span>RAW: {register.raw}</span>
                      </div>
                      <label className="arctic-register-input">
                        <span>Override value</span>
                        <input
                          type="number"
                          step={isTemperatureRegister(register) ? '0.1' : '1'}
                          value={registerDrafts[key] ?? register.value}
                          onChange={(event) => {
                            setRegisterDrafts((current) => ({ ...current, [key]: event.target.value }))
                          }}
                        />
                      </label>
                      {getRegisterNote(register) ? <p>{getRegisterNote(register)}</p> : null}
                      <button className="button-secondary" onClick={() => applyRegister(device.device_id, register)}>Apply Override</button>
                    </article>
                  )
                })}
              </div>
            </div>

            <details className="arctic-advanced-block">
              <summary>Advanced Device Config And Full Register Table</summary>
              <div className="form-grid compact arctic-form-block">
                <label>
                  <span>Device Name</span>
                  <input value={draftDevice.name} onChange={(event) => updateDeviceDraft(device.device_id, 'name', event.target.value)} />
                </label>
                <label>
                  <span>Unit ID</span>
                  <input value={draftDevice.unit_id} onChange={(event) => updateDeviceDraft(device.device_id, 'unit_id', event.target.value)} />
                </label>
                <label>
                  <span>Display Side</span>
                  <select value={draftDevice.display_side} onChange={(event) => updateDeviceDraft(device.device_id, 'display_side', event.target.value)}>
                    <option value="left">left</option>
                    <option value="right">right</option>
                  </select>
                </label>
              </div>

              <div className="table-wrap tall">
                <table>
                  <thead>
                    <tr>
                      <th>Addr</th>
                      <th>Name</th>
                      <th>Access</th>
                      <th>Value</th>
                      <th>Raw</th>
                      <th>Unit</th>
                      <th>Note</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {device.registers.map((register) => {
                      const key = `${device.device_id}:${register.address}`
                      return (
                        <tr key={register.address}>
                          <td>{register.address}</td>
                          <td>{register.name}</td>
                          <td>{getAccessLabel(register)}</td>
                          <td>
                            {register.manual_editable ? (
                              <input
                                type="number"
                                step={isTemperatureRegister(register) ? '0.1' : '1'}
                                value={registerDrafts[key] ?? register.value}
                                onChange={(event) => {
                                  setRegisterDrafts((current) => ({ ...current, [key]: event.target.value }))
                                }}
                              />
                            ) : (
                              <span>{formatRegisterValue(register, false)}</span>
                            )}
                          </td>
                          <td>{register.raw}</td>
                          <td>{register.unit}</td>
                          <td title={getRegisterNote(register)}>{register.note || (register.bitfield_text ? 'bitfield' : '')}</td>
                          <td>
                            {register.manual_editable ? (
                              <button className="button-secondary" onClick={() => applyRegister(device.device_id, register)}>Apply</button>
                            ) : (
                              <span className="arctic-table-hint">Reflected only</span>
                            )}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </details>
          </Card>
        )
      })}
    </div>
  )
}
