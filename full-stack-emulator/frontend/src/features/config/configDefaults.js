function nextNumberFromNames(items, prefixRegex) {
  return items.reduce((max, item) => {
    const match = String(item.id ?? item.sensor_name ?? '').match(prefixRegex)
    if (!match) return max
    return Math.max(max, Number(match[1]))
  }, 0) + 1
}

function firstMissingNumberFromNames(items, prefixRegex) {
  const used = new Set(
    items
      .map((item) => String(item.id ?? item.sensor_name ?? '').match(prefixRegex))
      .filter(Boolean)
      .map((match) => Number(match[1]))
      .filter((value) => Number.isInteger(value) && value > 0),
  )

  let candidate = 1
  while (used.has(candidate)) {
    candidate += 1
  }
  return candidate
}

function firstAvailableDetectorPair(valves) {
  const used = new Set(
    valves
      .filter((valve) => valve.profile_type === 'ov')
      .flatMap((valve) => [valve.open_detector, valve.close_detector]
        .filter(Boolean)
        .map((channel) => `${channel.i2c_address}:${channel.channel}`)),
  )

  for (let address = 0x20; address <= 0x27; address += 1) {
    for (let channel = 1; channel <= 15; channel += 2) {
      const openKey = `${address}:${channel}`
      const closeKey = `${address}:${channel + 1}`
      if (!used.has(openKey) && !used.has(closeKey)) {
        return [
          { i2c_address: address, channel },
          { i2c_address: address, channel: channel + 1 },
        ]
      }
    }
  }

  return [
    { i2c_address: 0x20, channel: 1 },
    { i2c_address: 0x20, channel: 2 },
  ]
}

function firstAvailableAnalogValveChannel(valves) {
  const available = [
    ...Array.from({ length: 16 }, (_, index) => ({ stack: 0, channel: index + 1 })),
    ...Array.from({ length: 16 }, (_, index) => ({ stack: 1, channel: index + 1 })),
    ...Array.from({ length: 4 }, (_, index) => ({ stack: 2, channel: index + 1 })),
  ]

  const used = new Set(
    valves
      .filter((valve) => valve.profile_type === 'cv' && valve.input_channel)
      .map((valve) => `${valve.input_channel.stack}:${valve.input_channel.channel}`),
  )

  return available.find((item) => !used.has(`${item.stack}:${item.channel}`)) ?? { stack: 0, channel: 0 }
}

function firstAvailableFeedbackPair(valves, fieldNames) {
  const used = new Set(
    valves
      .filter((valve) => valve.profile_type === 'ov')
      .flatMap((valve) => fieldNames
        .map((fieldName) => valve[fieldName])
        .filter(Boolean)
        .map((channel) => `${channel.stack}:${channel.channel}`)),
  )

  for (let stack = 0; stack <= 7; stack += 1) {
    for (let channel = 1; channel <= 15; channel += 2) {
      const openKey = `${stack}:${channel}`
      const closeKey = `${stack}:${channel + 1}`
      if (!used.has(openKey) && !used.has(closeKey)) {
        return [
          { stack, channel },
          { stack, channel: channel + 1 },
        ]
      }
    }
  }

  return [
    { stack: 0, channel: 1 },
    { stack: 0, channel: 2 },
  ]
}

export function createDefaultValve(valves, profileType = 'cv') {
  const sameProfile = valves.filter((valve) => valve.profile_type === profileType)
  const prefix = profileType === 'ov' ? 'OV' : 'CV'
  const nextNumber = firstMissingNumberFromNames(sameProfile, new RegExp(`^${prefix}(\\d+)$`, 'i'))
  const id = `${prefix}${nextNumber}`
  const analogChannel = firstAvailableAnalogValveChannel(valves)

  if (profileType === 'ov') {
    const openDetector = { i2c_address: null, channel: 1 }
    const closeDetector = { i2c_address: null, channel: 2 }
    const [openFeedback, closeFeedback] = firstAvailableFeedbackPair(valves, ['open_feedback', 'close_feedback'])

    return {
      id,
      name: `OV Valve ${nextNumber}`,
      enabled: true,
      profile_type: 'ov',
      open_detector: openDetector,
      close_detector: closeDetector,
      open_feedback: openFeedback,
      close_feedback: closeFeedback,
      behavior: {
        detector_delay_seconds: 3,
        feedback_hold_seconds: 1,
        default_position: 'open',
      },
    }
  }

  return {
    id,
    name: `CV Valve ${nextNumber}`,
    enabled: true,
    profile_type: 'cv',
    relay_detector: { i2c_address: null, channel: 1 },
    input_channel: analogChannel,
    output_channel: { ...analogChannel },
    behavior: {
      ramp_seconds: 90,
      v_min: 2,
      v_max: 10,
      cmd_threshold: 1.9,
      target_deadband: 0.05,
    },
  }
}

export function convertValveProfile(valves, valve, profileType) {
  const otherValves = valves.filter((item) => item.id !== valve.id)
  const template = createDefaultValve(otherValves, profileType)
  return {
    ...template,
    id: valve.id,
    name: valve.name,
    enabled: valve.enabled,
  }
}

export function createDefaultRelayDetectorStack(stacks) {
  const nextAddress = stacks.reduce((max, item) => Math.max(max, Number(item.i2c_address ?? 0x1f)), 0x1f) + 1
  return {
    i2c_address: nextAddress,
    i2c_bus: 1,
    active_low: false,
    use_internal_pullups: false,
    enabled: true,
  }
}

export function createDefaultRtdSensor(sensors) {
  const nextNumber = nextNumberFromNames(sensors, /^T(\d+)$/i)
  const nextBoardIndex = sensors.reduce((max, sensor) => Math.max(max, Number(sensor.board_index ?? -1)), -1) + 1

  return {
    sensor_name: `T${nextNumber}`,
    board_index: nextBoardIndex,
    position: sensors.reduce((max, sensor) => Math.max(max, Number(sensor.position ?? 0)), 0) + 1,
    bit_width: 5,
    logical_stack: Math.floor(nextBoardIndex / 8),
    logical_channel: (nextBoardIndex % 8) + 1,
    min_res_ohms: 95,
    max_res_ohms: 150,
    temp_min_c: -10,
    temp_max_c: 80,
    res_step_ohms: 2,
    use_custom_equation: false,
    custom_equation_a: null,
    custom_equation_b: null,
    output_temp_c: null,
  }
}

function firstAvailableLeakOutputChannel(sensors) {
  const used = new Set(
    sensors.map((sensor) => `${sensor.output_channel?.stack ?? 3}:${sensor.output_channel?.channel ?? 1}`),
  )

  for (let stack = 3; stack <= 7; stack += 1) {
    for (let channel = 1; channel <= 16; channel += 1) {
      const key = `${stack}:${channel}`
      if (!used.has(key)) {
        return { stack, channel }
      }
    }
  }

  return { stack: 3, channel: 1 }
}

export function createDefaultLeakSensor(sensors) {
  const nextNumber = firstMissingNumberFromNames(sensors, /^LS(\d+)$/i)
  const outputChannel = firstAvailableLeakOutputChannel(sensors)

  return {
    id: `LS${nextNumber}`,
    name: `Leak Sensor ${nextNumber}`,
    output_channel: outputChannel,
    voltage: 0,
  }
}
