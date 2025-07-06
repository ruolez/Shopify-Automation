import React, { createContext, useContext, useState, useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import api from '../utils/api';

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

interface SettingsContextType {
  settings: Settings | null;
  isLoading: boolean;
  timezone: string;
  dateFormat: string;
  refetchSettings: () => void;
}

const SettingsContext = createContext<SettingsContextType | undefined>(undefined);

export const useSettings = () => {
  const context = useContext(SettingsContext);
  if (!context) {
    throw new Error('useSettings must be used within a SettingsProvider');
  }
  return context;
};

export const SettingsProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [timezone, setTimezone] = useState('UTC');
  const [dateFormat, setDateFormat] = useState('MMM d, yyyy HH:mm');

  const { data: settings, isLoading, refetch } = useQuery<Settings>({
    queryKey: ['user-settings'],
    queryFn: async () => {
      const response = await api.get('/settings');
      return response.data;
    },
    staleTime: 5 * 60 * 1000, // Consider data fresh for 5 minutes
  });

  // Update local state when settings are fetched
  useEffect(() => {
    if (settings) {
      setTimezone(settings.timezone || 'UTC');
      setDateFormat(settings.date_format || 'MMM d, yyyy HH:mm');
    }
  }, [settings]);

  const value: SettingsContextType = {
    settings: settings || null,
    isLoading,
    timezone,
    dateFormat,
    refetchSettings: refetch,
  };

  return (
    <SettingsContext.Provider value={value}>
      {children}
    </SettingsContext.Provider>
  );
};