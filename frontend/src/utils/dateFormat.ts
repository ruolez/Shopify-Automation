import { format, parseISO } from 'date-fns';
import { toZonedTime, formatInTimeZone } from 'date-fns-tz';

// Map backend date format strings to date-fns format strings
const formatMap: Record<string, string> = {
  'MMM d, yyyy HH:mm': 'MMM d, yyyy HH:mm',
  'MM/dd/yyyy HH:mm:ss': 'MM/dd/yyyy HH:mm:ss',
  'dd/MM/yyyy HH:mm': 'dd/MM/yyyy HH:mm',
  'yyyy-MM-dd HH:mm:ss': 'yyyy-MM-dd HH:mm:ss',
  'd MMM yyyy, h:mm a': 'd MMM yyyy, h:mm a',
  'EEEE, MMMM d, yyyy': 'EEEE, MMMM d, yyyy',
  'MMM d, h:mm a': 'MMM d, h:mm a',
  "yyyy-MM-dd'T'HH:mm:ss": "yyyy-MM-dd'T'HH:mm:ss"
};

interface DateFormatOptions {
  timezone?: string;
  dateFormat?: string;
}

/**
 * Format a date string or Date object according to user preferences
 * @param date - The date to format (string or Date object)
 * @param options - Formatting options (timezone and format)
 * @returns Formatted date string
 */
export function formatDate(
  date: string | Date | null | undefined,
  options: DateFormatOptions = {}
): string {
  if (!date) return '';

  const { 
    timezone = 'UTC', 
    dateFormat = 'MMM d, yyyy HH:mm' 
  } = options;

  try {
    // Parse the date if it's a string
    const dateObj = typeof date === 'string' ? parseISO(date) : date;
    
    // Get the format string for date-fns
    const formatStr = formatMap[dateFormat] || dateFormat;
    
    // Format the date in the specified timezone
    if (timezone && timezone !== 'UTC') {
      return formatInTimeZone(dateObj, timezone, formatStr);
    }
    
    // For UTC or no timezone specified, use regular format
    return format(dateObj, formatStr);
  } catch (error) {
    console.error('Error formatting date:', error, { date, timezone, dateFormat });
    // Fallback to native date formatting
    return new Date(date).toLocaleString();
  }
}

/**
 * Get the current time in a specific timezone
 * @param timezone - The timezone to get the current time for
 * @returns Current time as a Date object in the specified timezone
 */
export function getCurrentTimeInTimezone(timezone: string): Date {
  return toZonedTime(new Date(), timezone);
}

/**
 * Format a date for display in a consistent short format (used in tables/lists)
 * @param date - The date to format
 * @param timezone - User's timezone preference
 * @returns Formatted date string
 */
export function formatShortDate(
  date: string | Date | null | undefined,
  timezone: string = 'UTC'
): string {
  if (!date) return '';
  
  return formatDate(date, {
    timezone,
    dateFormat: 'MMM d, yyyy'
  });
}

/**
 * Format a date for display with full date and time
 * @param date - The date to format
 * @param timezone - User's timezone preference
 * @param dateFormat - User's date format preference
 * @returns Formatted date string
 */
export function formatFullDateTime(
  date: string | Date | null | undefined,
  timezone: string = 'UTC',
  dateFormat: string = 'MMM d, yyyy HH:mm'
): string {
  return formatDate(date, { timezone, dateFormat });
}