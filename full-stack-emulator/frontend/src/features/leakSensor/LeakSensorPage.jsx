import { useEffect, useMemo, useState } from 'react'

import Card from '../../components/common/Card'
import { createDefaultLeakSensor } from '../config/configDefaults'

function buildDraftMap(sensors) {
  return Object.fromEntries(
    sensors.map((sensor) => [
      sensor.id,
      {
        name: sensor.name,
        output_channel: {
          stack: sensor.output_channel?.stack ?? 3,
          channel: sensor.output_channel?.channel ?? 1,
        },
        voltage: sensor.voltage ?? 0,
      },
    ]),
  )
}

function coerceDraftSensor(draft, template) {
  const stack = Number(draft.output_channel?.stack ?? template.output_channel.stack)
  const channel = Number(draft.output_channel?.channel ?? template.output_channel.channel)
  const voltage = Number(draft.voltage ?? template.voltage ?? 0)

  return {
    ...template,
    name: String(draft.name ?? template.name).trim() || template.name,
    output_channel: {
      stack: Number.isInteger(stack) && stack >= 0 ? stack : template.output_channel.stack,
      channel: Number.isInteger(channel) && channel >= 1 ? channel : template.output_channel.channel,
    },
    voltage: Number.isFinite(voltage) ? Math.max(0, Math.min(10, voltage)) : template.voltage ?? 0,
  }
}

function LeakSensorBulkConfigDialog({ sensors, drafts, config, onConfigChange, onClose, open }) {
  const [draftRows, setDraftRows] = useState([])
  const [saveError, setSaveError] = useState('')

  useEffect(() => {
    if (!open || !Array.isArray(sensors)) return
    setDraftRows(
      sensors.map((sensor) => ({
        id: sensor.id,
        ...(drafts[sensor.id] ?? {
          name: sensor.name,
          output_channel: {
            stack: sensor.output_channel?.stack ?? 3,
            channel: sensor.output_channel?.channel ?? 1,
          },
          voltage: sensor.voltage ?? 0,
        }),
      })),
    )
    setSaveError('')
  }, [open, sensors, drafts])

  if (!open || !Array.isArray(sensors) || sensors.length === 0) return null

  const updateRow = (sensorId, updater) => {
    setSaveError('')
    setDraftRows((current) => current.map((row) => (row.id === sensorId ? updater(row) : row)))
  }

  const applyBulkUpdate = async () => {
    try {
      const sensorMap = new Map(sensors.map((sensor) => [sensor.id, sensor]))
      const nextSensors = draftRows.map((row) => coerceDraftSensor(row, sensorMap.get(row.id)))
      await onConfigChange({
        ...config,
        leak_sensors: {
          ...config.leak_sensors,
          sensors: nextSensors,
        },
      })
      setSaveError('')
      onClose()
    } catch (error) {
      setSaveError(error.message || 'Leak sensor bulk config update failed')
    }
  }

  return (
    <div className="modal-backdrop">
      <div className="modal-card modal-card-wide">
        <div className="inline-row spread">
          <div>
            <h3>Leak Sensor Bulk Config</h3>
            <p>Bulk-edit the same fields shown on each leak sensor card: name, stack, channel, and voltage.</p>
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
                <th>ID</th>
                <th>Name</th>
                <th>Stack</th>
                <th>Channel</th>
                <th>Voltage</th>
              </tr>
            </thead>
            <tbody>
              {draftRows.map((row) => (
                <tr key={row.id}>
                  <td>{row.id}</td>
                  <td>
                    <input value={row.name ?? ''} onChange={(event) => updateRow(row.id, (current) => ({ ...current, name: event.target.value }))} />
                  </td>
                  <td>
                    <input
                      type="number"
                      min="0"
                      value={row.output_channel?.stack ?? 3}
                      onChange={(event) => updateRow(row.id, (current) => ({
                        ...current,
                        output_channel: { ...(current.output_channel ?? {}), stack: event.target.value },
                      }))}
                    />
                  </td>
                  <td>
                    <input
                      type="number"
                      min="1"
                      max="16"
                      value={row.output_channel?.channel ?? 1}
                      onChange={(event) => updateRow(row.id, (current) => ({
                        ...current,
                        output_channel: { ...(current.output_channel ?? {}), channel: event.target.value },
                      }))}
                    />
                  </td>
                  <td>
                    <input type="number" min="0" max="10" step="0.1" value={row.voltage ?? 0} onChange={(event) => updateRow(row.id, (current) => ({ ...current, voltage: event.target.value }))} />
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

export default function LeakSensorPage({ config, runtime, onConfigChange, onSetVoltage }) {
  const [drafts, setDrafts] = useState(() => buildDraftMap(config.leak_sensors?.sensors ?? []))
  const [pageError, setPageError] = useState('')
  const [bulkEditing, setBulkEditing] = useState(false)
  const [targetCount, setTargetCount] = useState(String(config.leak_sensors?.sensors?.length ?? 0))

  const sensorConfigs = config.leak_sensors?.sensors ?? []
  const runtimeSensors = runtime.leak_sensors?.sensors ?? []
  const runtimeById = useMemo(
    () => Object.fromEntries(runtimeSensors.map((sensor) => [sensor.id, sensor])),
    [runtimeSensors],
  )

  useEffect(() => {
    setDrafts(buildDraftMap(sensorConfigs))
    setTargetCount(String(sensorConfigs.length))
  }, [sensorConfigs])

  const updateDraft = (sensorId, updater) => {
    setDrafts((current) => ({
      ...current,
      [sensorId]: updater(current[sensorId] ?? buildDraftMap(sensorConfigs)[sensorId]),
    }))
    setPageError('')
  }

  const buildNextConfig = (nextSensors) => ({
    ...config,
    leak_sensors: {
      ...config.leak_sensors,
      sensors: nextSensors,
    },
  })

  const saveSensorConfig = async (sensorId) => {
    const sensorIndex = sensorConfigs.findIndex((sensor) => sensor.id === sensorId)
    if (sensorIndex < 0) return null

    const nextSensor = coerceDraftSensor(drafts[sensorId] ?? sensorConfigs[sensorIndex], sensorConfigs[sensorIndex])
    await onConfigChange(buildNextConfig(sensorConfigs.map((sensor, index) => (index === sensorIndex ? nextSensor : sensor))))
    setPageError('')
    return nextSensor
  }

  const applySensorVoltage = async (sensorId) => {
    try {
      const nextSensor = await saveSensorConfig(sensorId)
      if (!nextSensor) return
      await onSetVoltage(sensorId, nextSensor.voltage)
      setPageError('')
    } catch (error) {
      setPageError(error.message || 'Leak sensor voltage update failed')
    }
  }

  const resizeSensors = async () => {
    const requestedCount = Number(targetCount)
    if (!Number.isInteger(requestedCount) || requestedCount < 0) {
      setPageError('Leak sensor count must be an integer greater than or equal to 0.')
      return
    }

    let nextSensors = [...sensorConfigs]
    if (requestedCount < nextSensors.length) {
      nextSensors = nextSensors.slice(0, requestedCount)
    } else {
      while (nextSensors.length < requestedCount) {
        nextSensors.push(createDefaultLeakSensor(nextSensors))
      }
    }

    try {
      await onConfigChange(buildNextConfig(nextSensors))
      setPageError('')
    } catch (error) {
      setPageError(error.message || 'Leak sensor count update failed')
    }
  }

  const addSensor = async () => {
    const nextSensors = [...sensorConfigs, createDefaultLeakSensor(sensorConfigs)]
    try {
      await onConfigChange(buildNextConfig(nextSensors))
      setPageError('')
    } catch (error) {
      setPageError(error.message || 'Leak sensor add failed')
    }
  }

  const deleteSensor = async (sensorId) => {
    try {
      await onConfigChange(buildNextConfig(sensorConfigs.filter((sensor) => sensor.id !== sensorId)))
      setPageError('')
    } catch (error) {
      setPageError(error.message || 'Leak sensor delete failed')
    }
  }

  return (
    <div className="page-grid">
      {pageError ? <div className="error-text">{pageError}</div> : null}
      <Card
        title="Leak Sensors"
        subtitle="Leak sensors drive user-configured 0-10V analog outputs. Set Voltage saves the card fields, then writes the configured voltage to the assigned output channel."
        collapsible
        defaultExpanded
        actions={(
          <div className="inline-row wrap">
            <input className="count-input" type="number" min="0" value={targetCount} onChange={(event) => setTargetCount(event.target.value)} />
            <button className="button-secondary" onClick={resizeSensors}>Set Count</button>
            <button className="button-secondary" onClick={() => setBulkEditing(true)}>Bulk Config</button>
          </div>
        )}
      >
        <div className="leak-sensor-grid">
          {sensorConfigs.map((sensor) => {
            const runtimeSensor = runtimeById[sensor.id] ?? {
              id: sensor.id,
              name: sensor.name,
              stack: sensor.output_channel.stack,
              channel: sensor.output_channel.channel,
              voltage: sensor.voltage ?? 0,
              available: false,
              error: 'Awaiting runtime sync',
            }
            const draft = drafts[sensor.id] ?? {
              name: sensor.name,
              output_channel: { ...sensor.output_channel },
              voltage: sensor.voltage ?? 0,
            }

            return (
              <div key={sensor.id} className={runtimeSensor.available ? 'sensor-card leak-sensor-card' : 'sensor-card leak-sensor-card missing'}>
                <div className="inline-row spread">
                  <div>
                    <strong>{draft.name ?? sensor.name}</strong>
                    <div className="valve-meta">{sensor.id}</div>
                  </div>
                  <span className={runtimeSensor.available ? 'status-chip active' : 'status-chip'}>{runtimeSensor.available ? 'Live' : 'Offline'}</span>
                </div>

                <div className="valve-state-banner leak-sensor-banner">
                  <span className="valve-state-label">Analog Output</span>
                  <strong className="valve-state-value">{Number(runtimeSensor.voltage ?? draft.voltage ?? 0).toFixed(2)} V</strong>
                  <span className="valve-state-subtitle">Stack {runtimeSensor.stack}, Channel {runtimeSensor.channel}</span>
                </div>

                <div className="leak-sensor-form">
                  <label>
                    <span>Name</span>
                    <input value={draft.name ?? ''} onChange={(event) => updateDraft(sensor.id, (current) => ({ ...current, name: event.target.value }))} />
                  </label>
                  <label>
                    <span>Stack</span>
                    <input
                      type="number"
                      min="0"
                      value={draft.output_channel?.stack ?? 3}
                      onChange={(event) => updateDraft(sensor.id, (current) => ({
                        ...current,
                        output_channel: { ...(current.output_channel ?? {}), stack: event.target.value },
                      }))}
                    />
                  </label>
                  <label>
                    <span>Channel</span>
                    <input
                      type="number"
                      min="1"
                      max="16"
                      value={draft.output_channel?.channel ?? 1}
                      onChange={(event) => updateDraft(sensor.id, (current) => ({
                        ...current,
                        output_channel: { ...(current.output_channel ?? {}), channel: event.target.value },
                      }))}
                    />
                  </label>
                  <label>
                    <span>Voltage</span>
                    <input type="number" min="0" max="10" step="0.1" value={draft.voltage ?? 0} onChange={(event) => updateDraft(sensor.id, (current) => ({ ...current, voltage: event.target.value }))} />
                  </label>
                </div>

                <div className="inline-row wrap valve-actions">
                  <button className="button-secondary" onClick={() => saveSensorConfig(sensor.id).catch((error) => setPageError(error.message || 'Leak sensor config update failed'))}>Update</button>
                  <button className="button-secondary" onClick={() => applySensorVoltage(sensor.id)}>Set Voltage</button>
                  <button className="button-danger" onClick={() => deleteSensor(sensor.id)}>Delete</button>
                </div>

                <div className="error-text">{runtimeSensor.error || 'Output board available'}</div>
              </div>
            )
          })}

          <button className="add-card" onClick={addSensor}>
            <span className="add-card-mark">+</span>
            <strong>Add Leak Sensor</strong>
            <span>Creates one more leak sensor card and keeps the count aligned with the configured outputs.</span>
          </button>
        </div>
      </Card>

      <LeakSensorBulkConfigDialog
        sensors={bulkEditing ? sensorConfigs : null}
        drafts={drafts}
        config={config}
        onConfigChange={onConfigChange}
        open={bulkEditing}
        onClose={() => setBulkEditing(false)}
      />
    </div>
  )
}
