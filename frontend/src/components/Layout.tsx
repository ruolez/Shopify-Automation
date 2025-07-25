import React, { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import {
  HomeIcon,
  BuildingStorefrontIcon,
  CogIcon,
  ArrowRightOnRectangleIcon,
  UserIcon,
  ClipboardDocumentListIcon,
  AdjustmentsHorizontalIcon,
  MapPinIcon,
  ChartBarIcon,
  ShieldExclamationIcon,
  CubeIcon,
  Bars3Icon,
  XMarkIcon,
} from "@heroicons/react/24/outline";
import { useAuth } from "../contexts/AuthContext";
import ThemeToggle from "./ThemeToggle";

interface LayoutProps {
  children: React.ReactNode;
}

const Layout: React.FC<LayoutProps> = ({ children }) => {
  const { user, logout } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const navigation = [
    { name: "Dashboard", href: "/", icon: HomeIcon },
    {
      name: "Orders",
      href: "/order-logs",
      icon: ClipboardDocumentListIcon,
    },
    {
      name: "Fraud Detection",
      href: "/fraud-detection",
      icon: ShieldExclamationIcon,
    },
    {
      name: "Inventory",
      href: "/inventory",
      icon: CubeIcon,
    },
    { name: "Rules", href: "/rules", icon: CogIcon },
    { name: "Stores", href: "/stores", icon: BuildingStorefrontIcon },
    { name: "Locations", href: "/locations", icon: MapPinIcon },
    { name: "Reports", href: "/reports", icon: ChartBarIcon },
    { name: "Settings", href: "/settings", icon: AdjustmentsHorizontalIcon },
  ];

  const handleLogout = () => {
    logout();
    navigate("/login");
  };

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-dark-50">
      {/* Mobile sidebar backdrop */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-40 bg-gray-600 bg-opacity-75 lg:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* Mobile sidebar */}
      <div className={`fixed inset-y-0 left-0 z-50 w-64 bg-white dark:bg-dark-100 shadow-lg dark:shadow-2xl border-r border-gray-200 dark:border-dark-200 transform transition-transform duration-300 ease-in-out lg:hidden ${
        sidebarOpen ? "translate-x-0" : "-translate-x-full"
      }`}>
        <div className="flex h-full flex-col">
          {/* Logo and close button */}
          <div className="flex h-16 items-center justify-between px-4 border-b border-gray-200 dark:border-dark-200">
            <h1 className="text-xl font-bold text-shopify-700 dark:text-shopify-400">
              Shopify Automation
            </h1>
            <button
              onClick={() => setSidebarOpen(false)}
              className="p-1 text-gray-400 hover:text-gray-500"
            >
              <XMarkIcon className="h-6 w-6" />
            </button>
          </div>

          {/* Navigation */}
          <nav className="flex-1 space-y-1 px-4 py-4">
            {navigation.map((item) => {
              const isActive = location.pathname === item.href;
              return (
                <Link
                  key={item.name}
                  to={item.href}
                  onClick={() => setSidebarOpen(false)}
                  className={`group flex items-center px-2 py-2 text-sm font-medium rounded-md transition-all duration-200 ${
                    isActive
                      ? "bg-shopify-100 dark:bg-shopify-800/30 text-shopify-900 dark:text-shopify-300 shadow-sm"
                      : "text-gray-600 dark:text-dark-500 hover:bg-gray-50 dark:hover:bg-dark-200 hover:text-gray-900 dark:hover:text-dark-700"
                  }`}
                >
                  <item.icon
                    className={`mr-3 h-6 w-6 flex-shrink-0 transition-colors ${
                      isActive
                        ? "text-shopify-600 dark:text-shopify-400"
                        : "text-gray-400 dark:text-dark-400 group-hover:text-gray-500 dark:group-hover:text-dark-500"
                    }`}
                  />
                  {item.name}
                </Link>
              );
            })}
          </nav>

          {/* User menu */}
          <div className="border-t border-gray-200 dark:border-dark-200 p-4">
            <div className="flex items-center">
              <div className="flex-shrink-0">
                <UserIcon className="h-8 w-8 text-gray-400 dark:text-dark-400" />
              </div>
              <div className="ml-3 flex-1">
                <p className="text-sm font-medium text-gray-900 dark:text-dark-800">
                  {user?.full_name}
                </p>
                <p className="text-xs text-gray-500 dark:text-dark-400">
                  {user?.email}
                </p>
              </div>
              <button
                onClick={handleLogout}
                className="flex-shrink-0 p-1 text-gray-400 dark:text-dark-400 hover:text-gray-500 dark:hover:text-dark-500 transition-colors"
                title="Logout"
              >
                <ArrowRightOnRectangleIcon className="h-5 w-5" />
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Desktop sidebar - now shows icons only on mobile/tablet */}
      <div className="hidden lg:fixed lg:inset-y-0 lg:left-0 lg:z-50 lg:w-16 xl:w-64 lg:bg-white lg:dark:bg-dark-100 lg:shadow-lg lg:dark:shadow-2xl lg:border-r lg:border-gray-200 lg:dark:border-dark-200 lg:block">
        <div className="flex h-full flex-col">
          {/* Logo */}
          <div className="flex h-16 items-center justify-center border-b border-gray-200 dark:border-dark-200 px-4">
            <h1 className="text-xl font-bold text-shopify-700 dark:text-shopify-400 hidden xl:block">
              Shopify Automation
            </h1>
            <BuildingStorefrontIcon className="h-8 w-8 text-shopify-700 dark:text-shopify-400 xl:hidden" />
          </div>

          {/* Navigation */}
          <nav className="flex-1 space-y-1 px-2 xl:px-4 py-4">
            {navigation.map((item) => {
              const isActive = location.pathname === item.href;
              return (
                <Link
                  key={item.name}
                  to={item.href}
                  className={`group flex items-center px-2 py-2 text-sm font-medium rounded-md transition-all duration-200 ${
                    isActive
                      ? "bg-shopify-100 dark:bg-shopify-800/30 text-shopify-900 dark:text-shopify-300 shadow-sm"
                      : "text-gray-600 dark:text-dark-500 hover:bg-gray-50 dark:hover:bg-dark-200 hover:text-gray-900 dark:hover:text-dark-700"
                  }`}
                  title={item.name}
                >
                  <item.icon
                    className={`h-6 w-6 flex-shrink-0 transition-colors xl:mr-3 ${
                      isActive
                        ? "text-shopify-600 dark:text-shopify-400"
                        : "text-gray-400 dark:text-dark-400 group-hover:text-gray-500 dark:group-hover:text-dark-500"
                    }`}
                  />
                  <span className="hidden xl:block">{item.name}</span>
                </Link>
              );
            })}
          </nav>

          {/* User menu */}
          <div className="border-t border-gray-200 dark:border-dark-200 p-2 xl:p-4">
            <div className="flex items-center justify-center xl:justify-start">
              <div className="flex-shrink-0">
                <UserIcon className="h-8 w-8 text-gray-400 dark:text-dark-400" />
              </div>
              <div className="ml-3 flex-1 hidden xl:block">
                <p className="text-sm font-medium text-gray-900 dark:text-dark-800">
                  {user?.full_name}
                </p>
                <p className="text-xs text-gray-500 dark:text-dark-400">
                  {user?.email}
                </p>
              </div>
              <button
                onClick={handleLogout}
                className="flex-shrink-0 p-1 text-gray-400 dark:text-dark-400 hover:text-gray-500 dark:hover:text-dark-500 transition-colors xl:ml-auto"
                title="Logout"
              >
                <ArrowRightOnRectangleIcon className="h-5 w-5" />
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Main content */}
      <div className="lg:pl-16 xl:pl-64">
        {/* Top bar with menu button and theme toggle */}
        <div className="sticky top-0 z-10 bg-white dark:bg-dark-100 shadow-sm dark:shadow-md">
          <div className="flex justify-between items-center px-4 sm:px-6 lg:px-8 py-2">
            <button
              onClick={() => setSidebarOpen(true)}
              className="p-1 text-gray-400 hover:text-gray-500 lg:hidden"
            >
              <Bars3Icon className="h-6 w-6" />
            </button>
            <div className="flex-1" />
            <ThemeToggle />
          </div>
        </div>
        <main className="py-2">
          <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.3 }}
            >
              {children}
            </motion.div>
          </div>
        </main>
      </div>
    </div>
  );
};

export default Layout;
