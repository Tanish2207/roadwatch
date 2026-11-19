import { Route, Routes } from "react-router-dom";
import { Layout } from "../components/Layout";
import { Dashboard } from "../pages/Dashboard";
import { DetectionStudio } from "../pages/DetectionStudio";
import { HazardMap } from "../pages/HazardMap";
import { Settings } from "../pages/Settings";
import { Simulation } from "../pages/Simulation";

export function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Dashboard />} />
        <Route path="/studio" element={<DetectionStudio />} />
        <Route path="/map" element={<HazardMap />} />
        <Route path="/simulation" element={<Simulation />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="*" element={<Dashboard />} />
      </Route>
    </Routes>
  );
}
