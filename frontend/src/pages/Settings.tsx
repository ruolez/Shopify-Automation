import React, { useState } from 'react';
import { motion } from 'framer-motion';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Switch } from '@headlessui/react';
import { Dialog } from '@headlessui/react';
import { ExclamationTriangleIcon, TrashIcon, PlusIcon, PencilIcon } from '@heroicons/react/24/outline';
import toast from 'react-hot-toast';
import api from '../utils/api';
import LoadingSpinner from '../components/LoadingSpinner';
import { formatDate, getCurrentTimeInTimezone, formatShortDate } from '../utils/dateFormat';

interface Settings {
  id: number;
  user_id: number;
  sync_frequency_minutes: number;
  auto_sync_enabled: boolean;
  log_retention_days: number;
  timezone: string;
  date_format: string;
  created_at: string;
  updated_at: string | null;
}

interface DataStats {
  order_logs: number;
  processed_orders: number;
  oos_incidents: number;
  task_status: number;
}

interface ResetOptions {
  reset_order_logs: boolean;
  reset_processed_orders: boolean;
  reset_oos_incidents: boolean;
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

const TimezoneSelector: React.FC<{
  value: string;
  onChange: (timezone: string) => void;
}> = ({ value, onChange }) => {
  const { data: timezoneData } = useQuery<TimezoneData>({
    queryKey: ['timezones'],
    queryFn: async () => {
      const response = await api.get('/settings/timezones');
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
      <label htmlFor="timezone" className="block text-sm font-medium text-gray-700">
        Timezone
      </label>
      <p className="text-sm text-gray-500 mb-2">
        Select your preferred timezone for displaying dates and times
      </p>
      
      <div className="space-y-3">
        <select
          id="timezone"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="w-full rounded-md border-gray-300 shadow-sm focus:border-shopify-500 focus:ring-shopify-500 sm:text-sm"
        >
          {timezoneData && Object.entries(timezoneData.groups).map(([groupName, timezones]) => (
            <optgroup key={groupName} label={groupName}>
              {timezones.map((timezone) => (
                <option key={timezone} value={timezone}>
                  {timezone.replace(/_/g, ' ')}
                </option>
              ))}
            </optgroup>
          ))}
        </select>
        
        <div className="text-sm text-gray-600 bg-gray-50 p-3 rounded-md">
          <div className="font-medium text-gray-700">Current time in {value}:</div>
          <div className="text-lg font-mono">
            {formatDate(currentTime, { timezone: value, dateFormat: 'EEEE, MMMM d, yyyy HH:mm:ss' })}
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
    queryKey: ['date-formats'],
    queryFn: async () => {
      const response = await api.get('/settings/date-formats');
      return response.data;
    },
  });

  const previewTime = React.useMemo(() => {
    const now = new Date();
    return formatDate(now, { timezone, dateFormat: value });
  }, [timezone, value]);

  return (
    <div>
      <label htmlFor="date-format" className="block text-sm font-medium text-gray-700">
        Date Format
      </label>
      <p className="text-sm text-gray-500 mb-2">
        Choose how dates and times should be displayed throughout the application
      </p>
      
      <div className="space-y-3">
        <select
          id="date-format"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="w-full rounded-md border-gray-300 shadow-sm focus:border-shopify-500 focus:ring-shopify-500 sm:text-sm"
        >
          {dateFormats?.map((format) => (
            <option key={format.format} value={format.format}>
              {format.description} - {format.example}
            </option>
          ))}
        </select>
        
        <div className="text-sm text-gray-600 bg-gray-50 p-3 rounded-md">
          <div className="font-medium text-gray-700">Preview with current format:</div>
          <div className="text-lg font-mono">{previewTime}</div>
        </div>
      </div>
    </div>
  );
};

const ExcludedSKUsSection: React.FC<{ timezone?: string }> = ({ timezone = 'UTC' }) => {
  const queryClient = useQueryClient();
  const [showAddModal, setShowAddModal] = useState(false);
  const [editingSku, setEditingSku] = useState<ExcludedSKU | null>(null);
  const [formData, setFormData] = useState({
    sku_pattern: '',
    description: ''
  });

  const { data: excludedSkus, isLoading } = useQuery<ExcludedSKU[]>({
    queryKey: ['excluded-skus'],
    queryFn: async () => {
      const response = await api.get('/settings/excluded-skus');
      return response.data;
    },
  });

  const createMutation = useMutation({
    mutationFn: async (data: { sku_pattern: string; description?: string }) => {
      const response = await api.post('/settings/excluded-skus', data);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['excluded-skus'] });
      toast.success('Excluded SKU added successfully');
      setShowAddModal(false);
      setFormData({ sku_pattern: '', description: '' });
    },
    onError: (error: any) => {
      toast.error(error.response?.data?.detail || 'Failed to add excluded SKU');
    },
  });

  const updateMutation = useMutation({
    mutationFn: async ({ id, data }: { id: number; data: Partial<ExcludedSKU> }) => {
      const response = await api.put(`/settings/excluded-skus/${id}`, data);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['excluded-skus'] });
      toast.success('Excluded SKU updated successfully');
      setEditingSku(null);
    },
    onError: (error: any) => {
      toast.error(error.response?.data?.detail || 'Failed to update excluded SKU');
    },
  });

  const deleteMutation = useMutation({
    mutationFn: async (id: number) => {
      await api.delete(`/settings/excluded-skus/${id}`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['excluded-skus'] });
      toast.success('Excluded SKU deleted successfully');
    },
    onError: (error: any) => {
      toast.error(error.response?.data?.detail || 'Failed to delete excluded SKU');
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!formData.sku_pattern.trim()) {
      toast.error('SKU pattern is required');
      return;
    }

    if (editingSku) {
      updateMutation.mutate({
        id: editingSku.id,
        data: {
          sku_pattern: formData.sku_pattern,
          description: formData.description || undefined
        }
      });
    } else {
      createMutation.mutate({
        sku_pattern: formData.sku_pattern,
        description: formData.description || undefined
      });
    }
  };

  const startEdit = (sku: ExcludedSKU) => {
    setEditingSku(sku);
    setFormData({
      sku_pattern: sku.sku_pattern,
      description: sku.description || ''
    });
    setShowAddModal(true);
  };

  const cancelEdit = () => {
    setEditingSku(null);
    setFormData({ sku_pattern: '', description: '' });
    setShowAddModal(false);
  };

  const toggleActive = (sku: ExcludedSKU) => {
    updateMutation.mutate({
      id: sku.id,
      data: { is_active: !sku.is_active }
    });
  };

  return (
    <>
      <div className="bg-white shadow rounded-lg">
        <div className="px-4 py-5 sm:p-6">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="text-lg font-medium leading-6 text-gray-900">
                Excluded SKUs
              </h3>
              <p className="mt-1 text-sm text-gray-500">
                SKU patterns to exclude from weight calculations and OOS reporting. These products will still be moved during fulfillment location changes.
              </p>
            </div>
            <button
              onClick={() => setShowAddModal(true)}
              className="inline-flex items-center px-3 py-2 border border-transparent text-sm leading-4 font-medium rounded-md text-white bg-shopify-600 hover:bg-shopify-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-shopify-500"
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
                  className="flex items-center justify-between p-4 border border-gray-200 rounded-lg"
                >
                  <div className="flex-1">
                    <div className="flex items-center space-x-3">
                      <code className="px-2 py-1 bg-gray-100 rounded text-sm font-mono">
                        {sku.sku_pattern}
                      </code>
                      <span
                        className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                          sku.is_active
                            ? 'bg-green-100 text-green-800'
                            : 'bg-red-100 text-red-800'
                        }`}
                      >
                        {sku.is_active ? 'Active' : 'Inactive'}
                      </span>
                    </div>
                    {sku.description && (
                      <p className="mt-1 text-sm text-gray-600">{sku.description}</p>
                    )}
                    <p className="mt-1 text-xs text-gray-400">
                      Created: {formatShortDate(sku.created_at, timezone)}
                    </p>
                  </div>
                  <div className="flex items-center space-x-2">
                    <Switch
                      checked={sku.is_active}
                      onChange={() => toggleActive(sku)}
                      className={`${
                        sku.is_active ? 'bg-shopify-600' : 'bg-gray-200'
                      } relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-shopify-500 focus:ring-offset-2`}
                    >
                      <span className="sr-only">Toggle active status</span>
                      <span
                        className={`${
                          sku.is_active ? 'translate-x-6' : 'translate-x-1'
                        } inline-block h-4 w-4 transform rounded-full bg-white transition-transform`}
                      />
                    </Switch>
                    <button
                      onClick={() => startEdit(sku)}
                      className="p-2 text-gray-600 hover:bg-gray-50 rounded-lg transition-colors"
                      title="Edit SKU pattern"
                    >
                      <PencilIcon className="h-4 w-4" />
                    </button>
                    <button
                      onClick={() => {
                        if (window.confirm('Are you sure you want to delete this SKU pattern?')) {
                          deleteMutation.mutate(sku.id);
                        }
                      }}
                      className="p-2 text-red-600 hover:bg-red-50 rounded-lg transition-colors"
                      title="Delete SKU pattern"
                    >
                      <TrashIcon className="h-4 w-4" />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-center py-8 text-gray-500">
              <p>No excluded SKU patterns configured.</p>
              <p className="text-sm">Add patterns to exclude specific products from weight calculations and OOS reporting.</p>
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
          <Dialog.Overlay className="fixed inset-0 bg-gray-500 bg-opacity-75 transition-opacity" />

          <div className="inline-block align-bottom bg-white rounded-lg px-4 pt-5 pb-4 text-left overflow-hidden shadow-xl transform transition-all sm:my-8 sm:align-middle sm:max-w-lg sm:w-full sm:p-6">
            <div>
              <div className="mt-3 text-center sm:mt-0 sm:text-left">
                <Dialog.Title
                  as="h3"
                  className="text-lg leading-6 font-medium text-gray-900"
                >
                  {editingSku ? 'Edit' : 'Add'} Excluded SKU Pattern
                </Dialog.Title>
                <div className="mt-4">
                  <form onSubmit={handleSubmit} className="space-y-4">
                    <div>
                      <label htmlFor="sku_pattern" className="block text-sm font-medium text-gray-700">
                        SKU Pattern
                      </label>
                      <input
                        type="text"
                        id="sku_pattern"
                        value={formData.sku_pattern}
                        onChange={(e) => setFormData({ ...formData, sku_pattern: e.target.value })}
                        placeholder="e.g., SAMPLE, TEST-, _EXCLUDED"
                        className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-shopify-500 focus:ring-shopify-500 sm:text-sm"
                        required
                      />
                      <p className="mt-1 text-xs text-gray-500">
                        Products with SKUs containing this text will be excluded (case-insensitive)
                      </p>
                    </div>
                    <div>
                      <label htmlFor="description" className="block text-sm font-medium text-gray-700">
                        Description (optional)
                      </label>
                      <textarea
                        id="description"
                        value={formData.description}
                        onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                        placeholder="Why is this SKU pattern excluded?"
                        rows={3}
                        className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-shopify-500 focus:ring-shopify-500 sm:text-sm"
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
                className="w-full inline-flex justify-center rounded-md border border-transparent shadow-sm px-4 py-2 bg-shopify-600 text-base font-medium text-white hover:bg-shopify-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-shopify-500 sm:ml-3 sm:w-auto sm:text-sm disabled:opacity-50"
              >
                {createMutation.isPending || updateMutation.isPending ? (
                  <>
                    <LoadingSpinner size="sm" className="mr-2" />
                    {editingSku ? 'Updating...' : 'Adding...'}
                  </>
                ) : (
                  editingSku ? 'Update' : 'Add'
                )}
              </button>
              <button
                type="button"
                onClick={cancelEdit}
                className="mt-3 w-full inline-flex justify-center rounded-md border border-gray-300 shadow-sm px-4 py-2 bg-white text-base font-medium text-gray-700 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-shopify-500 sm:mt-0 sm:w-auto sm:text-sm"
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

const Settings: React.FC = () => {
  const queryClient = useQueryClient();
  const [showResetModal, setShowResetModal] = useState(false);
  const [resetOptions, setResetOptions] = useState<ResetOptions>({
    reset_order_logs: true,
    reset_processed_orders: true,
    reset_oos_incidents: true,
    reset_task_status: false,
    confirmation: '',
  });

  const { data: settings, isLoading } = useQuery<Settings>({
    queryKey: ['settings'],
    queryFn: async () => {
      const response = await api.get('/settings');
      return response.data;
    },
  });

  const { data: dataStats } = useQuery<DataStats>({
    queryKey: ['data-stats'],
    queryFn: async () => {
      const response = await api.get('/settings/data-stats');
      return response.data;
    },
    enabled: showResetModal,
  });

  const updateSettings = useMutation({
    mutationFn: async (data: Partial<Settings>) => {
      const response = await api.put('/settings', data);
      return response.data;
    },
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['settings'] });
      
      // Trigger localStorage event for cross-window updates
      localStorage.setItem('user-settings-updated', Date.now().toString());
      
      // Trigger custom event for same-window updates (storage events don't fire in same window)
      window.dispatchEvent(new CustomEvent('settings-updated', { 
        detail: { timezone: variables.timezone, dateFormat: variables.date_format }
      }));
      
      toast.success('Settings updated successfully');
      
      // Debug logging
      if (variables.timezone) {
        console.log('Timezone updated to:', variables.timezone);
      }
      if (variables.date_format) {
        console.log('Date format updated to:', variables.date_format);
      }
    },
    onError: () => {
      toast.error('Failed to update settings');
    },
  });

  const syncAllStores = useMutation({
    mutationFn: async () => {
      const response = await api.post('/sync/all');
      return response.data;
    },
    onSuccess: () => {
      toast.success('Sync started for all stores');
    },
    onError: () => {
      toast.error('Failed to start sync');
    },
  });

  const resetData = useMutation({
    mutationFn: async (options: ResetOptions) => {
      const response = await api.post('/settings/reset-data', options);
      return response.data;
    },
    onSuccess: () => {
      toast.success('Data reset completed successfully');
      setShowResetModal(false);
      setResetOptions({
        reset_order_logs: true,
        reset_processed_orders: true,
        reset_oos_incidents: true,
        reset_task_status: false,
        confirmation: '',
      });
      // Invalidate queries that might have been affected
      queryClient.invalidateQueries({ queryKey: ['order-logs'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard-stats'] });
      queryClient.invalidateQueries({ queryKey: ['reports'] });
    },
    onError: (error: any) => {
      toast.error(error.response?.data?.detail || 'Failed to reset data');
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
      <div className="bg-white shadow rounded-lg">
        <div className="px-4 py-5 sm:p-6">
          <h3 className="text-lg font-medium leading-6 text-gray-900">
            Sync Settings
          </h3>
          <p className="mt-1 text-sm text-gray-500">
            Configure how often orders are synchronized and processed.
          </p>

          <div className="mt-6 space-y-6">
            {/* Auto-sync toggle */}
            <div className="flex items-center justify-between">
              <div>
                <label htmlFor="auto-sync" className="text-sm font-medium text-gray-700">
                  Automatic Order Processing
                </label>
                <p className="text-sm text-gray-500">
                  Automatically process orders based on your rules
                </p>
              </div>
              <Switch
                checked={settings?.auto_sync_enabled || false}
                onChange={(enabled) => updateSettings.mutate({ auto_sync_enabled: enabled })}
                className={`${
                  settings?.auto_sync_enabled ? 'bg-shopify-600' : 'bg-gray-200'
                } relative inline-flex h-6 w-11 items-center rounded-full transition-colors`}
              >
                <span
                  className={`${
                    settings?.auto_sync_enabled ? 'translate-x-6' : 'translate-x-1'
                  } inline-block h-4 w-4 transform rounded-full bg-white transition-transform`}
                />
              </Switch>
            </div>

            {/* Sync frequency */}
            <div>
              <label htmlFor="sync-frequency" className="block text-sm font-medium text-gray-700">
                Sync Frequency (minutes)
              </label>
              <p className="text-sm text-gray-500 mb-2">
                How often to check for new orders when auto-sync is enabled
              </p>
              <select
                id="sync-frequency"
                value={settings?.sync_frequency_minutes || 10}
                onChange={(e) => updateSettings.mutate({ sync_frequency_minutes: parseInt(e.target.value) })}
                className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-shopify-500 focus:ring-shopify-500 sm:text-sm"
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

            {/* Log retention */}
            <div>
              <label htmlFor="log-retention" className="block text-sm font-medium text-gray-700">
                Order Log Retention (days)
              </label>
              <p className="text-sm text-gray-500 mb-2">
                How long to keep order processing logs
              </p>
              <select
                id="log-retention"
                value={settings?.log_retention_days || 30}
                onChange={(e) => updateSettings.mutate({ log_retention_days: parseInt(e.target.value) })}
                className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-shopify-500 focus:ring-shopify-500 sm:text-sm"
              >
                <option value={7}>7 days</option>
                <option value={14}>14 days</option>
                <option value={30}>30 days</option>
                <option value={60}>60 days</option>
                <option value={90}>90 days</option>
                <option value={180}>180 days</option>
              </select>
            </div>
          </div>
        </div>
      </div>

      {/* Timezone & Date Format Settings */}
      <div className="bg-white shadow rounded-lg">
        <div className="px-4 py-5 sm:p-6">
          <h3 className="text-lg font-medium leading-6 text-gray-900">
            Timezone & Date Format
          </h3>
          <p className="mt-1 text-sm text-gray-500">
            Configure your preferred timezone and date format for displaying timestamps.
          </p>

          <div className="mt-6 space-y-6">
            {/* Timezone Selection */}
            <TimezoneSelector
              value={settings?.timezone || 'UTC'}
              onChange={(timezone) => updateSettings.mutate({ timezone })}
            />

            {/* Date Format Selection */}
            <DateFormatSelector
              value={settings?.date_format || 'MMM d, yyyy HH:mm'}
              onChange={(date_format) => updateSettings.mutate({ date_format })}
              timezone={settings?.timezone || 'UTC'}
            />
          </div>
        </div>
      </div>

      {/* Manual sync section */}
      <div className="bg-white shadow rounded-lg">
        <div className="px-4 py-5 sm:p-6">
          <h3 className="text-lg font-medium leading-6 text-gray-900">
            Manual Sync
          </h3>
          <p className="mt-1 text-sm text-gray-500">
            Manually trigger order synchronization for all stores.
          </p>

          <div className="mt-5">
            <button
              onClick={() => syncAllStores.mutate()}
              disabled={syncAllStores.isPending}
              className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md shadow-sm text-white bg-shopify-600 hover:bg-shopify-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-shopify-500 disabled:opacity-50"
            >
              {syncAllStores.isPending ? (
                <>
                  <LoadingSpinner size="sm" className="mr-2" />
                  Syncing...
                </>
              ) : (
                'Sync All Stores Now'
              )}
            </button>
          </div>
        </div>
      </div>

      {/* Excluded SKUs section */}
      <ExcludedSKUsSection timezone={settings?.timezone} />

      {/* Data Management section */}
      <div className="bg-white shadow rounded-lg">
        <div className="px-4 py-5 sm:p-6">
          <h3 className="text-lg font-medium leading-6 text-gray-900">
            Data Management
          </h3>
          <p className="mt-1 text-sm text-gray-500">
            Reset operational data while preserving your stores, rules, and settings.
          </p>

          <div className="mt-5">
            <button
              onClick={() => setShowResetModal(true)}
              className="inline-flex items-center px-4 py-2 border border-red-300 text-sm font-medium rounded-md text-red-700 bg-white hover:bg-red-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-red-500"
            >
              <TrashIcon className="h-4 w-4 mr-2" />
              Reset Data
            </button>
          </div>
        </div>
      </div>

      {/* Reset Data Modal */}
      <Dialog open={showResetModal} onClose={() => setShowResetModal(false)} className="relative z-50">
        <div className="fixed inset-0 bg-black bg-opacity-30" aria-hidden="true" />
        
        <div className="fixed inset-0 flex items-center justify-center p-4">
          <Dialog.Panel className="mx-auto max-w-lg w-full bg-white rounded-xl shadow-lg">
            <div className="p-6">
              <div className="flex items-center">
                <div className="flex-shrink-0">
                  <ExclamationTriangleIcon className="h-12 w-12 text-red-600" />
                </div>
                <div className="ml-4">
                  <Dialog.Title className="text-lg font-medium text-gray-900">
                    Reset Data
                  </Dialog.Title>
                  <p className="mt-1 text-sm text-gray-500">
                    This action cannot be undone. All selected data will be permanently deleted.
                  </p>
                </div>
              </div>

              {dataStats && (
                <div className="mt-6 space-y-4">
                  <h4 className="text-sm font-medium text-gray-900">Select data to reset:</h4>
                  
                  <div className="space-y-3">
                    <label className="flex items-center">
                      <input
                        type="checkbox"
                        checked={resetOptions.reset_order_logs}
                        onChange={(e) => setResetOptions({ ...resetOptions, reset_order_logs: e.target.checked })}
                        className="h-4 w-4 text-red-600 focus:ring-red-500 border-gray-300 rounded"
                      />
                      <span className="ml-3 text-sm">
                        <span className="font-medium text-gray-900">Order Logs</span>
                        <span className="text-gray-500"> ({dataStats.order_logs} records)</span>
                      </span>
                    </label>

                    <label className="flex items-center">
                      <input
                        type="checkbox"
                        checked={resetOptions.reset_processed_orders}
                        onChange={(e) => setResetOptions({ ...resetOptions, reset_processed_orders: e.target.checked })}
                        className="h-4 w-4 text-red-600 focus:ring-red-500 border-gray-300 rounded"
                      />
                      <span className="ml-3 text-sm">
                        <span className="font-medium text-gray-900">Processed Orders</span>
                        <span className="text-gray-500"> ({dataStats.processed_orders} records)</span>
                        <p className="text-xs text-gray-400">Allows orders to be reprocessed</p>
                      </span>
                    </label>

                    <label className="flex items-center">
                      <input
                        type="checkbox"
                        checked={resetOptions.reset_oos_incidents}
                        onChange={(e) => setResetOptions({ ...resetOptions, reset_oos_incidents: e.target.checked })}
                        className="h-4 w-4 text-red-600 focus:ring-red-500 border-gray-300 rounded"
                      />
                      <span className="ml-3 text-sm">
                        <span className="font-medium text-gray-900">Out of Stock Incidents</span>
                        <span className="text-gray-500"> ({dataStats.oos_incidents} records)</span>
                      </span>
                    </label>

                    <label className="flex items-center">
                      <input
                        type="checkbox"
                        checked={resetOptions.reset_task_status}
                        onChange={(e) => setResetOptions({ ...resetOptions, reset_task_status: e.target.checked })}
                        className="h-4 w-4 text-red-600 focus:ring-red-500 border-gray-300 rounded"
                      />
                      <span className="ml-3 text-sm">
                        <span className="font-medium text-gray-900">Old Task Status</span>
                        <span className="text-gray-500"> ({dataStats.task_status} records)</span>
                        <p className="text-xs text-gray-400">Tasks older than 24 hours</p>
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
                  onChange={(e) => setResetOptions({ ...resetOptions, confirmation: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-red-500 focus:border-red-500 sm:text-sm"
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
                      reset_task_status: false,
                      confirmation: '',
                    });
                  }}
                  className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-gray-500"
                >
                  Cancel
                </button>
                <button
                  onClick={() => resetData.mutate(resetOptions)}
                  disabled={resetOptions.confirmation !== 'RESET' || resetData.isPending}
                  className="px-4 py-2 text-sm font-medium text-white bg-red-600 border border-transparent rounded-md hover:bg-red-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-red-500 disabled:opacity-50"
                >
                  {resetData.isPending ? (
                    <>
                      <LoadingSpinner size="sm" className="inline mr-2" />
                      Resetting...
                    </>
                  ) : (
                    'Reset Data'
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