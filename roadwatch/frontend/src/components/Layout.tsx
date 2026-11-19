import { Menu, X } from "lucide-react";
import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { TopBar } from "./TopBar";

const NAV_ITEMS = [
  { to: "/", label: "Dashboard", icon: "◉" },
  { to: "/studio", label: "Detection Studio", icon: "▶" },
  { to: "/map", label: "Hazard Map", icon: "◆" },
  { to: "/simulation", label: "Simulation", icon: "→" },
  { to: "/settings", label: "Settings", icon: "⚙" },
];

export function Layout() {
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <div className="flex min-h-screen flex-col md:flex-row">
      {/* Sidebar */}
      <aside
        className={`fixed inset-y-0 left-0 z-40 w-64 transform border-r-[3px] border-ink bg-ink text-canvas transition-transform md:static md:translate-x-0 ${
          menuOpen ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <div className="flex items-center justify-between border-b-[3px] border-canvas/30 px-5 py-5">
          <div>
            <div className="font-display text-2xl font-bold tracking-tight text-accent-yellow">
              ROADWATCH
            </div>
            <div className="font-mono text-[10px] uppercase tracking-widest text-canvas/70">
              Roads, observed.
            </div>
          </div>
          <button
            className="text-canvas md:hidden"
            onClick={() => setMenuOpen(false)}
            aria-label="Close menu"
          >
            <X size={22} />
          </button>
        </div>

        <nav className="flex flex-col gap-1 p-3" aria-label="Main navigation">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              onClick={() => setMenuOpen(false)}
              className={({ isActive }) =>
                `flex items-center gap-3 border-[3px] px-3 py-2.5 font-display text-sm font-bold uppercase tracking-wide transition-colors ${
                  isActive
                    ? "border-canvas bg-accent-yellow text-ink"
                    : "border-transparent text-canvas hover:border-canvas/50 hover:bg-white/10"
                }`
              }
            >
              <span aria-hidden className="w-4 text-center">{item.icon}</span>
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="absolute bottom-0 left-0 right-0 border-t-[3px] border-canvas/30 p-4">
          <span className="nb-tag bg-accent-mint text-ink">LOCAL ONLY</span>
        </div>
      </aside>

      {menuOpen && (
        <div
          className="fixed inset-0 z-30 bg-ink/50 md:hidden"
          onClick={() => setMenuOpen(false)}
          aria-hidden
        />
      )}

      {/* Main column */}
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar onMenuToggle={() => setMenuOpen((v) => !v)} menuOpen={menuOpen} />
        <main className="flex-1 p-4 md:p-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

export { Menu };
