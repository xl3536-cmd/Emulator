import Card from '../../components/common/Card'

export default function DashboardPage({ runtime }) {
  const connectedValves = runtime.valves.ball_valves.filter((item) => !item.missing_board).length
  const leakSensors = runtime.leak_sensors?.sensors ?? []
  const liveLeakSensors = leakSensors.filter((item) => item.available).length
  const activeLeakOutputs = leakSensors.filter((item) => Number(item.voltage ?? 0) > 0.01).length
  const slowMode = runtime.rtd.playback.mode === 'slow'
  const arcticServer = runtime.arctic_hp.server

  return (
    <div className="page-grid">
      <Card title="System Summary" subtitle="Live emulator state with RTD, valves, leak sensors, and Arctic HP status.">
        <div className="stat-grid">
          <div><strong>{runtime.rtd.board_count}</strong><span>RTD Boards</span></div>
          <div><strong>{runtime.rtd.playback.row_count}</strong><span>CSV Rows</span></div>
          <div><strong>{connectedValves}/{runtime.valves.ball_valves.length}</strong><span>Valve Boards Present</span></div>
          <div><strong>{liveLeakSensors}/{leakSensors.length}</strong><span>Leak Sensors Live</span></div>
          <div><strong>{activeLeakOutputs}</strong><span>Leak Outputs Active</span></div>
          <div><strong>{slowMode ? 'SLOW' : 'FAST'}</strong><span>Playback Mode</span></div>
          <div><strong>{arcticServer.running ? 'RUNNING' : 'STOPPED'}</strong><span>Arctic Server</span></div>
          <div><strong>{arcticServer.transport_available ? 'ONLINE' : 'OFFLINE'}</strong><span>Arctic Transport</span></div>
        </div>
      </Card>

      <Card title="Module Guide" subtitle="How each emulator module works and what drives its runtime behavior.">
        <div className="dashboard-guide-grid">
          <section className="dashboard-guide-card">
            <span className="dashboard-guide-tag">RTD</span>
            <strong>Shift-register resistance emulator</strong>
            <p>Each RTD card owns one board index and one frame position. The board bits convert to resistance using the configured step size, then to estimated temperature using either the default line fit or your custom equation.</p>
            <p>RTD output can come from manual board bits, config temperature overrides, or the Scheduling CSV. The Scheduling tab links CSV columns to the actual RTD cards by <code>sensor_name</code> or <code>T&#123;board_index + 1&#125;</code> and updates the live frame bytes from the current row.</p>
          </section>
          <section className="dashboard-guide-card">
            <span className="dashboard-guide-tag">CV</span>
            <strong>Continuous valve analog tracker</strong>
            <p>CV valves only follow command VIN when the relay detector is ON. Detector OFF forces feedback VOUT to <code>0V</code> while keeping the last tracked target in memory.</p>
            <p>When detector is ON and VIN is above the command threshold, the valve ramps between <code>v_min</code> and <code>v_max</code> over the configured ramp time. The dashboard slow mode also activates during these <code>RAMP_UP</code> and <code>RAMP_DOWN</code> periods.</p>
          </section>
          <section className="dashboard-guide-card">
            <span className="dashboard-guide-tag">OV</span>
            <strong>Open-close detector and feedback relay emulator</strong>
            <p>OV valves watch separate open and close detector inputs. A rising edge starts a wait timer, then the emulator pulses the matching feedback relay and settles the stored position to <code>OPEN</code> or <code>CLOSED</code>.</p>
            <p>Runtime slow mode stays active during <code>WAIT_OPEN</code>, <code>WAIT_CLOSE</code>, <code>OPEN_FEEDBACK</code>, and <code>CLOSE_FEEDBACK</code>. Scheduling slow mode can also activate earlier when an upcoming CSV valve marker changes <code>0 -&gt; 1</code> or <code>1 -&gt; 0</code>.</p>
          </section>
          <section className="dashboard-guide-card">
            <span className="dashboard-guide-tag">Leak</span>
            <strong>Standalone analog leak-sensor output cards</strong>
            <p>Each leak sensor card owns one named analog output assignment with a stack, a channel, and a target voltage from <code>0V</code> to <code>10V</code>.</p>
            <p>The card editor and bulk config table write the saved configuration, while <code>Set Voltage</code> pushes the current card voltage to the assigned output channel in runtime.</p>
          </section>
          <section className="dashboard-guide-card">
            <span className="dashboard-guide-tag">Arctic</span>
            <strong>Card-based Arctic HP emulator with reflected control registers</strong>
            <p>The Arctic page now surfaces the most important heat-pump values as cards first: power state, working mode, setpoints, ambient and water temperatures, compressor frequency, and electrical readings.</p>
            <p>Controller-writable registers are shown as reflected readback values, while manual apply stays limited to readable sensor and status registers. Serial settings, device metadata, and the full register table remain available under advanced sections.</p>
          </section>
        </div>
      </Card>
    </div>
  )
}
