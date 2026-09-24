const API_BASE = import.meta.env.VITE_API_BASE || ''

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  })
  if (!response.ok) {
    const text = await response.text()
    throw new Error(text || `HTTP ${response.status}`)
  }
  if (response.status === 204) {
    return null
  }
  return response.json()
}

export const api = {
  getConfig: () => request('/api/config'),
  putConfig: (config) => request('/api/config', { method: 'PUT', body: JSON.stringify(config) }),
  getRuntime: () => request('/api/runtime'),
  loadCsv: (payload) => request('/api/runtime/rtd/csv', { method: 'POST', body: JSON.stringify(payload) }),
  clearCsv: () => request('/api/runtime/rtd/csv/clear', { method: 'POST' }),
  setPlayback: (playing) => request('/api/runtime/rtd/playback', { method: 'POST', body: JSON.stringify({ playing }) }),
  setBoardBits: (boardIndex, bits) => request(`/api/runtime/rtd/boards/${boardIndex}`, { method: 'POST', body: JSON.stringify({ bits }) }),
  setValveOverride: (valveId, voltage) => request(`/api/runtime/valves/${valveId}/input-override`, { method: 'POST', body: JSON.stringify({ voltage }) }),
  setLeakSensorVoltage: (sensorId, voltage) => request(`/api/runtime/leak-sensors/${sensorId}/voltage`, { method: 'POST', body: JSON.stringify({ voltage }) }),
  startArcticServer: () => request('/api/runtime/arctic-hp/server/start', { method: 'POST' }),
  stopArcticServer: () => request('/api/runtime/arctic-hp/server/stop', { method: 'POST' }),
  setArcticRegister: (deviceId, address, value) => request(`/api/runtime/arctic-hp/${deviceId}/registers/${address}`, { method: 'POST', body: JSON.stringify({ value }) }),
  resetArcticDevice: (deviceId) => request(`/api/runtime/arctic-hp/${deviceId}/reset`, { method: 'POST' }),
}
