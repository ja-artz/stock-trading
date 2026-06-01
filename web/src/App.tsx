import { NavLink, Route, Routes } from "react-router-dom";
import Dashboard from "./pages/Dashboard";
import Stories from "./pages/Stories";
import WeeklyPlan from "./pages/WeeklyPlan";
import Portfolio from "./pages/Portfolio";
import Insights from "./pages/Insights";
import Settings from "./pages/Settings";

export default function App() {
  return (
    <>
      <nav>
        <NavLink to="/" end>Home</NavLink>
        <NavLink to="/stories">Stories</NavLink>
        <NavLink to="/weekly-plan">Weekly plan</NavLink>
        <NavLink to="/portfolio">Portfolio</NavLink>
        <NavLink to="/insights">Insights</NavLink>
        <NavLink to="/settings">Settings</NavLink>
      </nav>
      <main>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/stories" element={<Stories />} />
          <Route path="/weekly-plan" element={<WeeklyPlan />} />
          <Route path="/portfolio" element={<Portfolio />} />
          <Route path="/insights" element={<Insights />} />
          <Route path="/settings" element={<Settings />} />
        </Routes>
        <p className="disclaimer">
          Educational tool only. Not investment advice. Execute trades manually in Sofi.
        </p>
      </main>
    </>
  );
}
