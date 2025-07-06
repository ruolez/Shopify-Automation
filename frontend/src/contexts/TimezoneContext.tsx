import { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import { formatDate as formatDateUtil } from '../utils/dateFormat';
import api from '../utils/api';

interface TimezoneContextType {
  timezone: string;
  dateFormat: string;
  setTimezone: (timezone: string) => void;
  setDateFormat: (format: string) => void;
  formatDate: (date: string | Date | null | undefined) => string;
  isLoading: boolean;
}

const TimezoneContext = createContext<TimezoneContextType | undefined>(undefined);

interface TimezoneProviderProps {
  children: ReactNode;
}

export function TimezoneProvider({ children }: TimezoneProviderProps) {
  const [timezone, setTimezoneState] = useState<string>('UTC');
  const [dateFormat, setDateFormatState] = useState<string>('MMM d, yyyy HH:mm');
  const [isLoading, setIsLoading] = useState<boolean>(true);

  // Initialize timezone and date format from user settings
  useEffect(() => {
    const initializeTimezone = async () => {
      try {
        // Try to get user settings from API
        const token = localStorage.getItem('token');
        if (token) {
          const response = await api.get('/settings');
          const settings = response.data;
          setTimezoneState(settings.timezone || 'UTC');
          setDateFormatState(settings.date_format || 'MMM d, yyyy HH:mm');
        } else {
          // No token, use browser timezone
          const browserTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
          setTimezoneState(browserTimezone || 'UTC');
        }
      } catch (error) {
        console.error('Error initializing timezone:', error);
        // Fallback to browser timezone
        const browserTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
        setTimezoneState(browserTimezone || 'UTC');
      } finally {
        setIsLoading(false);
      }
    };

    initializeTimezone();
  }, []);

  // Listen for settings updates (when user changes timezone/date format in Settings page)
  useEffect(() => {
    // Custom event listener for same-window updates
    const handleCustomEvent = (e: CustomEvent) => {
      console.log('Custom timezone event detected:', e.detail);
      const fetchSettings = async () => {
        try {
          const response = await api.get('/settings');
          const settings = response.data;
          console.log('Fetched updated settings:', settings);
          setTimezoneState(settings.timezone || 'UTC');
          setDateFormatState(settings.date_format || 'MMM d, yyyy HH:mm');
          console.log('TimezoneContext updated to:', settings.timezone);
        } catch (error) {
          console.error('Error updating timezone from settings:', error);
        }
      };
      
      fetchSettings();
    };

    // Storage event for cross-window updates
    const handleStorageChange = (e: StorageEvent) => {
      console.log('Storage event detected:', e.key, e.newValue);
      if (e.key === 'user-settings-updated') {
        console.log('Settings update detected from another window');
        handleCustomEvent(new CustomEvent('settings-updated'));
      }
    };

    // Listen for both custom events and storage events
    window.addEventListener('settings-updated', handleCustomEvent as EventListener);
    window.addEventListener('storage', handleStorageChange);
    
    return () => {
      window.removeEventListener('settings-updated', handleCustomEvent as EventListener);
      window.removeEventListener('storage', handleStorageChange);
    };
  }, []);

  const setTimezone = (newTimezone: string) => {
    setTimezoneState(newTimezone);
    // Trigger a custom event to notify other components
    window.dispatchEvent(new CustomEvent('timezone-changed', { detail: { timezone: newTimezone, dateFormat } }));
  };

  const setDateFormat = (newFormat: string) => {
    setDateFormatState(newFormat);
    // Trigger a custom event to notify other components
    window.dispatchEvent(new CustomEvent('timezone-changed', { detail: { timezone, dateFormat: newFormat } }));
  };

  const formatDate = (date: string | Date | null | undefined): string => {
    return formatDateUtil(date, { timezone, dateFormat });
  };

  const contextValue: TimezoneContextType = {
    timezone,
    dateFormat,
    setTimezone,
    setDateFormat,
    formatDate,
    isLoading,
  };

  return (
    <TimezoneContext.Provider value={contextValue}>
      {children}
    </TimezoneContext.Provider>
  );
}

export function useTimezone(): TimezoneContextType {
  const context = useContext(TimezoneContext);
  if (context === undefined) {
    throw new Error('useTimezone must be used within a TimezoneProvider');
  }
  return context;
}

// Hook for getting just the formatting function (lightweight alternative)
export function useDateFormatter() {
  const { formatDate } = useTimezone();
  return formatDate;
}

// Hook for getting timezone info
export function useTimezoneInfo() {
  const { timezone, dateFormat } = useTimezone();
  return { timezone, dateFormat };
}