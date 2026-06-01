import { Link, Outlet, useLocation } from "react-router-dom";
import {
  Home,
  Newspaper,
  Calendar,
  Briefcase,
  TrendingUp,
  Settings,
} from "lucide-react";
import { cn } from "@/lib/utils";

const nav = [
  { to: "/", label: "Home", icon: Home, end: true },
  { to: "/stories", label: "Stories", icon: Newspaper },
  { to: "/recommendations", label: "Trading plan", icon: Calendar },
  { to: "/portfolio", label: "Portfolio", icon: Briefcase },
  { to: "/insights", label: "Insights", icon: TrendingUp },
];

export function Layout() {
  const location = useLocation();

  const active = (path: string, end?: boolean) => {
    if (end) return location.pathname === path;
    return location.pathname.startsWith(path);
  };

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col">
      <header className="bg-white border-b border-gray-200 sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between h-16 gap-4">
            <div className="flex items-center gap-3 shrink-0">
              <TrendingUp className="w-8 h-8 text-blue-600" />
              <h1 className="text-xl font-semibold text-gray-900 hidden sm:block">Trading Intelligence</h1>
            </div>
            <nav className="flex items-center gap-1 flex-wrap justify-center">
              {nav.map(({ to, label, icon: Icon, end }) => (
                <Link
                  key={to}
                  to={to}
                  className={cn(
                    "flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium transition-colors",
                    active(to, end)
                      ? "bg-blue-50 text-blue-700"
                      : "text-gray-600 hover:text-gray-900 hover:bg-gray-50"
                  )}
                >
                  <Icon className="w-4 h-4" />
                  <span className="hidden md:inline">{label}</span>
                </Link>
              ))}
            </nav>
            <Link
              to="/settings"
              className={cn(
                "flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium",
                active("/settings") ? "bg-blue-50 text-blue-700" : "text-gray-600 hover:bg-gray-50"
              )}
            >
              <Settings className="w-4 h-4" />
            </Link>
          </div>
        </div>
      </header>
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <Outlet />
      </main>
      <footer className="border-t border-gray-200 bg-white">
        <div className="max-w-7xl mx-auto px-4 py-4">
          <p className="text-xs text-gray-500 text-center">
            Educational purposes only. Not investment advice. Execute trades manually in Sofi.
          </p>
        </div>
      </footer>
    </div>
  );
}
