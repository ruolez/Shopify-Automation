import { Routes, Route, Navigate } from "react-router-dom";
import { useAuth } from "./contexts/AuthContext";
import { SettingsProvider } from "./contexts/SettingsContext";
import { TimezoneProvider } from "./contexts/TimezoneContext";
import { ThemeProvider } from "./contexts/ThemeContext";
import Layout from "./components/Layout";
import Login from "./pages/Login";
import Register from "./pages/Register";
import Dashboard from "./pages/Dashboard";
import Stores from "./pages/Stores";
import Rules from "./pages/Rules";
import RuleBuilder from "./pages/RuleBuilder";
import FraudDetection from "./pages/FraudDetection";
import FraudRuleBuilder from "./components/FraudRuleBuilder";
import Inventory from "./pages/Inventory";
import OrderLogs from "./pages/OrderLogs";
import Settings from "./pages/Settings";
import LocationManagement from "./pages/LocationManagement";
import Reports from "./pages/Reports";
import LoadingSpinner from "./components/LoadingSpinner";
import AdminLogin from "./pages/AdminLogin";
import AdminDashboard from "./pages/AdminDashboard";
import AdminUsers from "./pages/AdminUsers";
import AdminDatabase from "./pages/AdminDatabase";

function App() {
  const { user, loading } = useAuth();

  if (loading) {
    return (
      <ThemeProvider>
        <div className="min-h-screen flex items-center justify-center">
          <LoadingSpinner size="lg" />
        </div>
      </ThemeProvider>
    );
  }

  // Admin routes (separate from user authentication)
  const isAdminRoute = window.location.pathname.startsWith("/admin");

  if (isAdminRoute) {
    return (
      <ThemeProvider>
        <Routes>
          <Route path="/admin/login" element={<AdminLogin />} />
          <Route path="/admin/dashboard" element={<AdminDashboard />} />
          <Route path="/admin/users" element={<AdminUsers />} />
          <Route path="/admin/database" element={<AdminDatabase />} />
          <Route
            path="/admin/*"
            element={<Navigate to="/admin/login" replace />}
          />
        </Routes>
      </ThemeProvider>
    );
  }

  if (!user) {
    return (
      <ThemeProvider>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />
          <Route path="*" element={<Navigate to="/login" replace />} />
        </Routes>
      </ThemeProvider>
    );
  }

  return (
    <ThemeProvider>
      <SettingsProvider>
        <TimezoneProvider>
          <Layout>
            <Routes>
              <Route path="/" element={<Dashboard />} />
              <Route path="/stores" element={<Stores />} />
              <Route path="/rules" element={<Rules />} />
              <Route path="/rules/new" element={<RuleBuilder />} />
              <Route path="/rules/:id/edit" element={<RuleBuilder />} />
              <Route path="/fraud-detection" element={<FraudDetection />} />
              <Route path="/fraud-detection/rules/new" element={<FraudRuleBuilder />} />
              <Route path="/fraud-detection/rules/:id/edit" element={<FraudRuleBuilder />} />
              <Route path="/inventory" element={<Inventory />} />
              <Route path="/order-logs" element={<OrderLogs />} />
              <Route path="/settings" element={<Settings />} />
              <Route path="/locations" element={<LocationManagement />} />
              <Route path="/reports" element={<Reports />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </Layout>
        </TimezoneProvider>
      </SettingsProvider>
    </ThemeProvider>
  );
}

export default App;
