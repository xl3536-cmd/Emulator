import { useEffect, useMemo, useRef, useState } from 'react'

import Card from '../../components/common/Card'
import { updateConfigAtPath } from '../config/updateConfigAtPath'

function parseCsvText(text) {
  const lines = text.split(/\r?\n/).filter(Boolean)
  if (lines.length === 0) {
    return { header: [], rows: [] }
  }
  const header = lines[0].split(',').map((item) => item.trim())
  const rows = lines.slice(1).map((line) => {
    const parts = line.split(',')
    const row = {}
    header.forEach((column, index) => {
      row[column] = parts[index] ?? ''
    })
    return row
  })
  return { header, rows }
}

function normalizeBitWidth(value) {
  return Number(value) === 8 ? 8 : 5
}

function formatNumber(value, digits = 2) {
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
    }
  }
  return deriveDefaultEquation(sensor)
}

function estimateFromCode(sensor, code) {
  const equation = resolveEquation(sensor)
  const maxRes = Number(sensor.max_res_ohms ?? 150)
  const step = Number(sensor.res_step_ohms ?? 2)
  const resistance = maxRes - (Number(code) * step)
  const temperature = (equation.a * resistance) + equation.b
  return {
    resistance,
    temperature,
  }
}

function buildBitsFromCode(code, bitWidth) {
  const width = normalizeBitWidth(bitWidth)
  return Array.from({ length: width }, (_, offset) => {
    const index = width - 1 - offset
    return ((Number(code) >> index) & 1) ? '1' : '0'
  }).join('')
}

function formatOutputSource(source) {
  if (source === 'csv') return 'Scheduling CSV'
  if (source === 'override') return 'Config Override'
  return 'Manual Bits'
}

function getModeChipClass(playback) {
  if (playback.mode === 'slow' && playback.slow_reason === 'csv_valve_change') return 'status-chip slow'
  if (playback.mode === 'slow') return 'status-chip runtime'
  return 'status-chip fast'
}

function formatValveMarkerValue(value, profileType) {
  if (profileType === 'cv') {
    const numeric = Number(value)
    if (!Number.isFinite(numeric)) return '0'
    return numeric.toFixed(2).replace(/\.?0+$/, '')
  }
  return value ? '1' : '0'
}

export default function SchedulingPage({ config, runtime, onConfigChange, onLoadCsv, onSetPlayback, onClearCsv }) {
  const [playbackTiming, setPlaybackTiming] = useState({
    fastSeconds: String(config.rtd.playback.fast_interval_seconds ?? 1),
    slowSeconds: String(config.rtd.playback.slow_interval_seconds ?? 60),
  })
  const [timingError, setTimingError] = useState('')
  const fileInputRef = useRef(null)

  useEffect(() => {
    setPlaybackTiming({
      fastSeconds: String(config.rtd.playback.fast_interval_seconds ?? 1),
      slowSeconds: String(config.rtd.playback.slow_interval_seconds ?? 60),
    })
    setTimingError('')
  }, [config.rtd.playback.fast_interval_seconds, config.rtd.playback.slow_interval_seconds])

  const applyPlaybackTiming = async () => {
    const fastSeconds = Number(playbackTiming.fastSeconds)
    const slowSeconds = Number(playbackTiming.slowSeconds)
    if (!Number.isFinite(fastSeconds) || fastSeconds < 1) {
      setTimingError('Fast row interval must be at least 1 second.')
      return
    }
    if (!Number.isFinite(slowSeconds) || slowSeconds < 1) {
      setTimingError('Slow row interval must be at least 1 second.')
      return
    }
    setTimingError('')
    const nextConfig = updateConfigAtPath(
      updateConfigAtPath(config, ['rtd', 'playback', 'fast_interval_seconds'], fastSeconds),
      ['rtd', 'playback', 'slow_interval_seconds'],
      slowSeconds,
    )
    await onConfigChange(nextConfig)
  }

  const currentRowLabel = runtime.rtd.playback.row_index >= 0
    ? `${runtime.rtd.playback.row_index + 1} / ${runtime.rtd.playback.row_count}`
    : 'Not started'

  const rtdPreview = useMemo(() => (
    config.rtd.sensors.map((sensor) => {
      const code = runtime.rtd.current_rtd_codes[sensor.sensor_name]
      const estimate = estimateFromCode(sensor, Number.isFinite(Number(code)) ? Number(code) : 0)
      return {
        sensor_name: sensor.sensor_name,
        bits: buildBitsFromCode(code ?? 0, sensor.bit_width),
        resistance: estimate.resistance,
        temperature: estimate.temperature,
      }
    })
  ), [config.rtd.sensors, runtime.rtd.current_rtd_codes])

  const valvePreview = useMemo(() => (
    config.valves.ball_valves
      .filter((valve) => runtime.rtd.playback.matched_valve_columns[valve.id])
      .map((valve) => ({
        id: valve.id,
        profile_type: valve.profile_type,
        header: runtime.rtd.playback.matched_valve_columns[valve.id],
        value: runtime.rtd.current_valve_states[valve.id],
      }))
  ), [config.valves.ball_valves, runtime.rtd.current_valve_states, runtime.rtd.playback.matched_valve_columns])

  const loadedFileLabel = runtime.rtd.playback.loaded_filename || 'No file loaded'

  return (
    <div className="page-grid">
        <Card
          title="Scheduling CSV"
        subtitle="Upload one CSV that schedules RTD board codes plus optional CV and OV marker columns. OV markers slow on any state change. CV markers slow when the scheduled value changes by at least 0.01. CSV valve markers do not drive live valve hardware."
        actions={(
          <div className="button-row">
            <button onClick={() => onSetPlayback(true)} disabled={!runtime.rtd.playback.loaded}>Start</button>
            <button onClick={() => onSetPlayback(false)}>Stop</button>
            <button className="button-secondary" onClick={onClearCsv} disabled={!runtime.rtd.playback.loaded}>Clear File</button>
          </div>
        )}
      >
        <div className="inline-row wrap">
          <input
            ref={fileInputRef}
            style={{ display: 'none' }}
            type="file"
            accept=".csv"
            onChange={async (event) => {
              const file = event.target.files?.[0]
              if (!file) return
              const text = await file.text()
              await onLoadCsv({ ...parseCsvText(text), filename: file.name })
              event.target.value = ''
            }}
          />
          <button className="button-secondary" onClick={() => fileInputRef.current?.click()}>Choose CSV</button>
          <span>Loaded File: {loadedFileLabel}</span>
          <span>Current Row: {currentRowLabel}</span>
          <span className={getModeChipClass(runtime.rtd.playback)}>
            Mode: {runtime.rtd.playback.mode.toUpperCase()}
          </span>
          {runtime.rtd.playback.slow_reason === 'csv_valve_change' ? <span>CSV Valve Change</span> : null}
          {runtime.rtd.playback.slow_reason === 'runtime' ? <span>Valve Runtime Slowdown</span> : null}
          <span>{runtime.rtd.playback.playing ? 'Playing' : 'Stopped'}</span>
          <span>Timestamp: {runtime.rtd.playback.last_timestamp || 'n/a'}</span>
          <span>Rows: {runtime.rtd.playback.row_count}</span>
          <span>RTD Matches: {Object.keys(runtime.rtd.playback.matched_rtd_columns).length}</span>
          <span>Valve Matches: {Object.keys(runtime.rtd.playback.matched_valve_columns).length}</span>
          <span>Source: {formatOutputSource(runtime.rtd.output_source)}</span>
        </div>
        <div className="inline-fields">
          <label>
            <span>Fast Row Time (sec)</span>
            <input
              type="number"
              min="1"
              step="1"
              value={playbackTiming.fastSeconds}
              onChange={(event) => setPlaybackTiming((current) => ({ ...current, fastSeconds: event.target.value }))}
            />
          </label>
          <label>
            <span>Slow Row Time (sec)</span>
            <input
              type="number"
              min="1"
              step="1"
              value={playbackTiming.slowSeconds}
              onChange={(event) => setPlaybackTiming((current) => ({ ...current, slowSeconds: event.target.value }))}
            />
          </label>
          <div className="button-row">
            <button onClick={applyPlaybackTiming}>Apply Row Timing</button>
          </div>
        </div>
        {timingError ? <div className="error-text">{timingError}</div> : null}
        {!runtime.rtd.hardware_available ? <div className="error-text">RTD hardware writes are not active. CSV scheduling still updates the live frame preview while the shift-register chain is offline.</div> : null}
        {runtime.rtd.hardware_error ? <div className="error-text">RTD hardware error: {runtime.rtd.hardware_error}</div> : null}
        {!runtime.rtd.reverse_byte_order ? <div className="error-text">RTD reverse byte order is OFF. That does not match the working Pi script you provided.</div> : null}
        <div className="frame-bytes">Frame Bytes: {runtime.rtd.frame_bytes.map((value) => `0x${value.toString(16).padStart(2, '0')}`).join(' ')}</div>
      </Card>

      <div className="page-grid two-up">
        <Card title="RTD Preview" subtitle="Current row mapped through each RTD equation so you can see the scheduled resistance and estimated temperature.">
          <div className="table-wrap tall">
            <table>
              <thead>
                <tr>
                  <th>Sensor</th>
                  <th>Bits</th>
                  <th>Resistance</th>
                  <th>Est Temp</th>
                </tr>
              </thead>
              <tbody>
                {runtime.rtd.playback.loaded ? rtdPreview.map((item) => (
                  <tr key={item.sensor_name}>
                    <td>{item.sensor_name}</td>
                    <td>{item.bits}</td>
                    <td>{formatNumber(item.resistance, 2)} Ω</td>
                    <td>{formatNumber(item.temperature, 2)} °C</td>
                  </tr>
                )) : (
                  <tr>
                    <td colSpan="4">No CSV uploaded.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </Card>

        <Card title="Valve Markers" subtitle="Matched CSV valve columns by exact valve card ID. These markers only influence fast versus slow scheduling when a value changes between rows.">
          <div className="table-wrap tall">
            <table>
              <thead>
                <tr>
                  <th>Valve</th>
                  <th>Type</th>
                  <th>CSV Header</th>
                  <th>Current Value</th>
                </tr>
              </thead>
              <tbody>
                {valvePreview.length > 0 ? valvePreview.map((item) => (
                  <tr key={item.id}>
                    <td>{item.id}</td>
                    <td>{item.profile_type.toUpperCase()}</td>
                    <td>{item.header}</td>
                    <td>
                      {formatValveMarkerValue(item.value, item.profile_type)}
                      {runtime.rtd.playback.valve_transitions[item.id] ? ` (${runtime.rtd.playback.valve_transitions[item.id]})` : ''}
                    </td>
                  </tr>
                )) : (
                  <tr>
                    <td colSpan="4">No CSV valve headers are currently matched.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </Card>
      </div>
    </div>
  )
}
