import { useEffect, useState } from 'react'

import Card from '../../components/common/Card'
import { createDefaultRtdSensor } from '../config/configDefaults'
import { updateConfigAtPath } from '../config/updateConfigAtPath'

function normalizeBitWidth(value) {
  return Number(value) === 8 ? 8 : 5
}

function formatNumber(value, digits = 3) {
  const numeric = Number(value)
  return Number.isFinite(numeric) ? numeric.toFixed(digits) : 'n/a'
}

function deriveDefaultEquation(sensor) {
  const minRes = Number(sensor.min_res_ohms ?? 95)
  const maxRes = Number(sensor.max_res_ohms ?? 150)
  const minTemp = Number(sensor.temp_min_c ?? -10)
  const maxTemp = Number(sensor.temp_max_c ?? 80)
  const deltaRes = maxRes - minRes
  if (Math.abs(deltaRes) < 1e-9) {
    return { a: 0, b: minTemp }
  }
  const a = (maxTemp - minTemp) / deltaRes
  const b = minTemp - (a * minRes)
  return { a, b }
}

function resolveEquation(sensor) {
  if (
    sensor.use_custom_equation &&
    sensor.custom_equation_a !== null &&
    sensor.custom_equation_a !== '' &&
    sensor.custom_equation_b !== null &&
    sensor.custom_equation_b !== ''
  ) {
    return {
      a: Number(sensor.custom_equation_a),
      b: Number(sensor.custom_equation_b),
      mode: 'custom',
    }
  }
  const equation = deriveDefaultEquation(sensor)
  return { ...equation, mode: 'default' }
}

function activeMask(bitWidth) {
  return normalizeBitWidth(bitWidth) === 8 ? 0xFF : 0x1F
}

function buildBitsFromCode(code, bitWidth) {
  return Array.from({ length: normalizeBitWidth(bitWidth) }, (_, offset) => {
    const index = normalizeBitWidth(bitWidth) - 1 - offset
    return ((code >> index) & 1) ? '1' : '0'
  }).join('')
}

function bitsToCode(bits) {
  return (Array.isArray(bits) ? bits : []).reduce((code, bit, index) => (bit ? (code | (1 << index)) : code), 0)
}

function orderedBitIndexes(bitCount) {
  return Array.from({ length: bitCount }, (_, offset) => (bitCount - 1 - offset))
}

function codeToResistance(sensor, code) {
  const maxRes = Number(sensor.max_res_ohms ?? 150)
  const step = Number(sensor.res_step_ohms ?? 2)
  const clampedCode = Math.max(0, Math.min(activeMask(sensor.bit_width), Number(code) || 0))
  return maxRes - (clampedCode * step)
}

function clampResistanceToRange(sensor, resistance) {
  const minRes = Number(sensor.min_res_ohms ?? 95)
  const maxRes = Number(sensor.max_res_ohms ?? 150)
  return Math.max(minRes, Math.min(maxRes, Number(resistance)))
}

function findClosestCodeForResistance(sensor, resistance) {
  const targetResistance = clampResistanceToRange(sensor, resistance)
  const minRes = Number(sensor.min_res_ohms ?? 95)
  const maxRes = Number(sensor.max_res_ohms ?? 150)

  let bestCode = 0
  let bestResistance = codeToResistance(sensor, 0)
  let bestDistance = Math.abs(bestResistance - targetResistance)
  let bestInRange = bestResistance >= minRes && bestResistance <= maxRes

  for (let code = 1; code <= activeMask(sensor.bit_width); code += 1) {
    const candidateResistance = codeToResistance(sensor, code)
    const candidateDistance = Math.abs(candidateResistance - targetResistance)
    const candidateInRange = candidateResistance >= minRes && candidateResistance <= maxRes

    if (candidateDistance < bestDistance) {
      bestCode = code
      bestResistance = candidateResistance
      bestDistance = candidateDistance
      bestInRange = candidateInRange
      continue
    }

    if (Math.abs(candidateDistance - bestDistance) < 1e-9) {
      if (candidateInRange && !bestInRange) {
        bestCode = code
        bestResistance = candidateResistance
        bestInRange = true
        continue
      }
      if (candidateInRange === bestInRange && code < bestCode) {
        bestCode = code
        bestResistance = candidateResistance
      }
    }
  }

  return {
    code: bestCode,
    resistance: bestResistance,
    targetResistance,
  }
}

function estimateFromCode(sensor, code) {
  const equation = resolveEquation(sensor)
  const resistance = codeToResistance(sensor, code)
  const temperature = (equation.a * resistance) + equation.b
  return {
    code,
    resistance,
    temperature,
  }
}

function buildTemperatureOverridePreview(sensor) {
  if (sensor.output_temp_c === null || sensor.output_temp_c === undefined || sensor.output_temp_c === '') {
    return null
  }

  const targetTemp = Number(sensor.output_temp_c)
  if (!Number.isFinite(targetTemp)) {
    return null
  }

  const equation = resolveEquation(sensor)
  const targetResistance = Math.abs(equation.a) < 1e-9
    ? Number(sensor.max_res_ohms ?? 150)
    : ((targetTemp - equation.b) / equation.a)
  const closest = findClosestCodeForResistance(sensor, targetResistance)

  return {
    temperature: targetTemp,
    resistance: closest.resistance,
    targetResistance: closest.targetResistance,
    code: closest.code,
    bits: buildBitsFromCode(closest.code, sensor.bit_width),
  }
}

function formatEquation(sensor) {
  const defaultEquation = deriveDefaultEquation(sensor)
  const activeEquation = resolveEquation(sensor)
  return {
    defaultText: `T = ${formatNumber(defaultEquation.a, 4)} * R + ${formatNumber(defaultEquation.b, 4)}`,
    activeText: `T = ${formatNumber(activeEquation.a, 4)} * R + ${formatNumber(activeEquation.b, 4)}`,
    mode: activeEquation.mode,
  }
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
    const parsed = Number(text)
    return Number.isFinite(parsed) ? parsed : template
  }
  if (template === null && typeof draft === 'string') {
    const text = draft.trim()
    if (!text) return null
    const parsed = Number(text)
    return Number.isFinite(parsed) ? parsed : null
  }
  if (typeof template === 'boolean') {
    return Boolean(draft)
  }
  return draft ?? template
}

function nextBoardCountForSensors(sensors) {
  return Math.max(
    1,
    ...sensors.flatMap((sensor) => [Number(sensor.board_index ?? -1) + 1, Number(sensor.position ?? 0)]),
  )
}

function RtdSensorConfigDialog({ sensor, sensorIndex, config, onConfigChange, onClose }) {
  const [draftSensor, setDraftSensor] = useState(sensor)
  const [saveError, setSaveError] = useState('')

  useEffect(() => {
    setDraftSensor(sensor)
    setSaveError('')
  }, [sensor])

  if (!sensor || !draftSensor) return null

  const equationInfo = formatEquation(draftSensor)
  const overridePreview = buildTemperatureOverridePreview(draftSensor)

  const updateSensor = (path, value) => {
    setSaveError('')
    setDraftSensor((current) => updateConfigAtPath(current, path, value))
  }

  const applySensorUpdate = async () => {
    const nextSensor = coerceDraftValue(draftSensor, sensor)
    const nextSensors = config.rtd.sensors.map((item, index) => (index === sensorIndex ? nextSensor : item))
    const nextConfig = {
      ...config,
      rtd: {
        ...config.rtd,
        board_count: Math.max(config.rtd.board_count, nextBoardCountForSensors(nextSensors)),
        sensors: nextSensors,
      },
    }

    try {
      await onConfigChange(nextConfig)
      setSaveError('')
      onClose()
    } catch (error) {
      setSaveError(error.message || 'RTD sensor config update failed')
    }
  }

  return (
    <div className="modal-backdrop">
      <div className="modal-card">
        <div className="inline-row spread">
          <div>
            <h3>{draftSensor.sensor_name} RTD Board Config</h3>
            <p>Board order, bit width, calibration range, equation, and optional temperature override.</p>
          </div>
          <div className="inline-row wrap">
            <button className="button-secondary" onClick={applySensorUpdate}>Update</button>
            <button onClick={onClose}>Close</button>
          </div>
        </div>
        {saveError ? <div className="error-text config-error">{saveError}</div> : null}

        <div className="form-grid">
          <label>
            <span>Sensor Name</span>
            <input value={draftSensor.sensor_name} onChange={(event) => updateSensor(['sensor_name'], event.target.value)} />
          </label>
          <label>
            <span>Board Index</span>
            <input type="number" min="0" value={draftSensor.board_index} onChange={(event) => updateSensor(['board_index'], event.target.value)} />
          </label>
          <label>
            <span>Frame Position</span>
            <input type="number" min="1" value={draftSensor.position ?? 1} onChange={(event) => updateSensor(['position'], event.target.value)} />
          </label>
          <label>
            <span>Active Bits</span>
            <select value={draftSensor.bit_width ?? 5} onChange={(event) => updateSensor(['bit_width'], Number(event.target.value))}>
              <option value="5">5 bits</option>
              <option value="8">8 bits</option>
            </select>
          </label>
          <label>
            <span>Logical Stack</span>
            <input type="number" min="0" value={draftSensor.logical_stack ?? 0} onChange={(event) => updateSensor(['logical_stack'], event.target.value)} />
          </label>
          <label>
            <span>Logical Channel</span>
            <input type="number" min="1" value={draftSensor.logical_channel ?? 1} onChange={(event) => updateSensor(['logical_channel'], event.target.value)} />
          </label>
        </div>

        <div className="rtd-config-section">
          <div className="rtd-section-heading">Calibration Range</div>
          <div className="form-grid">
            <label>
              <span>Minimum Resistance (Ω)</span>
              <input type="number" step="0.1" value={draftSensor.min_res_ohms ?? 95} onChange={(event) => updateSensor(['min_res_ohms'], event.target.value)} />
            </label>
            <label>
              <span>Maximum Resistance (Ω)</span>
              <input type="number" step="0.1" value={draftSensor.max_res_ohms ?? 150} onChange={(event) => updateSensor(['max_res_ohms'], event.target.value)} />
            </label>
            <label>
              <span>Minimum Temp (°C)</span>
              <input type="number" step="0.1" value={draftSensor.temp_min_c ?? -10} onChange={(event) => updateSensor(['temp_min_c'], event.target.value)} />
            </label>
            <label>
              <span>Maximum Temp (°C)</span>
              <input type="number" step="0.1" value={draftSensor.temp_max_c ?? 80} onChange={(event) => updateSensor(['temp_max_c'], event.target.value)} />
            </label>
            <label>
              <span>Resistance Step (Ω)</span>
              <input type="number" min="0.001" step="0.1" value={draftSensor.res_step_ohms ?? 2} onChange={(event) => updateSensor(['res_step_ohms'], event.target.value)} />
            </label>
          </div>
        </div>

        <div className="rtd-config-section">
          <div className="rtd-section-heading">Equation</div>
          <div className="rtd-equation-box">
            <strong>Default Equation</strong>
            <span>{equationInfo.defaultText}</span>
            <span className="valve-meta">
              T({formatNumber(draftSensor.min_res_ohms ?? 95, 1)} Ω) = {formatNumber(draftSensor.temp_min_c ?? -10, 2)} °C,
              {' '}
              T({formatNumber(draftSensor.max_res_ohms ?? 150, 1)} Ω) = {formatNumber(draftSensor.temp_max_c ?? 80, 2)} °C
            </span>
          </div>
          <div className="form-grid">
            <label>
              <span>Use Custom Equation</span>
              <input type="checkbox" checked={!!draftSensor.use_custom_equation} onChange={(event) => updateSensor(['use_custom_equation'], event.target.checked)} />
            </label>
            <label>
              <span>Custom A</span>
              <input value={draftSensor.custom_equation_a ?? ''} onChange={(event) => updateSensor(['custom_equation_a'], event.target.value)} disabled={!draftSensor.use_custom_equation} />
            </label>
            <label>
              <span>Custom B</span>
              <input value={draftSensor.custom_equation_b ?? ''} onChange={(event) => updateSensor(['custom_equation_b'], event.target.value)} disabled={!draftSensor.use_custom_equation} />
            </label>
          </div>
          <div className="rtd-equation-box subtle">
            <strong>Active Equation</strong>
            <span>{equationInfo.activeText}</span>
            <span className="valve-meta">{equationInfo.mode === 'custom' ? 'Custom override is active.' : 'Using the default equation derived from the configured ranges.'}</span>
          </div>
        </div>

        <div className="rtd-config-section">
          <div className="rtd-section-heading">Temperature Override</div>
          <div className="form-grid">
            <label>
              <span>Output Temp Override (°C)</span>
              <input value={draftSensor.output_temp_c ?? ''} onChange={(event) => updateSensor(['output_temp_c'], event.target.value)} />
            </label>
            <div className="inline-row">
              <button className="button-secondary" onClick={() => updateSensor(['output_temp_c'], null)}>Clear Override</button>
            </div>
          </div>
          <div className="rtd-equation-box subtle">
            <strong>Override Preview</strong>
            {overridePreview ? (
              <>
                <span>{formatNumber(overridePreview.temperature, 2)} °C {'->'} {formatNumber(overridePreview.resistance, 3)} Ω</span>
                <span>Closest code {overridePreview.code} {'->'} bits {overridePreview.bits}</span>
                <span className="valve-meta">{normalizeBitWidth(draftSensor.bit_width) === 5 ? '5 active bits are used. The upper 3 shift-register outputs remain padding bits.' : 'All 8 bits are active for this board.'}</span>
              </>
            ) : (
              <span>No temperature override configured.</span>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

function RtdBulkConfigDialog({ sensors, config, onConfigChange, onClose, open }) {
  const [draftSensors, setDraftSensors] = useState(sensors)
  const [saveError, setSaveError] = useState('')
  const activeSensors = Array.isArray(draftSensors) ? draftSensors : sensors

  useEffect(() => {
    if (!open || !Array.isArray(sensors)) {
      return
    }
    setDraftSensors(sensors)
    setSaveError('')
  }, [open, sensors])

  if (!Array.isArray(sensors) || sensors.length === 0 || !Array.isArray(activeSensors)) return null

  const updateSensor = (index, path, value) => {
    setSaveError('')
    setDraftSensors((current) => current.map((sensor, sensorIndex) => (
      sensorIndex === index ? updateConfigAtPath(sensor, path, value) : sensor
    )))
  }

  const applyBulkUpdate = async () => {
    const nextSensors = activeSensors.map((sensor, index) => coerceDraftValue(sensor, sensors[index]))
    try {
      await onConfigChange({
        ...config,
        rtd: {
          ...config.rtd,
          board_count: Math.max(config.rtd.board_count, nextBoardCountForSensors(nextSensors)),
          sensors: nextSensors,
        },
      })
      setSaveError('')
      onClose()
    } catch (error) {
      setSaveError(error.message || 'RTD bulk config update failed')
    }
  }

  return (
    <div className="modal-backdrop">
      <div className="modal-card modal-card-wide">
        <div className="inline-row spread">
          <div>
            <h3>RTD Bulk Config</h3>
            <p>Bulk-edit RTD board mappings, calibration ranges, equation overrides, and temperature overrides.</p>
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
                <th>Name</th>
                <th>Board</th>
                <th>Position</th>
                <th>Bits</th>
                <th>Logical</th>
                <th>Calibration</th>
                <th>Equation</th>
                <th>Override</th>
              </tr>
            </thead>
            <tbody>
              {activeSensors.map((sensor, index) => (
                <tr key={`${sensor.sensor_name}-${index}`}>
                  <td>
                    <input value={sensor.sensor_name} onChange={(event) => updateSensor(index, ['sensor_name'], event.target.value)} />
                  </td>
                  <td>
                    <input value={sensor.board_index} onChange={(event) => updateSensor(index, ['board_index'], event.target.value)} />
                  </td>
                  <td>
                    <input value={sensor.position ?? 1} onChange={(event) => updateSensor(index, ['position'], event.target.value)} />
                  </td>
                  <td>
                    <select value={sensor.bit_width ?? 5} onChange={(event) => updateSensor(index, ['bit_width'], Number(event.target.value))}>
                      <option value="5">5</option>
                      <option value="8">8</option>
                    </select>
                  </td>
                  <td>
                    <div className="table-cell-grid">
                      <label>
                        <span>Stack</span>
                        <input value={sensor.logical_stack ?? 0} onChange={(event) => updateSensor(index, ['logical_stack'], event.target.value)} />
                      </label>
                      <label>
                        <span>Channel</span>
                        <input value={sensor.logical_channel ?? 1} onChange={(event) => updateSensor(index, ['logical_channel'], event.target.value)} />
                      </label>
                    </div>
                  </td>
                  <td>
                    <div className="table-cell-grid">
                      <label>
                        <span>Min Res</span>
                        <input value={sensor.min_res_ohms ?? 95} onChange={(event) => updateSensor(index, ['min_res_ohms'], event.target.value)} />
                      </label>
                      <label>
                        <span>Max Res</span>
                        <input value={sensor.max_res_ohms ?? 150} onChange={(event) => updateSensor(index, ['max_res_ohms'], event.target.value)} />
                      </label>
                      <label>
                        <span>Min Temp</span>
                        <input value={sensor.temp_min_c ?? -10} onChange={(event) => updateSensor(index, ['temp_min_c'], event.target.value)} />
                      </label>
                      <label>
                        <span>Max Temp</span>
                        <input value={sensor.temp_max_c ?? 80} onChange={(event) => updateSensor(index, ['temp_max_c'], event.target.value)} />
                      </label>
                      <label>
                        <span>Step</span>
                        <input value={sensor.res_step_ohms ?? 2} onChange={(event) => updateSensor(index, ['res_step_ohms'], event.target.value)} />
                      </label>
                    </div>
                  </td>
                  <td>
                    <div className="table-cell-grid">
                      <label>
                        <span>Use Custom</span>
                        <input type="checkbox" checked={!!sensor.use_custom_equation} onChange={(event) => updateSensor(index, ['use_custom_equation'], event.target.checked)} />
                      </label>
                      <label>
                        <span>A</span>
                        <input value={sensor.custom_equation_a ?? ''} onChange={(event) => updateSensor(index, ['custom_equation_a'], event.target.value)} />
                      </label>
                      <label>
                        <span>B</span>
                        <input value={sensor.custom_equation_b ?? ''} onChange={(event) => updateSensor(index, ['custom_equation_b'], event.target.value)} />
                      </label>
                    </div>
                  </td>
                  <td>
                    <div className="table-cell-grid">
                      <label>
                        <span>Output Temp °C</span>
                        <input value={sensor.output_temp_c ?? ''} onChange={(event) => updateSensor(index, ['output_temp_c'], event.target.value)} />
                      </label>
                      <button className="button-secondary" onClick={() => updateSensor(index, ['output_temp_c'], null)}>Clear Override</button>
                    </div>
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

export default function RtdPage({ runtime, config, onConfigChange, onSetBoardBits }) {
  const [pageError, setPageError] = useState('')
  const [editingSensorIndex, setEditingSensorIndex] = useState(null)
  const [bulkEditing, setBulkEditing] = useState(false)
  const [targetCount, setTargetCount] = useState(String(config.rtd.sensors.length))

  useEffect(() => {
    setTargetCount(String(config.rtd.sensors.length))
  }, [config.rtd.sensors.length])

  const editingSensor = editingSensorIndex === null ? null : config.rtd.sensors[editingSensorIndex]

  const renderBoardBits = (sensor) => {
    const boardIndex = Number(sensor.board_index ?? -1)
    const bits = runtime.rtd.board_bits[boardIndex]

    if (!Array.isArray(bits)) {
      return (
        <div className="sensor-board-panel missing">
          <div className="inline-row spread">
            <strong>Board {boardIndex + 1}</strong>
            <span className="valve-meta">Unavailable</span>
          </div>
          <span>Board bits are not available for this board index.</span>
        </div>
      )
    }

    return (
      <div className="sensor-board-panel">
        <div className="inline-row spread">
          <strong>Board {boardIndex + 1}</strong>
          <span className="valve-meta">{bits.length} active bit{bits.length === 1 ? '' : 's'} - manual frame edit</span>
        </div>
        <div className="bit-row wrap">
          {orderedBitIndexes(bits.length).map((bitIndex) => (
            <label key={bitIndex} className="bit-toggle">
              <span>b{bitIndex}</span>
              <input
                type="checkbox"
                checked={!!bits[bitIndex]}
                onChange={(event) => {
                  const nextBits = [...bits]
                  nextBits[bitIndex] = event.target.checked ? 1 : 0
                  onSetBoardBits(boardIndex, nextBits)
                }}
              />
            </label>
          ))}
        </div>
      </div>
    )
  }

  const addSensor = async () => {
    const nextSensor = createDefaultRtdSensor(config.rtd.sensors)
    const nextSensors = [...config.rtd.sensors, nextSensor]
    setPageError('')
    setTargetCount(String(nextSensors.length))
    await onConfigChange({
      ...config,
      rtd: {
        ...config.rtd,
        board_count: Math.max(config.rtd.board_count, nextBoardCountForSensors(nextSensors)),
        sensors: nextSensors,
      },
    })
    setEditingSensorIndex(nextSensors.length - 1)
  }

  const resizeSensors = async () => {
    const requestedCount = Number(targetCount)
    if (!Number.isInteger(requestedCount) || requestedCount < 1) {
      setPageError('RTD board count must be an integer greater than or equal to 1.')
      return
    }

    let nextSensors = [...config.rtd.sensors]
    if (requestedCount < nextSensors.length) {
      nextSensors = nextSensors.slice(0, requestedCount)
    } else {
      while (nextSensors.length < requestedCount) {
        nextSensors.push(createDefaultRtdSensor(nextSensors))
      }
    }

    setPageError('')
    await onConfigChange({
      ...config,
      rtd: {
        ...config.rtd,
        board_count: nextBoardCountForSensors(nextSensors),
        sensors: nextSensors,
      },
    })
  }

  const deleteSensor = async (index) => {
    const nextSensors = config.rtd.sensors.filter((_, sensorIndex) => sensorIndex !== index)
    setPageError('')
    setTargetCount(String(nextSensors.length))
    await onConfigChange({
      ...config,
      rtd: {
        ...config.rtd,
        board_count: nextBoardCountForSensors(nextSensors),
        sensors: nextSensors,
      },
    })
    if (editingSensorIndex === index) {
      setEditingSensorIndex(null)
    }
  }

  return (
    <>
      <div className="page-grid">
        {pageError ? <div className="error-text">{pageError}</div> : null}
        {!runtime.rtd.hardware_available ? <div className="error-text">RTD hardware writes are not active. The UI and frame bytes can still change while the shift-register chain is offline.</div> : null}
        {runtime.rtd.hardware_error ? <div className="error-text">RTD hardware error: {runtime.rtd.hardware_error}</div> : null}
        {!runtime.rtd.reverse_byte_order ? <div className="error-text">RTD reverse byte order is OFF. That does not match the working Pi script you provided.</div> : null}
        <div className="frame-bytes">Frame Bytes: {runtime.rtd.frame_bytes.map((value) => `0x${value.toString(16).padStart(2, '0')}`).join(' ')}</div>

        <Card
          title="RTD Boards"
          subtitle="Each card shows the physical board bits and opens a valve-style editor for frame position, calibration, and temperature mapping."
          collapsible
          defaultExpanded
          actions={(
            <div className="inline-row wrap">
              <input className="count-input" type="number" min="1" value={targetCount} onChange={(event) => setTargetCount(event.target.value)} />
              <button className="button-secondary" onClick={resizeSensors}>Set Count</button>
              <button className="button-secondary" onClick={() => setBulkEditing(true)}>Bulk Config</button>
            </div>
          )}
        >
          <div className="sensor-grid rtd-grid">
            {config.rtd.sensors.map((sensor, index) => {
              const equationInfo = formatEquation(sensor)
              const overridePreview = buildTemperatureOverridePreview(sensor)
              const boardBits = runtime.rtd.board_bits[Number(sensor.board_index ?? -1)]
              const estimate = estimateFromCode(sensor, bitsToCode(boardBits))

              return (
                <div key={`${sensor.sensor_name}-${index}`} className="sensor-card rtd-card">
                  <div className="inline-row spread">
                    <div>
                      <strong>{sensor.sensor_name}</strong>
                      <div className="valve-meta">Board {Number(sensor.board_index) + 1}</div>
                    </div>
                    <div className="inline-row wrap">
                      <span className="profile-chip cv">P{sensor.position}</span>
                      <span className="profile-chip ov">{normalizeBitWidth(sensor.bit_width)}-BIT</span>
                    </div>
                  </div>

                  <div className="valve-state-banner rtd-state-banner">
                    <span className="valve-state-label">Output Mapping</span>
                    <div className="rtd-banner-summary">
                      <div className="rtd-banner-item">
                        <span className="rtd-banner-key">Frame Position</span>
                        <strong className="rtd-banner-value">{sensor.position}</strong>
                      </div>
                      <div className="rtd-banner-item">
                        <span className="rtd-banner-key">Res</span>
                        <strong className="rtd-banner-value">{formatNumber(estimate.resistance, 2)} Ω</strong>
                      </div>
                      <div className="rtd-banner-item">
                        <span className="rtd-banner-key">Est Temp</span>
                        <strong className="rtd-banner-value">{formatNumber(estimate.temperature, 2)} °C</strong>
                      </div>
                    </div>
                  </div>

                  <div className="valve-detail-list subdued">
                    <div className="inline-row spread"><span>Logical Address</span><span>Stack {sensor.logical_stack ?? 0}, Ch {sensor.logical_channel ?? 1}</span></div>
                    <div className="inline-row spread"><span>Resistance Range</span><span>{formatNumber(sensor.min_res_ohms, 1)} to {formatNumber(sensor.max_res_ohms, 1)} Ω</span></div>
                    <div className="inline-row spread"><span>Temp Range</span><span>{formatNumber(sensor.temp_min_c, 1)} to {formatNumber(sensor.temp_max_c, 1)} °C</span></div>
                    <div className="inline-row spread"><span>Res Step</span><span>{formatNumber(sensor.res_step_ohms, 2)} Ω</span></div>
                    <div className="rtd-detail-grid">
                      <span>Equation</span>
                      <span>{equationInfo.activeText}</span>
                    </div>
                    <div className="inline-row spread"><span>Temp Override</span><span>{overridePreview ? `${formatNumber(overridePreview.temperature, 2)} °C -> ${overridePreview.bits}` : 'None'}</span></div>
                  </div>

                  {renderBoardBits(sensor)}

                  <div className="inline-row wrap valve-actions">
                    <button className="button-secondary" onClick={() => setEditingSensorIndex(index)}>RTD Sensor Config</button>
                    <button className="button-danger" onClick={() => deleteSensor(index)}>Delete</button>
                  </div>
                </div>
              )
            })}

            <button className="add-card" onClick={addSensor}>
              <span className="add-card-mark">+</span>
              <strong>Add RTD Sensor</strong>
              <span>Creates the next RTD board with default mapping, calibration, and equation settings.</span>
            </button>
          </div>
        </Card>
      </div>

      <RtdSensorConfigDialog
        sensor={editingSensor}
        sensorIndex={editingSensorIndex}
        config={config}
        onConfigChange={onConfigChange}
        onClose={() => setEditingSensorIndex(null)}
      />
      <RtdBulkConfigDialog
        sensors={bulkEditing ? config.rtd.sensors : null}
        config={config}
        onConfigChange={onConfigChange}
        open={bulkEditing}
        onClose={() => setBulkEditing(false)}
      />
    </>
  )
}
