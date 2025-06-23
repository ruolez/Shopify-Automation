import React, { useState } from 'react';
import { motion } from 'framer-motion';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Dialog } from '@headlessui/react';
import { PlusIcon, TrashIcon, XMarkIcon, ArrowPathIcon } from '@heroicons/react/24/outline';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import toast from 'react-hot-toast';
import api from '../utils/api';
import { Store, StoreForm } from '../types';
import LoadingSpinner from '../components/LoadingSpinner';

const storeSchema = z.object({
  shop_domain: z.string().min(1, 'Shop domain is required'),
  access_token: z.string().min(1, 'Access token is required'),
});

const Stores: React.FC = () => {
  const [isModalOpen, setIsModalOpen] = useState(false);
  const queryClient = useQueryClient();

  const { data: stores, isLoading } = useQuery<Store[]>({
    queryKey: ['stores'],
    queryFn: async () => {
      const response = await api.get('/stores');
      return response.data;
    },
  });

  const createStoreMutation = useMutation({
    mutationFn: async (data: StoreForm) => {
      const response = await api.post('/stores', data);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['stores'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard-stats'] });
      setIsModalOpen(false);
      reset();
      toast.success('Store connected successfully!');
    },
    onError: (error: any) => {
      toast.error(error.response?.data?.detail || 'Failed to connect store');
    },
  });

  const deleteStoreMutation = useMutation({
    mutationFn: async (storeId: number) => {
      await api.delete(`/stores/${storeId}`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['stores'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard-stats'] });
      toast.success('Store removed successfully');
    },
    onError: (error: any) => {
      toast.error(error.response?.data?.detail || 'Failed to remove store');
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
      toast.error(error.response?.data?.detail || 'Failed to start sync');
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
    createStoreMutation.mutate(data);
  };

  const handleDeleteStore = (storeId: number) => {
    if (window.confirm('Are you sure you want to remove this store?')) {
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
          <h1 className="text-3xl font-bold text-gray-900">Stores</h1>
          <p className="mt-2 text-gray-600">
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
                  <h3 className="text-lg font-medium text-gray-900">
                    {store.shop_name}
                  </h3>
                  <p className="text-sm text-gray-500">{store.shop_domain}</p>
                  <div className="mt-3 flex items-center">
                    <span
                      className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                        store.is_active
                          ? 'bg-green-100 text-green-800'
                          : 'bg-red-100 text-red-800'
                      }`}
                    >
                      {store.is_active ? 'Active' : 'Inactive'}
                    </span>
                  </div>
                  {store.last_sync && (
                    <p className="text-xs text-gray-400 mt-2">
                      Last sync: {new Date(store.last_sync).toLocaleDateString()}
                    </p>
                  )}
                </div>
                <div className="flex items-center space-x-2">
                  <button
                    onClick={() => syncStoreMutation.mutate(store.id)}
                    disabled={syncStoreMutation.isPending}
                    className="text-shopify-600 hover:text-shopify-700 p-1"
                    title="Sync orders"
                  >
                    <ArrowPathIcon className={`h-5 w-5 ${syncStoreMutation.isPending ? 'animate-spin' : ''}`} />
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
            <h3 className="mt-2 text-sm font-medium text-gray-900">No stores</h3>
            <p className="mt-1 text-sm text-gray-500">
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
        <div className="fixed inset-0 bg-black/30" aria-hidden="true" />
        <div className="fixed inset-0 flex items-center justify-center p-4">
          <Dialog.Panel className="bg-white rounded-lg shadow-xl max-w-md w-full p-6">
            <div className="flex items-center justify-between mb-4">
              <Dialog.Title className="text-lg font-medium text-gray-900">
                Connect Shopify Store
              </Dialog.Title>
              <button
                onClick={() => setIsModalOpen(false)}
                className="text-gray-400 hover:text-gray-500"
              >
                <XMarkIcon className="h-6 w-6" />
              </button>
            </div>

            <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
              <div>
                <label className="label">Shop Domain</label>
                <input
                  {...register('shop_domain')}
                  type="text"
                  className="input"
                  placeholder="your-shop.myshopify.com"
                />
                {errors.shop_domain && (
                  <p className="mt-1 text-sm text-red-600">
                    {errors.shop_domain.message}
                  </p>
                )}
              </div>

              <div>
                <label className="label">Admin API Access Token</label>
                <input
                  {...register('access_token')}
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

              <div className="text-sm text-gray-500">
                <p>
                  To get an access token, create a private app in your Shopify admin
                  and copy the Admin API access token.
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
                    'Connect Store'
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