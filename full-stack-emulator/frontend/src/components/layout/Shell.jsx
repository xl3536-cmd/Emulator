export default function Shell({ tabs, activeTab, onTabChange, children, status }) {
  return (
    <div className="app-shell">
      <header className="hero">
        <div>
          <h1>Full Stack Emulator</h1>
          <p className="hero-copy">RTD ladder control, grouped CV and OV valves, leak-sensor outputs, Arctic heat pumps, and Grundfos BACnet MS/TP pumps.</p>
        </div>
        <div className="hero-status">
          <span>{status}</span>
        </div>
      </header>
      <div className="tabs-sticky-wrap">
        <nav className="tabs">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              className={tab.id === activeTab ? 'tab active' : 'tab'}
              onClick={() => onTabChange(tab.id)}
            >
              {tab.label}
            </button>
          ))}
        </nav>
      </div>
      <main>{children}</main>
    </div>
  )
}
