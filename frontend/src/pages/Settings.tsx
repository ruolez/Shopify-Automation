import React, { useState } from 'react';
import { motion } from 'framer-motion';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Switch } from '@headlessui/react';
import { Dialog } from '@headlessui/react';
import { ExclamationTriangleIcon, TrashIcon } from '@heroicons/react/24/outline';
import toast from 'react-hot-toast';
import api from '../utils/api';
import LoadingSpinner from '../components/LoadingSpinner';

interface Settings {
  id: number;
  user_id: number;
  sync_frequency_minutes: number;
  auto_sync_enabled: boolean;
  log_retention_days: number;
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
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['settings'] });
      toast.success('Settings updated successfully');
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