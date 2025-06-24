import React from 'react';
import { motion } from 'framer-motion';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Switch } from '@headlessui/react';
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

const Settings: React.FC = () => {
  const queryClient = useQueryClient();

  const { data: settings, isLoading } = useQuery<Settings>({
    queryKey: ['settings'],
    queryFn: async () => {
      const response = await api.get('/settings');
      return response.data;
    },
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
    </motion.div>
  );
};

export default Settings;