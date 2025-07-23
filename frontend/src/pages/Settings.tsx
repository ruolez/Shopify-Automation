import React, { useState, useEffect } from "react";
import { motion } from "framer-motion";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Switch } from "@headlessui/react";
import { Dialog } from "@headlessui/react";
import {
  ExclamationTriangleIcon,
  TrashIcon,
  PlusIcon,
  PencilIcon,
  SunIcon,
  MoonIcon,
  PlayIcon,
  ArrowPathIcon,
  CircleStackIcon,
} from "@heroicons/react/24/outline";
import toast from "react-hot-toast";
import api from "../utils/api";
import LoadingSpinner from "../components/LoadingSpinner";
import {
  formatDate,
  getCurrentTimeInTimezone,
  formatShortDate,
} from "../utils/dateFormat";
import { useTheme } from "../contexts/ThemeContext";

interface Settings {
  id: number;
  user_id: number;
  sync_frequency_minutes: number;
  auto_sync_enabled: boolean;
  fraud_sync_enabled: boolean;
  log_retention_days: number;
  sync_window_days: number;
  duplicate_detection_days: number;
  fraud_sync_days: number;
  reconciliation_batch_size: number;
  timezone: string;
  date_format: string;
  created_at: string;
  updated_at: string | null;
}

interface DataStats {
  order_logs: number;
  processed_orders: number;
  oos_incidents: number;
  fraud_analyses: number;
  archived_fraud_analyses: number;
  task_status: number;
}

interface ResetOptions {
  reset_order_logs: boolean;
  reset_processed_orders: boolean;
  reset_oos_incidents: boolean;
  reset_fraud_analyses: boolean;
  reset_archived_fraud_analyses: boolean;
  reset_task_status: boolean;
  confirmation: string;
}

interface ExcludedSKU {
  id: number;
  sku_pattern: string;
  description?: string;
  is_active: boolean;
  created_at: string;
  updated_at?: string;
}

interface TimezoneGroup {
  [groupName: string]: string[];
}

interface TimezoneData {
  groups: TimezoneGroup;
  all: string[];
}

interface DateFormat {
  format: string;
  description: string;
  example: string;
}

interface FraudSyncStatus {
  recent_analyses_count: number;
  total_analyses_count: number;
  active_fraud_rules_count: number;
  active_stores_count: number;
  is_processing: boolean;
  running_tasks: Array<{
    task_id: string;
    task_type: string;
    started_at: string;
    status: string;
  }>;
}

const TimezoneSelector: React.FC<{
  value: string;
  onChange: (timezone: string) => void;
}> = ({ value, onChange }) => {
  const { data: timezoneData } = useQuery<TimezoneData>({
    queryKey: ["timezones"],
    queryFn: async () => {
      const response = await api.get("/settings/timezones");
      return response.data;
    },
  });

  const currentTime = React.useMemo(() => {
    try {
      return getCurrentTimeInTimezone(value);
    } catch {
      return new Date();
    }
  }, [value]);

  return (
    <div>
      <label
        htmlFor="timezone"
        className="block text-sm font-medium text-gray-700 dark:text-dark-600"
      >
        Timezone
      </label>
      <p className="text-sm text-gray-500 dark:text-dark-400 mb-2">
        Select your preferred timezone for displaying dates and times
      </p>

      <div className="space-y-3">
        <select
          id="timezone"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="w-full rounded-md border-gray-300 dark:!border-gray-600 bg-white dark:bg-dark-100 text-gray-900 dark:text-dark-800 shadow-sm focus:outline-none focus:!ring-0 focus:!border-gray-300 dark:focus:!border-gray-600 sm:text-sm"
        >
          {timezoneData &&
            Object.entries(timezoneData.groups).map(
              ([groupName, timezones]) => (
                <optgroup key={groupName} label={groupName}>
                  {timezones.map((timezone) => (
                    <option key={timezone} value={timezone}>
                      {timezone.replace(/_/g, " ")}
                    </option>
                  ))}
                </optgroup>
              ),
            )}
        </select>

        <div className="text-sm text-gray-600 dark:text-dark-500 bg-gray-50 dark:bg-dark-200 p-3 rounded-md">
          <div className="font-medium text-gray-700 dark:text-dark-600">
            Current time in {value}:
          </div>
          <div className="text-lg font-mono text-gray-900 dark:text-dark-800">
            {formatDate(currentTime, {
              timezone: value,
              dateFormat: "EEEE, MMMM d, yyyy HH:mm:ss",
            })}
          </div>
        </div>
      </div>
    </div>
  );
};

const DateFormatSelector: React.FC<{
  value: string;
  onChange: (format: string) => void;
  timezone: string;
}> = ({ value, onChange, timezone }) => {
  const { data: dateFormats } = useQuery<DateFormat[]>({
    queryKey: ["date-formats"],
    queryFn: async () => {
      const response = await api.get("/settings/date-formats");
      return response.data;
    },
  });

  const previewTime = React.useMemo(() => {
    const now = new Date();
    return formatDate(now, { timezone, dateFormat: value });
  }, [timezone, value]);

  return (
    <div>
      <label
        htmlFor="date-format"
        className="block text-sm font-medium text-gray-700 dark:text-dark-600"
      >
        Date Format
      </label>
      <p className="text-sm text-gray-500 dark:text-dark-400 mb-2">
        Choose how dates and times should be displayed throughout the
        application
      </p>

      <div className="space-y-3">
        <select
          id="date-format"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="w-full rounded-md border-gray-300 dark:!border-gray-600 bg-white dark:bg-dark-100 text-gray-900 dark:text-dark-800 shadow-sm focus:outline-none focus:!ring-0 focus:!border-gray-300 dark:focus:!border-gray-600 sm:text-sm"
        >
          {dateFormats?.map((format) => (
            <option key={format.format} value={format.format}>
              {format.description} - {format.example}
            </option>
          ))}
        </select>

        <div className="text-sm text-gray-600 dark:text-dark-500 bg-gray-50 dark:bg-dark-200 p-3 rounded-md">
          <div className="font-medium text-gray-700 dark:text-dark-600">
            Preview with current format:
          </div>
          <div className="text-lg font-mono text-gray-900 dark:text-dark-800">
            {previewTime}
          </div>
        </div>
      </div>
    </div>
  );
};

const ThemeToggle: React.FC = () => {
  const { theme, toggleTheme, setTheme } = useTheme();

  return (
    <div className="space-y-4">
      <div>
        <label className="block text-sm font-medium text-gray-700 dark:text-dark-600 mb-3">
          Theme Preference
        </label>
        <p className="text-sm text-gray-500 dark:text-dark-400 mb-4">
          Choose your preferred color scheme for the application interface.
        </p>

        <div className="grid grid-cols-3 gap-3">
          {/* Light Mode */}
          <button
            onClick={() => setTheme("light")}
            className={`relative flex flex-col items-center p-4 rounded-lg border-2 transition-all duration-200 ${
              theme === "light"
                ? "border-shopify-500 bg-shopify-50 dark:bg-shopify-900/20"
                : "border-gray-200 dark:border-dark-300 hover:border-gray-300 dark:hover:border-dark-400"
            }`}
          >
            <SunIcon className="h-6 w-6 text-yellow-500 mb-2" />
            <span className="text-sm font-medium text-gray-900 dark:text-dark-800">
              Light
            </span>
            <span className="text-xs text-gray-500 dark:text-dark-400">
              Always light theme
            </span>
            {theme === "light" && (
              <div className="absolute top-2 right-2">
                <div className="h-2 w-2 bg-shopify-500 rounded-full"></div>
              </div>
            )}
          </button>

          {/* Dark Mode */}
          <button
            onClick={() => setTheme("dark")}
            className={`relative flex flex-col items-center p-4 rounded-lg border-2 transition-all duration-200 ${
              theme === "dark"
                ? "border-shopify-500 bg-shopify-50 dark:bg-shopify-900/20"
                : "border-gray-200 dark:border-dark-300 hover:border-gray-300 dark:hover:border-dark-400"
            }`}
          >
            <MoonIcon className="h-6 w-6 text-blue-500 mb-2" />
            <span className="text-sm font-medium text-gray-900 dark:text-dark-800">
              Dark
            </span>
            <span className="text-xs text-gray-500 dark:text-dark-400">
              Always dark theme
            </span>
            {theme === "dark" && (
              <div className="absolute top-2 right-2">
                <div className="h-2 w-2 bg-shopify-500 rounded-full"></div>
              </div>
            )}
          </button>

          {/* System Mode */}
          <button
            onClick={() => {
              localStorage.removeItem("theme");
              const systemPrefersDark = window.matchMedia(
                "(prefers-color-scheme: dark)",
              ).matches;
              setTheme(systemPrefersDark ? "dark" : "light");
            }}
            className={`relative flex flex-col items-center p-4 rounded-lg border-2 transition-all duration-200 ${
              !localStorage.getItem("theme")
                ? "border-shopify-500 bg-shopify-50 dark:bg-shopify-900/20"
                : "border-gray-200 dark:border-dark-300 hover:border-gray-300 dark:hover:border-dark-400"
            }`}
          >
            <div className="h-6 w-6 mb-2 flex">
              <SunIcon className="h-3 w-3 text-yellow-500" />
              <MoonIcon className="h-3 w-3 text-blue-500" />
            </div>
            <span className="text-sm font-medium text-gray-900 dark:text-dark-800">
              System
            </span>
            <span className="text-xs text-gray-500 dark:text-dark-400">
              Follow system setting
            </span>
            {!localStorage.getItem("theme") && (
              <div className="absolute top-2 right-2">
                <div className="h-2 w-2 bg-shopify-500 rounded-full"></div>
              </div>
            )}
          </button>
        </div>
      </div>

      {/* Quick Toggle Switch */}
      <div className="flex items-center justify-between p-4 bg-gray-50 dark:bg-dark-200 rounded-lg">
        <div className="flex items-center space-x-3">
          <SunIcon className="h-5 w-5 text-yellow-500" />
          <span className="text-sm font-medium text-gray-700 dark:text-dark-600">
            Quick Toggle
          </span>
          <MoonIcon className="h-5 w-5 text-blue-500" />
        </div>
        <button
          onClick={toggleTheme}
          className="relative inline-flex h-6 w-11 items-center rounded-full bg-gray-200 dark:bg-dark-300 transition-colors focus:outline-none"
        >
          <span
            className={`${
              theme === "dark" ? "translate-x-6" : "translate-x-1"
            } inline-block h-4 w-4 transform rounded-full bg-white transition-transform`}
          />
        </button>
      </div>
    </div>
  );
};

const ExcludedSKUsSection: React.FC<{ timezone?: string }> = ({
  timezone = "UTC",
}) => {
  const queryClient = useQueryClient();
  const [showAddModal, setShowAddModal] = useState(false);
  const [editingSku, setEditingSku] = useState<ExcludedSKU | null>(null);
  const [formData, setFormData] = useState({
    sku_pattern: "",
    description: "",
  });

  const { data: excludedSkus, isLoading } = useQuery<ExcludedSKU[]>({
    queryKey: ["excluded-skus"],
    queryFn: async () => {
      const response = await api.get("/settings/excluded-skus");
      return response.data;
    },
  });

  const createMutation = useMutation({
    mutationFn: async (data: { sku_pattern: string; description?: string }) => {
      const response = await api.post("/settings/excluded-skus", data);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["excluded-skus"] });
      toast.success("Excluded SKU added successfully");
      setShowAddModal(false);
      setFormData({ sku_pattern: "", description: "" });
    },
    onError: (error: any) => {
      toast.error(error.response?.data?.detail || "Failed to add excluded SKU");
    },
  });

  const updateMutation = useMutation({
    mutationFn: async ({
      id,
      data,
    }: {
      id: number;
      data: Partial<ExcludedSKU>;
    }) => {
      const response = await api.put(`/settings/excluded-skus/${id}`, data);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["excluded-skus"] });
      toast.success("Excluded SKU updated successfully");
      setEditingSku(null);
    },
    onError: (error: any) => {
      toast.error(
        error.response?.data?.detail || "Failed to update excluded SKU",
      );
    },
  });

  const deleteMutation = useMutation({
    mutationFn: async (id: number) => {
      await api.delete(`/settings/excluded-skus/${id}`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["excluded-skus"] });
      toast.success("Excluded SKU deleted successfully");
    },
    onError: (error: any) => {
      toast.error(
        error.response?.data?.detail || "Failed to delete excluded SKU",
      );
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!formData.sku_pattern.trim()) {
      toast.error("SKU pattern is required");
      return;
    }

    if (editingSku) {
      updateMutation.mutate({
        id: editingSku.id,
        data: {
          sku_pattern: formData.sku_pattern,
          description: formData.description || undefined,
        },
      });
    } else {
      createMutation.mutate({
        sku_pattern: formData.sku_pattern,
        description: formData.description || undefined,
      });
    }
  };

  const startEdit = (sku: ExcludedSKU) => {
    setEditingSku(sku);
    setFormData({
      sku_pattern: sku.sku_pattern,
      description: sku.description || "",
    });
    setShowAddModal(true);
  };

  const cancelEdit = () => {
    setEditingSku(null);
    setFormData({ sku_pattern: "", description: "" });
    setShowAddModal(false);
  };

  const toggleActive = (sku: ExcludedSKU) => {
    updateMutation.mutate({
      id: sku.id,
      data: { is_active: !sku.is_active },
    });
  };

  return (
    <>
      <div className="bg-white dark:bg-dark-100 shadow rounded-lg">
        <div className="px-4 py-5 sm:p-6">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="text-lg font-medium leading-6 text-gray-900 dark:text-dark-800">
                Excluded SKUs
              </h3>
              <p className="mt-1 text-sm text-gray-500">
                SKU patterns to exclude from weight calculations and OOS
                reporting. These products will still be moved during fulfillment
                location changes.
              </p>
            </div>
            <button
              onClick={() => setShowAddModal(true)}
              className="inline-flex items-center px-3 py-2 border border-transparent text-sm leading-4 font-medium rounded-md text-white bg-shopify-600 hover:bg-shopify-700 focus:outline-none"
            >
              <PlusIcon className="h-4 w-4 mr-2" />
              Add SKU Pattern
            </button>
          </div>

          {isLoading ? (
            <div className="flex justify-center py-8">
              <LoadingSpinner size="md" />
            </div>
          ) : excludedSkus && excludedSkus.length > 0 ? (
            <div className="space-y-3">
              {excludedSkus.map((sku) => (
                <div
                  key={sku.id}
                  className="flex items-center justify-between p-4 border border-gray-200 dark:border-dark-200 rounded-lg"
                >
                  <div className="flex-1">
                    <div className="flex items-center space-x-3">
                      <code className="px-2 py-1 bg-gray-100 dark:bg-dark-200 rounded text-sm font-mono text-gray-900 dark:text-dark-800">
                        {sku.sku_pattern}
                      </code>
                      <span
                        className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                          sku.is_active
                            ? "bg-green-100 text-green-800 dark:bg-green-900/20 dark:text-green-400"
                            : "bg-red-100 text-red-800 dark:bg-red-900/20 dark:text-red-400"
                        }`}
                      >
                        {sku.is_active ? "Active" : "Inactive"}
                      </span>
                    </div>
                    {sku.description && (
                      <p className="mt-1 text-sm text-gray-600 dark:text-dark-500">
                        {sku.description}
                      </p>
                    )}
                    <p className="mt-1 text-xs text-gray-400 dark:text-dark-300">
                      Created: {formatShortDate(sku.created_at, timezone)}
                    </p>
                  </div>
                  <div className="flex items-center space-x-2">
                    <Switch
                      checked={sku.is_active}
                      onChange={() => toggleActive(sku)}
                      className={`${
                        sku.is_active ? "bg-shopify-600" : "bg-gray-200"
                      } relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none`}
                    >
                      <span className="sr-only">Toggle active status</span>
                      <span
                        className={`${
                          sku.is_active ? "translate-x-6" : "translate-x-1"
                        } inline-block h-4 w-4 transform rounded-full bg-white transition-transform`}
                      />
                    </Switch>
                    <button
                      onClick={() => startEdit(sku)}
                      className="p-2 text-gray-600 hover:bg-gray-50 dark:text-dark-500 dark:hover:bg-dark-200 rounded-lg transition-colors"
                      title="Edit SKU pattern"
                    >
                      <PencilIcon className="h-4 w-4" />
                    </button>
                    <button
                      onClick={() => {
                        if (
                          window.confirm(
                            "Are you sure you want to delete this SKU pattern?",
                          )
                        ) {
                          deleteMutation.mutate(sku.id);
                        }
                      }}
                      className="p-2 text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-lg transition-colors"
                      title="Delete SKU pattern"
                    >
                      <TrashIcon className="h-4 w-4" />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-center py-8 text-gray-500 dark:text-dark-400">
              <p>No excluded SKU patterns configured.</p>
              <p className="text-sm">
                Add patterns to exclude specific products from weight
                calculations and OOS reporting.
              </p>
            </div>
          )}
        </div>
      </div>

      {/* Add/Edit Modal */}
      <Dialog
        open={showAddModal}
        onClose={cancelEdit}
        className="fixed inset-0 z-50 overflow-y-auto"
      >
        <div className="flex items-center justify-center min-h-screen pt-4 px-4 pb-20 text-center sm:block sm:p-0">
          <Dialog.Overlay className="modal-overlay" />

          <div className="modal-content inline-block align-bottom rounded-lg px-4 pt-5 pb-4 text-left overflow-hidden shadow-xl transform transition-all sm:my-8 sm:align-middle sm:max-w-lg sm:w-full sm:p-6">
            <div>
              <div className="mt-3 text-center sm:mt-0 sm:text-left">
                <Dialog.Title
                  as="h3"
                  className="text-lg leading-6 font-medium text-gray-900 dark:text-dark-800"
                >
                  {editingSku ? "Edit" : "Add"} Excluded SKU Pattern
                </Dialog.Title>
                <div className="mt-4">
                  <form onSubmit={handleSubmit} className="space-y-4">
                    <div>
                      <label
                        htmlFor="sku_pattern"
                        className="block text-sm font-medium text-gray-700"
                      >
                        SKU Pattern
                      </label>
                      <input
                        type="text"
                        id="sku_pattern"
                        value={formData.sku_pattern}
                        onChange={(e) =>
                          setFormData({
                            ...formData,
                            sku_pattern: e.target.value,
                          })
                        }
                        placeholder="e.g., SAMPLE, TEST-, _EXCLUDED"
                        className="mt-1 block w-full rounded-md border-gray-300 dark:!border-gray-600 bg-white dark:bg-dark-100 text-gray-900 dark:text-dark-800 shadow-sm focus:outline-none focus:!ring-0 focus:!border-gray-300 dark:focus:!border-gray-600 sm:text-sm"
                        required
                      />
                      <p className="mt-1 text-xs text-gray-500">
                        Products with SKUs containing this text will be excluded
                        (case-insensitive)
                      </p>
                    </div>
                    <div>
                      <label
                        htmlFor="description"
                        className="block text-sm font-medium text-gray-700"
                      >
                        Description (optional)
                      </label>
                      <textarea
                        id="description"
                        value={formData.description}
                        onChange={(e) =>
                          setFormData({
                            ...formData,
                            description: e.target.value,
                          })
                        }
                        placeholder="Why is this SKU pattern excluded?"
                        rows={3}
                        className="mt-1 block w-full rounded-md border-gray-300 dark:!border-gray-600 bg-white dark:bg-dark-100 text-gray-900 dark:text-dark-800 shadow-sm focus:outline-none focus:!ring-0 focus:!border-gray-300 dark:focus:!border-gray-600 sm:text-sm"
                      />
                    </div>
                  </form>
                </div>
              </div>
            </div>
            <div className="mt-5 sm:mt-4 sm:flex sm:flex-row-reverse">
              <button
                type="submit"
                onClick={handleSubmit}
                disabled={createMutation.isPending || updateMutation.isPending}
                className="w-full inline-flex justify-center rounded-md border border-transparent shadow-sm px-4 py-2 bg-shopify-600 text-base font-medium text-white hover:bg-shopify-700 focus:outline-none sm:ml-3 sm:w-auto sm:text-sm disabled:opacity-50"
              >
                {createMutation.isPending || updateMutation.isPending ? (
                  <>
                    <LoadingSpinner size="sm" className="mr-2" />
                    {editingSku ? "Updating..." : "Adding..."}
                  </>
                ) : editingSku ? (
                  "Update"
                ) : (
                  "Add"
                )}
              </button>
              <button
                type="button"
                onClick={cancelEdit}
                className="mt-3 w-full inline-flex justify-center rounded-md border border-gray-300 dark:border-dark-300 shadow-sm px-4 py-2 bg-white dark:bg-dark-100 text-base font-medium text-gray-700 dark:text-dark-600 hover:bg-gray-50 dark:hover:bg-dark-200 focus:outline-none sm:mt-0 sm:w-auto sm:text-sm"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      </Dialog>
    </>
  );
};

const DatabaseCompaction: React.FC = () => {
  const [isCompacting, setIsCompacting] = useState(false);
  const queryClient = useQueryClient();

  const { data: dbStats, isLoading, refetch } = useQuery({
    queryKey: ["database-stats"],
    queryFn: async () => {
      const response = await api.get("/settings/database-stats");
      return response.data;
    },
  });

  const compactMutation = useMutation({
    mutationFn: async () => {
      const response = await api.post("/settings/compact-database");
      return response.data;
    },
    onMutate: () => {
      setIsCompacting(true);
    },
    onSuccess: (data) => {
      toast.success(
        `Database compacted successfully! Saved ${data.space_saved_mb} MB (${data.space_saved_percent}%)`,
        { duration: 5000 }
      );
      refetch();
      queryClient.invalidateQueries({ queryKey: ["database-stats"] });
    },
    onError: (error: any) => {
      toast.error(
        error.response?.data?.detail || "Failed to compact database"
      );
    },
    onSettled: () => {
      setIsCompacting(false);
    },
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-4">
        <LoadingSpinner size="sm" />
      </div>
    );
  }

  if (!dbStats) {
    return (
      <div className="text-sm text-gray-500 dark:text-dark-400">
        Unable to load database statistics
      </div>
    );
  }

  const getFragmentationColor = (percent: number) => {
    if (percent < 10) return "text-green-600 dark:text-green-400";
    if (percent < 30) return "text-yellow-600 dark:text-yellow-400";
    return "text-red-600 dark:text-red-400";
  };

  const getFragmentationBgColor = (percent: number) => {
    if (percent < 10) return "bg-green-100 dark:bg-green-900/20";
    if (percent < 30) return "bg-yellow-100 dark:bg-yellow-900/20";
    return "bg-red-100 dark:bg-red-900/20";
  };

  return (
    <div className="space-y-4">
      <p className="text-sm text-gray-500 dark:text-dark-400">
        Reclaim unused space and optimize database performance by compacting.
      </p>

      {/* Database Statistics */}
      <div className="bg-gray-50 dark:bg-dark-200 rounded-lg p-4 space-y-3">
        <div className="flex items-center space-x-2 mb-3">
          <CircleStackIcon className="h-5 w-5 text-gray-600 dark:text-dark-500" />
          <h5 className="text-sm font-medium text-gray-900 dark:text-dark-800">
            Database Statistics
          </h5>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <div className="text-xs text-gray-500 dark:text-dark-400">
              Total Size
            </div>
            <div className="text-lg font-semibold text-gray-900 dark:text-dark-800">
              {dbStats.file_size_mb} MB
            </div>
          </div>
          <div>
            <div className="text-xs text-gray-500 dark:text-dark-400">
              Used Space
            </div>
            <div className="text-lg font-semibold text-gray-900 dark:text-dark-800">
              {dbStats.used_size_mb} MB
            </div>
          </div>
          <div>
            <div className="text-xs text-gray-500 dark:text-dark-400">
              Free Space
            </div>
            <div className="text-lg font-semibold text-gray-600 dark:text-dark-500">
              {dbStats.free_size_mb} MB
            </div>
          </div>
          <div>
            <div className="text-xs text-gray-500 dark:text-dark-400">
              Fragmentation
            </div>
            <div
              className={`text-lg font-semibold ${getFragmentationColor(
                dbStats.fragmentation_percent
              )}`}
            >
              {dbStats.fragmentation_percent}%
            </div>
          </div>
        </div>

        {/* Fragmentation indicator */}
        {dbStats.fragmentation_percent > 10 && (
          <div
            className={`mt-3 px-3 py-2 rounded-md text-sm ${getFragmentationBgColor(
              dbStats.fragmentation_percent
            )}`}
          >
            <p className={`font-medium ${getFragmentationColor(
              dbStats.fragmentation_percent
            )}`}>
              {dbStats.fragmentation_percent > 30
                ? "High fragmentation detected!"
                : "Moderate fragmentation detected."}
            </p>
            <p className="text-xs mt-1 text-gray-600 dark:text-dark-500">
              {dbStats.fragmentation_percent > 30
                ? "Compacting is highly recommended to reclaim space."
                : "Consider compacting to optimize performance."}
            </p>
          </div>
        )}
      </div>

      {/* Compact Button */}
      <div className="flex items-center justify-between">
        <div className="text-sm text-gray-500 dark:text-dark-400">
          {dbStats.can_compact ? (
            <>
              <span className="font-medium">{dbStats.free_size_mb} MB</span> can be
              reclaimed
            </>
          ) : (
            "Database is already optimized"
          )}
        </div>
        <button
          onClick={() => compactMutation.mutate()}
          disabled={!dbStats.can_compact || isCompacting}
          className={`inline-flex items-center px-4 py-2 text-sm font-medium rounded-md transition-colors ${
            dbStats.can_compact && !isCompacting
              ? "text-white bg-shopify-600 hover:bg-shopify-700"
              : "text-gray-400 dark:text-dark-400 bg-gray-200 dark:bg-dark-300 cursor-not-allowed"
          }`}
        >
          {isCompacting ? (
            <>
              <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white mr-2" />
              Compacting...
            </>
          ) : (
            <>
              <CircleStackIcon className="h-4 w-4 mr-2" />
              Compact Database
            </>
          )}
        </button>
      </div>
    </div>
  );
};

const Settings: React.FC = () => {
  const queryClient = useQueryClient();
  const [showResetModal, setShowResetModal] = useState(false);
  const [resetOptions, setResetOptions] = useState<ResetOptions>({
    reset_order_logs: true,
    reset_processed_orders: true,
    reset_oos_incidents: true,
    reset_fraud_analyses: true,
    reset_archived_fraud_analyses: false,
    reset_task_status: false,
    confirmation: "",
  });
  const [fraudSyncDays, setFraudSyncDays] = useState<number>(7);

  const { data: settings, isLoading } = useQuery<Settings>({
    queryKey: ["settings"],
    queryFn: async () => {
      const response = await api.get("/settings");
      return response.data;
    },
  });

  // Initialize fraudSyncDays from settings when they load
  useEffect(() => {
    if (settings?.fraud_sync_days) {
      setFraudSyncDays(settings.fraud_sync_days);
    }
  }, [settings]);

  const { data: dataStats } = useQuery<DataStats>({
    queryKey: ["data-stats"],
    queryFn: async () => {
      const response = await api.get("/settings/data-stats");
      return response.data;
    },
    enabled: showResetModal,
  });

  const { data: fraudSyncStatus, refetch: refetchFraudStatus } = useQuery<FraudSyncStatus>({
    queryKey: ["fraud-sync-status"],
    queryFn: async () => {
      const response = await api.get("/settings/fraud-sync-status");
      console.log("Fraud sync status:", response.data);
      
      // Check for stale tasks (older than 5 minutes)
      if (response.data.is_processing && response.data.running_tasks?.length > 0) {
        const now = new Date().getTime();
        const hasStaleTask = response.data.running_tasks.some((task: any) => {
          const taskStartTime = new Date(task.started_at).getTime();
          const taskAge = now - taskStartTime;
          return taskAge > 5 * 60 * 1000; // 5 minutes in milliseconds
        });
        
        if (hasStaleTask) {
          console.log("Detected stale task - treating as not processing");
          response.data.is_processing = false;
        }
      }
      
      return response.data;
    },
    refetchInterval: (query) => {
      // Use the query data to check if processing
      return query.state.data?.is_processing ? 2000 : false;
    },
    staleTime: 0, // Always fetch fresh data
    refetchOnWindowFocus: true, // Refetch when window regains focus
  });

  const updateSettings = useMutation({
    mutationFn: async (data: Partial<Settings>) => {
      const response = await api.put("/settings", data);
      return response.data;
    },
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ["settings"] });
      // Invalidate all queries that might use settings data
      queryClient.invalidateQueries({ queryKey: ["fraud-analyses"] });
      queryClient.invalidateQueries({ queryKey: ["fraud-rule-schema"] });

      // Trigger localStorage event for cross-window updates
      localStorage.setItem("user-settings-updated", Date.now().toString());

      // Trigger custom event for same-window updates (storage events don't fire in same window)
      window.dispatchEvent(
        new CustomEvent("settings-updated", {
          detail: {
            timezone: variables.timezone,
            dateFormat: variables.date_format,
          },
        }),
      );

      toast.success("Settings updated successfully");

      // Debug logging
      if (variables.timezone) {
        console.log("Timezone updated to:", variables.timezone);
      }
      if (variables.date_format) {
        console.log("Date format updated to:", variables.date_format);
      }
    },
    onError: () => {
      toast.error("Failed to update settings");
    },
  });

  const syncAllStores = useMutation({
    mutationFn: async () => {
      const response = await api.post("/sync/all");
      return response.data;
    },
    onSuccess: () => {
      toast.success("Sync started for all stores");
    },
    onError: () => {
      toast.error("Failed to start sync");
    },
  });

  const resetData = useMutation({
    mutationFn: async (options: ResetOptions) => {
      const response = await api.post("/settings/reset-data", options);
      return response.data;
    },
    onSuccess: () => {
      toast.success("Data reset completed successfully");
      setShowResetModal(false);
      setResetOptions({
        reset_order_logs: true,
        reset_processed_orders: true,
        reset_oos_incidents: true,
        reset_fraud_analyses: true,
        reset_archived_fraud_analyses: false,
        reset_task_status: false,
        confirmation: "",
      });
      // Invalidate queries that might have been affected
      queryClient.invalidateQueries({ queryKey: ["order-logs"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard-stats"] });
      queryClient.invalidateQueries({ queryKey: ["reports"] });
    },
    onError: (error: any) => {
      toast.error(error.response?.data?.detail || "Failed to reset data");
    },
  });

  const triggerFraudAnalysis = useMutation({
    mutationFn: async (daysBack: number) => {
      const response = await api.post(`/settings/trigger-fraud-analysis?days_back=${daysBack}`);
      return response.data;
    },
    onSuccess: (data) => {
      toast.success(data.message);
      refetchFraudStatus();
      
      // Keep polling for longer to handle backend delays
      let pollCount = 0;
      const maxPolls = 150; // Poll for up to 5 minutes (150 * 2 seconds)
      const taskStartTime = new Date().getTime();
      
      const pollInterval = setInterval(async () => {
        const result = await refetchFraudStatus();
        pollCount++;
        
        const now = new Date().getTime();
        const elapsed = now - taskStartTime;
        
        // Stop polling if:
        // 1. Max polls reached
        // 2. Processing is done
        // 3. Task has been running for more than 5 minutes (likely stuck)
        if (pollCount >= maxPolls || 
            !result.data?.is_processing || 
            elapsed > 5 * 60 * 1000) {
          clearInterval(pollInterval);
          
          // Force a final refetch after a delay
          setTimeout(() => refetchFraudStatus(), 2000);
          
          // If task was stuck, show a warning
          if (elapsed > 5 * 60 * 1000 && result.data?.is_processing) {
            toast("Fraud analysis task may have timed out. Please check the results.", {
              icon: '⚠️',
            });
          }
        }
      }, 2000);
    },
    onError: (error: any) => {
      toast.error(error.response?.data?.detail || "Failed to trigger fraud analysis");
    },
  });

  const reprocessFraudRules = useMutation({
    mutationFn: async (daysBack: number) => {
      const response = await api.post(`/settings/reprocess-fraud-rules?days_back=${daysBack}`);
      return response.data;
    },
    onSuccess: (data) => {
      toast.success(data.message);
      refetchFraudStatus();
      
      // Keep polling for longer to handle backend delays
      let pollCount = 0;
      const maxPolls = 150; // Poll for up to 5 minutes (150 * 2 seconds)
      const taskStartTime = new Date().getTime();
      
      const pollInterval = setInterval(async () => {
        const result = await refetchFraudStatus();
        pollCount++;
        
        const now = new Date().getTime();
        const elapsed = now - taskStartTime;
        
        // Stop polling if:
        // 1. Max polls reached
        // 2. Processing is done
        // 3. Task has been running for more than 5 minutes (likely stuck)
        if (pollCount >= maxPolls || 
            !result.data?.is_processing || 
            elapsed > 5 * 60 * 1000) {
          clearInterval(pollInterval);
          
          // Force a final refetch after a delay
          setTimeout(() => refetchFraudStatus(), 2000);
          
          // If task was stuck, show a warning
          if (elapsed > 5 * 60 * 1000 && result.data?.is_processing) {
            toast("Fraud rule reprocessing may have timed out. Please check the results.", {
              icon: '⚠️',
            });
          }
        }
      }, 2000);
    },
    onError: (error: any) => {
      toast.error(error.response?.data?.detail || "Failed to reprocess fraud rules");
    },
  });

  if (isLoading) {
    return (
      <div className="flex justify-center items-center h-64">
        <LoadingSpinner size="lg" />
      </div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className="space-y-6"
    >
      {/* Order Processing & Sync Settings */}
      <div className="bg-white dark:bg-dark-100 shadow rounded-lg">
        <div className="px-4 py-5 sm:p-6">
          <h3 className="text-lg font-medium leading-6 text-gray-900 dark:text-dark-800">
            Order Processing & Synchronization
          </h3>
          <p className="mt-1 text-sm text-gray-500">
            Configure how orders are synchronized and processed across your stores.
          </p>

          <div className="mt-6 space-y-6">
            {/* Auto-sync toggle */}
            <div className="flex items-center justify-between">
              <div>
                <label
                  htmlFor="auto-sync"
                  className="text-sm font-medium text-gray-700 dark:text-dark-600"
                >
                  Automatic Order Processing
                </label>
                <p className="text-sm text-gray-500 dark:text-dark-400">
                  Automatically process orders based on your rules
                </p>
              </div>
              <Switch
                checked={settings?.auto_sync_enabled || false}
                onChange={(enabled) =>
                  updateSettings.mutate({ auto_sync_enabled: enabled })
                }
                className={`${
                  settings?.auto_sync_enabled ? "bg-shopify-600" : "bg-gray-200"
                } relative inline-flex h-6 w-11 items-center rounded-full transition-colors`}
              >
                <span
                  className={`${
                    settings?.auto_sync_enabled
                      ? "translate-x-6"
                      : "translate-x-1"
                  } inline-block h-4 w-4 transform rounded-full bg-white transition-transform`}
                />
              </Switch>
            </div>

            {/* Sync frequency */}
            <div>
              <label
                htmlFor="sync-frequency"
                className="block text-sm font-medium text-gray-700"
              >
                Sync Frequency (minutes)
              </label>
              <p className="text-sm text-gray-500 dark:text-dark-400 mb-2">
                How often to check for new orders when auto-sync is enabled
              </p>
              <select
                id="sync-frequency"
                value={settings?.sync_frequency_minutes || 10}
                onChange={(e) =>
                  updateSettings.mutate({
                    sync_frequency_minutes: parseInt(e.target.value),
                  })
                }
                className="mt-1 block w-full rounded-md border-gray-300 dark:!border-gray-600 bg-white dark:bg-dark-100 text-gray-900 dark:text-dark-800 shadow-sm focus:outline-none focus:!ring-0 focus:!border-gray-300 dark:focus:!border-gray-600 sm:text-sm"
              >
                <option value={1}>Every 1 minute</option>
                <option value={2}>Every 2 minutes</option>
                <option value={3}>Every 3 minutes</option>
                <option value={5}>Every 5 minutes</option>
                <option value={10}>Every 10 minutes</option>
                <option value={15}>Every 15 minutes</option>
                <option value={30}>Every 30 minutes</option>
                <option value={60}>Every hour</option>
                <option value={120}>Every 2 hours</option>
              </select>
            </div>

            {/* Sync window */}
            <div>
              <label
                htmlFor="sync-window"
                className="block text-sm font-medium text-gray-700 dark:text-dark-600"
              >
                Order Sync Window (days)
              </label>
              <p className="text-sm text-gray-500 dark:text-dark-400 mb-2">
                How many days back to fetch orders during manual sync (affects
                missing order recovery)
              </p>
              <input
                id="sync-window"
                type="number"
                min="1"
                max="365"
                value={settings?.sync_window_days || 7}
                onChange={(e) =>
                  updateSettings.mutate({
                    sync_window_days: parseInt(e.target.value),
                  })
                }
                className="mt-1 block w-full rounded-md border-gray-300 dark:!border-gray-600 bg-white dark:bg-dark-100 text-gray-900 dark:text-dark-800 shadow-sm focus:outline-none focus:!ring-0 focus:!border-gray-300 dark:focus:!border-gray-600 sm:text-sm"
                placeholder="7"
              />
              <p className="text-xs text-gray-400 dark:text-dark-300 mt-1">
                Set to 1 for recent orders only, or higher values (7-30) to
                recover older orders
              </p>
            </div>

            {/* Manual sync button */}
            <div className="border-t pt-6">
              <h4 className="text-sm font-medium text-gray-700 dark:text-dark-600 mb-3">
                Manual Sync
              </h4>
              <button
                onClick={() => syncAllStores.mutate()}
                disabled={syncAllStores.isPending}
                className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md shadow-sm text-white bg-shopify-600 hover:bg-shopify-700 focus:outline-none disabled:opacity-50"
              >
                {syncAllStores.isPending ? (
                  <>
                    <LoadingSpinner size="sm" className="mr-2" />
                    Syncing...
                  </>
                ) : (
                  "Sync All Active Stores Now"
                )}
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Fraud Detection Settings */}
      <div className="bg-white dark:bg-dark-100 shadow rounded-lg">
        <div className="px-4 py-5 sm:p-6">
          <h3 className="text-lg font-medium leading-6 text-gray-900 dark:text-dark-800">
            Fraud Detection
          </h3>
          <p className="mt-1 text-sm text-gray-500">
            Configure fraud detection settings and manage fraud analysis.
          </p>

          <div className="mt-6 space-y-6">
            {/* Fraud sync toggle */}
            <div className="flex items-center justify-between">
              <div className="flex-1">
                <label
                  htmlFor="fraud-sync"
                  className="text-sm font-medium text-gray-700 dark:text-dark-600"
                >
                  Automatic Fraud Detection
                </label>
                <p className="text-sm text-gray-500 dark:text-dark-400">
                  Automatically analyze orders for fraud indicators
                </p>
              </div>
              <Switch
                checked={settings?.fraud_sync_enabled || false}
                onChange={(enabled) =>
                  updateSettings.mutate({ fraud_sync_enabled: enabled })
                }
                className={`${
                  settings?.fraud_sync_enabled ? "bg-shopify-600" : "bg-gray-200"
                } relative inline-flex h-6 w-11 items-center rounded-full transition-colors`}
              >
                <span
                  className={`${
                    settings?.fraud_sync_enabled
                      ? "translate-x-6"
                      : "translate-x-1"
                  } inline-block h-4 w-4 transform rounded-full bg-white transition-transform`}
                />
              </Switch>
            </div>

            {/* Duplicate detection days */}
            <div>
              <label
                htmlFor="duplicate-detection"
                className="block text-sm font-medium text-gray-700 dark:text-dark-600"
              >
                Duplicate Detection Period (days)
              </label>
              <p className="text-sm text-gray-500 dark:text-dark-400 mb-2">
                How many days to check for duplicate orders in fraud detection
              </p>
              <input
                id="duplicate-detection"
                type="number"
                min="1"
                max="365"
                value={settings?.duplicate_detection_days || 7}
                onChange={(e) =>
                  updateSettings.mutate({
                    duplicate_detection_days: parseInt(e.target.value),
                  })
                }
                className="mt-1 block w-full rounded-md border-gray-300 dark:!border-gray-600 bg-white dark:bg-dark-100 text-gray-900 dark:text-dark-800 shadow-sm focus:outline-none focus:!ring-0 focus:!border-gray-300 dark:focus:!border-gray-600 sm:text-sm"
                placeholder="7"
              />
              <p className="text-xs text-gray-400 dark:text-dark-300 mt-1">
                Set to 7 for weekly checks, or adjust based on your business needs (1-365 days)
              </p>
            </div>

            {/* Reconciliation batch size */}
            <div>
              <label
                htmlFor="reconciliation-batch"
                className="block text-sm font-medium text-gray-700 dark:text-dark-600"
              >
                Reconciliation Batch Size
              </label>
              <p className="text-sm text-gray-500 dark:text-dark-400 mb-2">
                Number of fraud analyses to process per reconciliation run
              </p>
              <select
                id="reconciliation-batch"
                value={settings?.reconciliation_batch_size || 500}
                onChange={(e) =>
                  updateSettings.mutate({
                    reconciliation_batch_size: parseInt(e.target.value),
                  })
                }
                className="mt-1 block w-full rounded-md border-gray-300 dark:!border-gray-600 bg-white dark:bg-dark-100 text-gray-900 dark:text-dark-800 shadow-sm focus:outline-none focus:!ring-0 focus:!border-gray-300 dark:focus:!border-gray-600 sm:text-sm"
              >
                <option value={100}>100 orders (fast)</option>
                <option value={250}>250 orders</option>
                <option value={500}>500 orders (default)</option>
                <option value={750}>750 orders</option>
                <option value={1000}>1000 orders</option>
                <option value={1500}>1500 orders</option>
                <option value={2000}>2000 orders (maximum)</option>
              </select>
              <p className="text-xs text-gray-400 dark:text-dark-300 mt-1">
                Larger batches process more orders but may take longer. Adjust based on your database size.
              </p>
            </div>

            {/* Manual fraud management */}
            <div className="border-t pt-6">
              <h4 className="text-sm font-medium text-gray-700 dark:text-dark-600 mb-3">
                Manual Fraud Management
              </h4>
              
              {/* Status Display */}
              {fraudSyncStatus && (
                <div className="mb-5 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
                  <div className="bg-gray-50 dark:bg-dark-200 px-4 py-3 rounded-lg">
                    <div className="text-sm font-medium text-gray-500 dark:text-dark-600">
                      Recent Analyses
                    </div>
                    <div className="text-lg font-bold text-gray-900 dark:text-dark-800">
                      {fraudSyncStatus.recent_analyses_count}
                    </div>
                  </div>
                  <div className="bg-gray-50 dark:bg-dark-200 px-4 py-3 rounded-lg">
                    <div className="text-sm font-medium text-gray-500 dark:text-dark-600">
                      Total Analyses
                    </div>
                    <div className="text-lg font-bold text-gray-900 dark:text-dark-800">
                      {fraudSyncStatus.total_analyses_count}
                    </div>
                  </div>
                  <div className="bg-gray-50 dark:bg-dark-200 px-4 py-3 rounded-lg">
                    <div className="text-sm font-medium text-gray-500 dark:text-dark-600">
                      Active Rules
                    </div>
                    <div className="text-lg font-bold text-gray-900 dark:text-dark-800">
                      {fraudSyncStatus.active_fraud_rules_count}
                    </div>
                  </div>
                  <div className="bg-gray-50 dark:bg-dark-200 px-4 py-3 rounded-lg">
                    <div className="text-sm font-medium text-gray-500 dark:text-dark-600">
                      Active Stores
                    </div>
                    <div className="text-lg font-bold text-gray-900 dark:text-dark-800">
                      {fraudSyncStatus.active_stores_count}
                    </div>
                  </div>
                </div>
              )}

              {/* Processing Status */}
              {fraudSyncStatus?.is_processing && (
                <div className="mb-4 bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg p-4">
                  <div className="flex items-center">
                    <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-blue-600 mr-3"></div>
                    <div className="text-sm font-medium text-blue-800 dark:text-blue-300">
                      Processing in progress...
                    </div>
                  </div>
                  {fraudSyncStatus.running_tasks.length > 0 && (
                    <div className="mt-2 text-xs text-blue-600 dark:text-blue-400">
                      {fraudSyncStatus.running_tasks.map((task) => (
                        <div key={task.task_id}>
                          {task.task_type === "trigger_fraud_analysis" ? "Analyzing fraud" : "Reprocessing rules"}
                          {" "}- Started {formatDate(task.started_at, {
                            timezone: settings?.timezone || "UTC",
                            dateFormat: settings?.date_format || "MMM d, yyyy HH:mm"
                          })}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* Days Selection */}
              <div className="mb-5">
                <label htmlFor="fraud-sync-days" className="block text-sm font-medium text-gray-700 dark:text-dark-600">
                  Process orders from last (days)
                </label>
                <div className="mt-1">
                  <input
                    id="fraud-sync-days"
                    type="number"
                    min="1"
                    max="365"
                    value={settings?.fraud_sync_days || fraudSyncDays}
                    onChange={(e) => {
                      const value = parseInt(e.target.value);
                      if (!isNaN(value) && value >= 1 && value <= 365) {
                        setFraudSyncDays(value);
                        updateSettings.mutate({ fraud_sync_days: value });
                      }
                    }}
                    className="block w-32 rounded-md border-gray-300 dark:!border-gray-600 bg-white dark:bg-dark-100 text-gray-900 dark:text-dark-800 shadow-sm focus:outline-none focus:!ring-0 focus:!border-gray-300 dark:focus:!border-gray-600 sm:text-sm"
                    placeholder="7"
                  />
                  <p className="text-xs text-gray-400 dark:text-dark-300 mt-1">
                    Enter 1-365 days
                  </p>
                </div>
              </div>

              {/* Action Buttons */}
              <div className="flex flex-col sm:flex-row gap-3">
                <button
                  onClick={() => triggerFraudAnalysis.mutate(fraudSyncDays)}
                  disabled={triggerFraudAnalysis.isPending || fraudSyncStatus?.is_processing}
                  className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md text-white bg-blue-600 hover:bg-blue-700 disabled:bg-gray-400 dark:disabled:bg-gray-600 disabled:text-gray-200 dark:disabled:text-gray-400 disabled:cursor-not-allowed focus:outline-none"
                >
                  {triggerFraudAnalysis.isPending ? (
                    <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white mr-2"></div>
                  ) : (
                    <PlayIcon className="h-4 w-4 mr-2" />
                  )}
                  Trigger Fraud Analysis
                </button>

                <button
                  onClick={() => reprocessFraudRules.mutate(fraudSyncDays)}
                  disabled={reprocessFraudRules.isPending || fraudSyncStatus?.is_processing}
                  className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md text-white bg-purple-600 hover:bg-purple-700 disabled:bg-gray-400 dark:disabled:bg-gray-600 disabled:text-gray-200 dark:disabled:text-gray-400 disabled:cursor-not-allowed focus:outline-none"
                >
                  {reprocessFraudRules.isPending ? (
                    <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white mr-2"></div>
                  ) : (
                    <ArrowPathIcon className="h-4 w-4 mr-2" />
                  )}
                  Reprocess Fraud Rules
                </button>
              </div>

              {/* Help Text */}
              <div className="mt-4 text-xs text-gray-500 dark:text-dark-600">
                <p className="mb-1">
                  <strong>Trigger Fraud Analysis:</strong> Analyzes recent orders for fraud indicators and creates fraud analyses records.
                </p>
                <p>
                  <strong>Reprocess Fraud Rules:</strong> Applies your current fraud detection rules to existing fraud analyses.
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Product Exclusions */}
      <ExcludedSKUsSection timezone={settings?.timezone} />

      {/* Display Preferences */}
      <div className="bg-white dark:bg-dark-100 shadow rounded-lg">
        <div className="px-4 py-5 sm:p-6">
          <h3 className="text-lg font-medium leading-6 text-gray-900 dark:text-dark-800">
            Display Preferences
          </h3>
          <p className="mt-1 text-sm text-gray-500 dark:text-dark-400">
            Customize how dates, times, and the interface appear.
          </p>

          <div className="mt-6 space-y-6">
            {/* Timezone Selection */}
            <TimezoneSelector
              value={settings?.timezone || "UTC"}
              onChange={(timezone) => updateSettings.mutate({ timezone })}
            />

            {/* Date Format Selection */}
            <DateFormatSelector
              value={settings?.date_format || "MMM d, yyyy HH:mm"}
              onChange={(date_format) => updateSettings.mutate({ date_format })}
              timezone={settings?.timezone || "UTC"}
            />

            {/* Theme Toggle */}
            <div className="border-t pt-6">
              <ThemeToggle />
            </div>
          </div>
        </div>
      </div>

      {/* Data & Storage Management */}
      <div className="bg-white dark:bg-dark-100 shadow rounded-lg">
        <div className="px-4 py-5 sm:p-6">
          <h3 className="text-lg font-medium leading-6 text-gray-900 dark:text-dark-800">
            Data & Storage Management
          </h3>
          <p className="mt-1 text-sm text-gray-500">
            Configure data retention and manage your stored data.
          </p>

          <div className="mt-6 space-y-6">
            {/* Log retention */}
            <div>
              <label
                htmlFor="log-retention"
                className="block text-sm font-medium text-gray-700 dark:text-dark-600"
              >
                Order Log Retention (days)
              </label>
              <p className="text-sm text-gray-500 dark:text-dark-400 mb-2">
                How long to keep order processing logs
              </p>
              <select
                id="log-retention"
                value={settings?.log_retention_days || 30}
                onChange={(e) =>
                  updateSettings.mutate({
                    log_retention_days: parseInt(e.target.value),
                  })
                }
                className="mt-1 block w-full rounded-md border-gray-300 dark:!border-gray-600 bg-white dark:bg-dark-100 text-gray-900 dark:text-dark-800 shadow-sm focus:outline-none focus:!ring-0 focus:!border-gray-300 dark:focus:!border-gray-600 sm:text-sm"
              >
                <option value={7}>7 days</option>
                <option value={14}>14 days</option>
                <option value={30}>30 days</option>
                <option value={60}>60 days</option>
                <option value={90}>90 days</option>
                <option value={180}>180 days</option>
              </select>
            </div>

            {/* Database Compaction */}
            <div className="border-t pt-6">
              <h4 className="text-sm font-medium text-gray-700 dark:text-dark-600 mb-3">
                Database Compaction
              </h4>
              <DatabaseCompaction />
            </div>

            {/* Reset Data */}
            <div className="border-t pt-6">
              <h4 className="text-sm font-medium text-gray-700 dark:text-dark-600 mb-3">
                Reset Operational Data
              </h4>
              <p className="text-sm text-gray-500 dark:text-dark-400 mb-4">
                Reset operational data while preserving your stores, rules, and
                settings.
              </p>
              <button
                onClick={() => setShowResetModal(true)}
                className="inline-flex items-center px-4 py-2 border border-red-300 dark:border-red-600 text-sm font-medium rounded-md text-red-700 dark:text-red-400 bg-white dark:bg-dark-100 hover:bg-red-50 dark:hover:bg-red-900/20 focus:outline-none"
              >
                <TrashIcon className="h-4 w-4 mr-2" />
                Reset Data
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Reset Data Modal */}
      <Dialog
        open={showResetModal}
        onClose={() => setShowResetModal(false)}
        className="relative z-50"
      >
        <div
          className="fixed inset-0 bg-black/50 dark:bg-black/70"
          aria-hidden="true"
        />

        <div className="fixed inset-0 flex items-center justify-center p-4">
          <Dialog.Panel className="mx-auto max-w-lg w-full bg-white dark:bg-dark-100 rounded-xl shadow-lg border border-gray-200 dark:border-dark-200">
            <div className="p-6">
              <div className="flex items-center">
                <div className="flex-shrink-0">
                  <ExclamationTriangleIcon className="h-12 w-12 text-red-600" />
                </div>
                <div className="ml-4">
                  <Dialog.Title className="text-lg font-medium text-gray-900 dark:text-dark-800">
                    Reset Data
                  </Dialog.Title>
                  <p className="mt-1 text-sm text-gray-500">
                    This action cannot be undone. All selected data will be
                    permanently deleted.
                  </p>
                </div>
              </div>

              {dataStats && (
                <div className="mt-6 space-y-4">
                  <h4 className="text-sm font-medium text-gray-900 dark:text-dark-800">
                    Select data to reset:
                  </h4>

                  <div className="space-y-3">
                    <label className="flex items-center">
                      <input
                        type="checkbox"
                        checked={resetOptions.reset_order_logs}
                        onChange={(e) =>
                          setResetOptions({
                            ...resetOptions,
                            reset_order_logs: e.target.checked,
                          })
                        }
                        className="h-4 w-4 text-red-600 border-gray-300 rounded focus:outline-none"
                      />
                      <span className="ml-3 text-sm">
                        <span className="font-medium text-gray-900 dark:text-dark-800">
                          Order Logs
                        </span>
                        <span className="text-gray-500">
                          {" "}
                          ({dataStats.order_logs} records)
                        </span>
                      </span>
                    </label>

                    <label className="flex items-center">
                      <input
                        type="checkbox"
                        checked={resetOptions.reset_processed_orders}
                        onChange={(e) =>
                          setResetOptions({
                            ...resetOptions,
                            reset_processed_orders: e.target.checked,
                          })
                        }
                        className="h-4 w-4 text-red-600 border-gray-300 rounded focus:outline-none"
                      />
                      <span className="ml-3 text-sm">
                        <span className="font-medium text-gray-900 dark:text-dark-800">
                          Processed Orders
                        </span>
                        <span className="text-gray-500">
                          {" "}
                          ({dataStats.processed_orders} records)
                        </span>
                        <p className="text-xs text-gray-400">
                          Allows orders to be reprocessed
                        </p>
                      </span>
                    </label>

                    <label className="flex items-center">
                      <input
                        type="checkbox"
                        checked={resetOptions.reset_oos_incidents}
                        onChange={(e) =>
                          setResetOptions({
                            ...resetOptions,
                            reset_oos_incidents: e.target.checked,
                          })
                        }
                        className="h-4 w-4 text-red-600 border-gray-300 rounded focus:outline-none"
                      />
                      <span className="ml-3 text-sm">
                        <span className="font-medium text-gray-900 dark:text-dark-800">
                          Out of Stock Incidents
                        </span>
                        <span className="text-gray-500">
                          {" "}
                          ({dataStats.oos_incidents} records)
                        </span>
                      </span>
                    </label>

                    <label className="flex items-center">
                      <input
                        type="checkbox"
                        checked={resetOptions.reset_fraud_analyses}
                        onChange={(e) =>
                          setResetOptions({
                            ...resetOptions,
                            reset_fraud_analyses: e.target.checked,
                          })
                        }
                        className="h-4 w-4 text-red-600 border-gray-300 rounded focus:outline-none"
                      />
                      <span className="ml-3 text-sm">
                        <span className="font-medium text-gray-900 dark:text-dark-800">
                          Fraud Analyses
                        </span>
                        <span className="text-gray-500">
                          {" "}
                          ({dataStats.fraud_analyses} records)
                        </span>
                        <p className="text-xs text-gray-400">
                          All fraud detection results
                        </p>
                      </span>
                    </label>

                    <label className="flex items-center">
                      <input
                        type="checkbox"
                        checked={resetOptions.reset_archived_fraud_analyses}
                        onChange={(e) =>
                          setResetOptions({
                            ...resetOptions,
                            reset_archived_fraud_analyses: e.target.checked,
                          })
                        }
                        className="h-4 w-4 text-red-600 border-gray-300 rounded focus:outline-none"
                      />
                      <span className="ml-3 text-sm">
                        <span className="font-medium text-gray-900 dark:text-dark-800">
                          Archived Fraud Analyses
                        </span>
                        <span className="text-gray-500">
                          {" "}
                          ({dataStats.archived_fraud_analyses} records)
                        </span>
                        <p className="text-xs text-gray-400">
                          Fulfilled/cancelled order fraud data
                        </p>
                      </span>
                    </label>

                    <label className="flex items-center">
                      <input
                        type="checkbox"
                        checked={resetOptions.reset_task_status}
                        onChange={(e) =>
                          setResetOptions({
                            ...resetOptions,
                            reset_task_status: e.target.checked,
                          })
                        }
                        className="h-4 w-4 text-red-600 border-gray-300 rounded focus:outline-none"
                      />
                      <span className="ml-3 text-sm">
                        <span className="font-medium text-gray-900 dark:text-dark-800">
                          Old Task Status
                        </span>
                        <span className="text-gray-500">
                          {" "}
                          ({dataStats.task_status} records)
                        </span>
                        <p className="text-xs text-gray-400">
                          Tasks older than 24 hours
                        </p>
                      </span>
                    </label>
                  </div>
                </div>
              )}

              <div className="mt-6">
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Type "RESET" to confirm:
                </label>
                <input
                  type="text"
                  value={resetOptions.confirmation}
                  onChange={(e) =>
                    setResetOptions({
                      ...resetOptions,
                      confirmation: e.target.value,
                    })
                  }
                  className="w-full px-3 py-2 border border-gray-300 dark:!border-gray-600 rounded-md shadow-sm bg-white dark:bg-dark-100 text-gray-900 dark:text-dark-800 focus:outline-none focus:!ring-0 focus:!border-gray-300 dark:focus:!border-gray-600 sm:text-sm"
                  placeholder="Type RESET to confirm"
                />
              </div>

              <div className="mt-6 flex justify-end space-x-3">
                <button
                  onClick={() => {
                    setShowResetModal(false);
                    setResetOptions({
                      reset_order_logs: true,
                      reset_processed_orders: true,
                      reset_oos_incidents: true,
                      reset_fraud_analyses: true,
                      reset_archived_fraud_analyses: false,
                      reset_task_status: false,
                      confirmation: "",
                    });
                  }}
                  className="px-4 py-2 text-sm font-medium text-gray-700 dark:text-dark-600 bg-white dark:bg-dark-100 border border-gray-300 dark:border-dark-300 rounded-md hover:bg-gray-50 dark:hover:bg-dark-200 focus:outline-none"
                >
                  Cancel
                </button>
                <button
                  onClick={() => resetData.mutate(resetOptions)}
                  disabled={
                    resetOptions.confirmation !== "RESET" || resetData.isPending
                  }
                  className="px-4 py-2 text-sm font-medium text-white bg-red-600 border border-transparent rounded-md hover:bg-red-700 focus:outline-none disabled:opacity-50"
                >
                  {resetData.isPending ? (
                    <>
                      <LoadingSpinner size="sm" className="inline mr-2" />
                      Resetting...
                    </>
                  ) : (
                    "Reset Data"
                  )}
                </button>
              </div>
            </div>
          </Dialog.Panel>
        </div>
      </Dialog>
    </motion.div>
  );
};

export default Settings;
