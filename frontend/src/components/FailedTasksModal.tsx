import React, { useState, useEffect } from "react";
import { Dialog } from "@headlessui/react";
import { motion } from "framer-motion";
import {
  XMarkIcon,
  ExclamationTriangleIcon,
  TrashIcon,
  MagnifyingGlassIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
} from "@heroicons/react/24/outline";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "../utils/api";
import LoadingSpinner from "./LoadingSpinner";
import { formatDate } from "../utils/dateFormat";
import { useTimezone } from "../contexts/TimezoneContext";

interface TaskStatus {
  id: number;
  user_id: number | null;
  task_id: string;
  task_name: string;
  status: string;
  result: any | null;
  error_message: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

interface FailedTasksResponse {
  tasks: TaskStatus[];
  total: number;
  page: number;
  per_page: number;
  pages: number;
}

interface FailedTasksModalProps {
  isOpen: boolean;
  onClose: () => void;
}

const FailedTasksModal: React.FC<FailedTasksModalProps> = ({ isOpen, onClose }) => {
  const { timezone, dateFormat } = useTimezone();
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [clearingPage, setClearingPage] = useState(false);

  // Fetch failed tasks
  const { data, isLoading, refetch } = useQuery<FailedTasksResponse>({
    queryKey: ["failed-tasks", page, search],
    queryFn: async () => {
      const params = new URLSearchParams({
        page: page.toString(),
        per_page: "20",
      });
      if (search) params.append("search", search);
      
      const response = await api.get(`/task-status/failed?${params}`);
      return response.data;
    },
    enabled: isOpen,
  });

  // Clear single task mutation
  const clearTaskMutation = useMutation({
    mutationFn: async (taskId: number) => {
      await api.delete(`/task-status/${taskId}`);
    },
    onSuccess: () => {
      refetch();
      queryClient.invalidateQueries({ queryKey: ["dashboard-enhanced-stats"] });
    },
  });


  // Reset page when search changes
  useEffect(() => {
    setPage(1);
  }, [search]);

  const getTaskTypeLabel = (taskName: string) => {
    if (taskName.includes("process_store_orders")) return "Order Processing";
    if (taskName.includes("fraud_analysis")) return "Fraud Detection";
    if (taskName.includes("cleanup")) return "Cleanup";
    if (taskName.includes("sync")) return "Synchronization";
    return taskName;
  };

  const truncateError = (error: string | null, maxLength: number = 150) => {
    if (!error) return "Unknown error";
    if (error.length <= maxLength) return error;
    return error.substring(0, maxLength) + "...";
  };

  return (
    <Dialog open={isOpen} onClose={onClose} className="relative z-50">
      <div className="fixed inset-0 bg-black/30" aria-hidden="true" />
      
      <div className="fixed inset-0 flex items-center justify-center p-4">
        <Dialog.Panel className="mx-auto max-w-4xl w-full bg-white dark:bg-dark-100 rounded-lg shadow-xl">
          {/* Header */}
          <div className="flex items-center justify-between p-6 border-b border-gray-200 dark:border-dark-300">
            <Dialog.Title className="text-lg font-semibold text-gray-900 dark:text-dark-800">
              Failed Tasks
            </Dialog.Title>
            <button
              onClick={onClose}
              className="text-gray-400 hover:text-gray-500 dark:text-dark-400 dark:hover:text-dark-500"
            >
              <XMarkIcon className="h-6 w-6" />
            </button>
          </div>

          {/* Search and Actions */}
          <div className="p-6 border-b border-gray-200 dark:border-dark-300">
            <div className="flex items-center justify-between space-x-4">
              <div className="flex-1 relative">
                <MagnifyingGlassIcon className="absolute left-3 top-1/2 transform -translate-y-1/2 h-5 w-5 text-gray-400" />
                <input
                  type="text"
                  placeholder="Search tasks or errors..."
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  className="w-full pl-10 pr-4 py-2 border border-gray-300 dark:border-dark-300 rounded-md focus:ring-shopify-500 focus:border-shopify-500 dark:bg-dark-50 dark:text-dark-800"
                />
              </div>
              {data && data.total > 0 && (
                <div className="flex items-center space-x-2">
                  <button
                    onClick={() => {
                      // Clear only the current page as a workaround
                      if (data.tasks.length > 0) {
                        setClearingPage(true);
                        Promise.all(
                          data.tasks.map(task => 
                            api.delete(`/task-status/${task.id}`).catch(err => {
                              // Ignore 404 errors - task was already deleted
                              if (err.response?.status !== 404) {
                                console.error(`Failed to delete task ${task.id}:`, err);
                              }
                            })
                          )
                        ).then(() => {
                          refetch();
                          queryClient.invalidateQueries({ queryKey: ["dashboard-enhanced-stats"] });
                        }).finally(() => {
                          setClearingPage(false);
                        });
                      }
                    }}
                    disabled={clearingPage}
                    className="inline-flex items-center px-4 py-2 border border-gray-300 text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50 dark:bg-dark-100 dark:border-dark-300 dark:text-dark-700 dark:hover:bg-dark-200 disabled:opacity-50"
                  >
                    <TrashIcon className="h-4 w-4 mr-2" />
                    {clearingPage ? "Clearing..." : `Clear Current Page (${data.tasks.length})`}
                  </button>
                </div>
              )}
            </div>
          </div>

          {/* Content */}
          <div className="p-6 max-h-[500px] overflow-y-auto">
            {isLoading ? (
              <div className="flex items-center justify-center py-12">
                <LoadingSpinner size="lg" />
              </div>
            ) : !data || data.tasks.length === 0 ? (
              <div className="text-center py-12">
                <ExclamationTriangleIcon className="h-12 w-12 text-gray-300 dark:text-dark-300 mx-auto mb-4" />
                <p className="text-gray-500 dark:text-dark-400">No failed tasks found</p>
              </div>
            ) : (
              <div className="space-y-4">
                {data.tasks.map((task) => (
                  <motion.div
                    key={task.id}
                    initial={{ opacity: 0, y: -10 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="border border-gray-200 dark:border-dark-300 rounded-lg p-4 hover:shadow-md transition-shadow"
                  >
                    <div className="flex items-start justify-between">
                      <div className="flex-1">
                        <div className="flex items-center space-x-2">
                          <span className="font-medium text-gray-900 dark:text-dark-800">
                            {getTaskTypeLabel(task.task_name)}
                          </span>
                          <span className="text-xs text-gray-500 dark:text-dark-400">
                            {formatDate(task.created_at, { dateFormat })}
                          </span>
                        </div>
                        <p className="mt-1 text-sm text-red-600 dark:text-red-400">
                          {truncateError(task.error_message)}
                        </p>
                        <div className="mt-2 flex items-center space-x-4 text-xs text-gray-500 dark:text-dark-400">
                          <span>Task ID: {task.task_id.substring(0, 8)}...</span>
                          {task.started_at && (
                            <span>Started: {formatDate(task.started_at, { timezone, dateFormat: "MMM d, h:mm a" })}</span>
                          )}
                        </div>
                      </div>
                      <button
                        onClick={() => clearTaskMutation.mutate(task.id)}
                        disabled={clearTaskMutation.isPending}
                        className="ml-4 text-gray-400 hover:text-red-600 dark:text-dark-400 dark:hover:text-red-400"
                      >
                        <TrashIcon className="h-5 w-5" />
                      </button>
                    </div>
                  </motion.div>
                ))}
              </div>
            )}
          </div>

          {/* Pagination */}
          {data && data.pages > 1 && (
            <div className="flex items-center justify-between p-6 border-t border-gray-200 dark:border-dark-300">
              <div className="text-sm text-gray-700 dark:text-dark-600">
                Showing {(page - 1) * data.per_page + 1} to{" "}
                {Math.min(page * data.per_page, data.total)} of {data.total} tasks
              </div>
              <div className="flex items-center space-x-2">
                <button
                  onClick={() => setPage(page - 1)}
                  disabled={page === 1}
                  className="p-2 text-gray-400 hover:text-gray-500 disabled:opacity-50 disabled:cursor-not-allowed dark:text-dark-400 dark:hover:text-dark-500"
                >
                  <ChevronLeftIcon className="h-5 w-5" />
                </button>
                <span className="text-sm text-gray-700 dark:text-dark-600">
                  Page {page} of {data.pages}
                </span>
                <button
                  onClick={() => setPage(page + 1)}
                  disabled={page === data.pages}
                  className="p-2 text-gray-400 hover:text-gray-500 disabled:opacity-50 disabled:cursor-not-allowed dark:text-dark-400 dark:hover:text-dark-500"
                >
                  <ChevronRightIcon className="h-5 w-5" />
                </button>
              </div>
            </div>
          )}
        </Dialog.Panel>
      </div>
    </Dialog>
  );
};

export default FailedTasksModal;