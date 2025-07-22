import React, { useState } from "react";
import { motion } from "framer-motion";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Dialog, Switch } from "@headlessui/react";
import {
  PlusIcon,
  TrashIcon,
  XMarkIcon,
  ArrowPathIcon,
} from "@heroicons/react/24/outline";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import toast from "react-hot-toast";
import api from "../utils/api";
import { Store, StoreForm } from "../types";
import LoadingSpinner from "../components/LoadingSpinner";
import { formatShortDate } from "../utils/dateFormat";
import { useTimezone } from "../contexts/TimezoneContext";

const storeSchema = z.object({
  shop_domain: z.string().min(1, "Store name is required"),
  access_token: z.string().min(1, "Access token is required"),
});

const Stores: React.FC = () => {
  const [isModalOpen, setIsModalOpen] = useState(false);
  const queryClient = useQueryClient();
  const { timezone } = useTimezone();

  const { data: stores, isLoading } = useQuery<Store[]>({
    queryKey: ["stores"],
    queryFn: async () => {
      const response = await api.get("/stores");
      return response.data;
    },
  });

  const createStoreMutation = useMutation({
    mutationFn: async (data: StoreForm) => {
      const response = await api.post("/stores", data);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["stores"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard-stats"] });
      setIsModalOpen(false);
      reset();
      toast.success("Store connected successfully!");
    },
    onError: (error: any) => {
      toast.error(error.response?.data?.detail || "Failed to connect store");
    },
  });

  const deleteStoreMutation = useMutation({
    mutationFn: async (storeId: number) => {
      await api.delete(`/stores/${storeId}`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["stores"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard-stats"] });
      toast.success("Store removed successfully");
    },
    onError: (error: any) => {
      toast.error(error.response?.data?.detail || "Failed to remove store");
    },
  });

  const syncStoreMutation = useMutation({
    mutationFn: async (storeId: number) => {
      const response = await api.post(`/sync/store/${storeId}`);
      return response.data;
    },
    onSuccess: (data) => {
      toast.success(`Sync started for ${data.store_name}`);
    },
    onError: (error: any) => {
      toast.error(error.response?.data?.detail || "Failed to start sync");
    },
  });

  const toggleStoreMutation = useMutation({
    mutationFn: async (storeId: number) => {
      const response = await api.put(`/stores/${storeId}/toggle-active`);
      return response.data;
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["stores"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard-stats"] });
      toast.success(data.message);
    },
    onError: (error: any) => {
      toast.error(
        error.response?.data?.detail || "Failed to toggle store status",
      );
    },
  });

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<StoreForm>({
    resolver: zodResolver(storeSchema),
  });

  const onSubmit = (data: StoreForm) => {
    // Clean the store name and ensure proper format
    let storeName = data.shop_domain.trim().toLowerCase();
    
    // If user accidentally included .myshopify.com, remove it
    if (storeName.endsWith('.myshopify.com')) {
      storeName = storeName.replace('.myshopify.com', '');
    }
    
    // If user included any dots, show error
    if (storeName.includes('.')) {
      toast.error("Please enter only the store name without the domain");
      return;
    }
    
    // Submit with cleaned store name
    createStoreMutation.mutate({
      ...data,
      shop_domain: storeName
    });
  };

  const handleDeleteStore = (storeId: number) => {
    if (window.confirm("Are you sure you want to remove this store?")) {
      deleteStoreMutation.mutate(storeId);
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <LoadingSpinner size="lg" />
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900 dark:text-dark-800">
            Stores
          </h1>
          <p className="mt-2 text-gray-600 dark:text-dark-500">
            Manage your connected Shopify stores
          </p>
        </div>
        <button
          onClick={() => setIsModalOpen(true)}
          className="btn-primary flex items-center"
        >
          <PlusIcon className="h-5 w-5 mr-2" />
          Connect Store
        </button>
      </div>

      {stores && stores.length > 0 ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {stores.map((store, index) => (
            <motion.div
              key={store.id}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: index * 0.1 }}
              className="card"
            >
              <div className="flex items-start justify-between">
                <div className="flex-1">
                  <h3 className="text-lg font-medium text-gray-900 dark:text-dark-800">
                    {store.shop_name}
                  </h3>
                  <p className="text-sm text-gray-500 dark:text-dark-400">
                    {store.shop_domain}
                  </p>
                  <div className="mt-3 flex items-center">
                    <span
                      className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                        store.is_active
                          ? "bg-green-100 text-green-800 dark:bg-green-900/20 dark:text-green-400"
                          : "bg-red-100 text-red-800 dark:bg-red-900/20 dark:text-red-400"
                      }`}
                    >
                      {store.is_active ? "Active" : "Inactive"}
                    </span>
                  </div>
                  {store.last_sync && (
                    <p className="text-xs text-gray-400 dark:text-dark-300 mt-2">
                      Last sync: {formatShortDate(store.last_sync, timezone)}
                    </p>
                  )}
                </div>
                <div className="flex items-center space-x-3">
                  <Switch
                    checked={store.is_active}
                    onChange={() => toggleStoreMutation.mutate(store.id)}
                    disabled={toggleStoreMutation.isPending}
                    className={`${
                      store.is_active ? "bg-shopify-600" : "bg-gray-200"
                    } relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none disabled:opacity-50`}
                    title={
                      store.is_active ? "Deactivate store" : "Activate store"
                    }
                  >
                    <span className="sr-only">Toggle store active status</span>
                    <span
                      className={`${
                        store.is_active ? "translate-x-6" : "translate-x-1"
                      } inline-block h-4 w-4 transform rounded-full bg-white transition-transform`}
                    />
                  </Switch>
                  <button
                    onClick={() => syncStoreMutation.mutate(store.id)}
                    disabled={syncStoreMutation.isPending}
                    className="text-shopify-600 hover:text-shopify-700 p-1"
                    title="Sync orders"
                  >
                    <ArrowPathIcon
                      className={`h-5 w-5 ${syncStoreMutation.isPending ? "animate-spin" : ""}`}
                    />
                  </button>
                  <button
                    onClick={() => handleDeleteStore(store.id)}
                    className="text-red-400 hover:text-red-500 p-1"
                    title="Remove store"
                  >
                    <TrashIcon className="h-5 w-5" />
                  </button>
                </div>
              </div>
            </motion.div>
          ))}
        </div>
      ) : (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="text-center py-12"
        >
          <div className="max-w-md mx-auto">
            <div className="mx-auto h-12 w-12 text-gray-400">
              <svg fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={1}
                  d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4"
                />
              </svg>
            </div>
            <h3 className="mt-2 text-sm font-medium text-gray-900 dark:text-dark-800">
              No stores
            </h3>
            <p className="mt-1 text-sm text-gray-500 dark:text-dark-400">
              Get started by connecting your first Shopify store.
            </p>
            <div className="mt-6">
              <button
                onClick={() => setIsModalOpen(true)}
                className="btn-primary"
              >
                <PlusIcon className="h-5 w-5 mr-2" />
                Connect Store
              </button>
            </div>
          </div>
        </motion.div>
      )}

      {/* Add Store Modal */}
      <Dialog
        open={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        className="relative z-50"
      >
        <div className="modal-overlay" aria-hidden="true" />
        <div className="fixed inset-0 flex items-center justify-center p-4">
          <Dialog.Panel className="modal-content max-w-md w-full p-6">
            <div className="flex items-center justify-between mb-4">
              <Dialog.Title className="text-lg font-medium text-gray-900 dark:text-dark-800">
                Connect Shopify Store
              </Dialog.Title>
              <button
                onClick={() => setIsModalOpen(false)}
                className="text-gray-400 hover:text-gray-500 dark:text-dark-400 dark:hover:text-dark-500"
              >
                <XMarkIcon className="h-6 w-6" />
              </button>
            </div>

            <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
              <div>
                <label className="label">Store Name</label>
                <input
                  {...register("shop_domain")}
                  type="text"
                  className="input"
                  placeholder="your-shop"
                />
                {errors.shop_domain && (
                  <p className="mt-1 text-sm text-red-600">
                    {errors.shop_domain.message}
                  </p>
                )}
                <p className="mt-1 text-xs text-gray-500 dark:text-dark-400">
                  Enter only the store name. We'll add .myshopify.com automatically.
                </p>
              </div>

              <div>
                <label className="label">Admin API Access Token</label>
                <input
                  {...register("access_token")}
                  type="password"
                  className="input"
                  placeholder="Enter your access token"
                />
                {errors.access_token && (
                  <p className="mt-1 text-sm text-red-600">
                    {errors.access_token.message}
                  </p>
                )}
              </div>

              <div className="text-sm text-gray-500 dark:text-dark-400">
                <p>
                  To get an access token, create a private app in your Shopify
                  admin and copy the Admin API access token.
                </p>
              </div>

              <div className="flex justify-end space-x-3 pt-4">
                <button
                  type="button"
                  onClick={() => setIsModalOpen(false)}
                  className="btn-secondary"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={createStoreMutation.isPending}
                  className="btn-primary"
                >
                  {createStoreMutation.isPending ? (
                    <LoadingSpinner size="sm" />
                  ) : (
                    "Connect Store"
                  )}
                </button>
              </div>
            </form>
          </Dialog.Panel>
        </div>
      </Dialog>
    </div>
  );
};

export default Stores;
