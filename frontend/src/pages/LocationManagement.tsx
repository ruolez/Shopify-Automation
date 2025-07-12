import React, { useState } from 'react';
import { motion } from 'framer-motion';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { TrashIcon, PencilIcon, MapPinIcon } from '@heroicons/react/24/outline';
import toast from 'react-hot-toast';
import api from '../utils/api';
import LoadingSpinner from '../components/LoadingSpinner';

interface LocationAlias {
  id: number;
  alias_name: string;
  description?: string;
  is_active: boolean;
  created_at: string;
  updated_at?: string;
  mappings: LocationMapping[];
}

interface LocationMapping {
  id: number;
  store_id: number;
  store_name: string;
  store_domain: string;
  shopify_location_id: string;
  shopify_location_name: string;
  is_active: boolean;
  created_at: string;
}

interface StoreLocation {
  store_id: number;
  store_name: string;
  store_domain: string;
  locations: Array<{ id: string; name: string }>;
}

const LocationManagement: React.FC = () => {
  const queryClient = useQueryClient();
  const [editingAlias, setEditingAlias] = useState<LocationAlias | null>(null);
  const [assigningLocation, setAssigningLocation] = useState<{ storeId: number; locationId: string; locationName: string; storeName: string } | null>(null);
  const [newAliasName, setNewAliasName] = useState('');
  const [newAliasDescription, setNewAliasDescription] = useState('');

  // Fetch location aliases
  const { data: aliases, isLoading: aliasesLoading } = useQuery<LocationAlias[]>({
    queryKey: ['location-aliases'],
    queryFn: async () => {
      const response = await api.get('/location-aliases');
      return response.data;
    },
  });

  // Fetch store locations for mapping
  const { data: storeLocations } = useQuery<StoreLocation[]>({
    queryKey: ['store-locations'],
    queryFn: async () => {
      const response = await api.get('/store-locations');
      return response.data;
    },
  });

  // Create alias mutation
  const createAliasMutation = useMutation({
    mutationFn: async (data: { alias_name: string; description?: string }) => {
      const response = await api.post('/location-aliases', data);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['location-aliases'] });
      toast.success('Location alias created successfully');
      setNewAliasName('');
      setNewAliasDescription('');
    },
    onError: (error: any) => {
      toast.error(error?.response?.data?.detail || 'Failed to create alias');
    },
  });

  // Update alias mutation
  const updateAliasMutation = useMutation({
    mutationFn: async ({ id, data }: { id: number; data: any }) => {
      const response = await api.put(`/location-aliases/${id}`, data);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['location-aliases'] });
      toast.success('Location alias updated successfully');
      setEditingAlias(null);
    },
    onError: (error: any) => {
      toast.error(error?.response?.data?.detail || 'Failed to update alias');
    },
  });

  // Delete alias mutation
  const deleteAliasMutation = useMutation({
    mutationFn: async (id: number) => {
      await api.delete(`/location-aliases/${id}`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['location-aliases'] });
      toast.success('Location alias deleted successfully');
    },
    onError: (error: any) => {
      toast.error(error?.response?.data?.detail || 'Failed to delete alias');
    },
  });

  // Create mapping mutation
  const createMappingMutation = useMutation({
    mutationFn: async ({ aliasId, mapping }: { aliasId: number; mapping: any }) => {
      const response = await api.post(`/location-aliases/${aliasId}/mappings`, mapping);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['location-aliases'] });
      toast.success('Location mapping created successfully');
    },
    onError: (error: any) => {
      toast.error(error?.response?.data?.detail || 'Failed to create mapping');
    },
  });


  const handleUpdateAlias = (alias: LocationAlias, updates: any) => {
    updateAliasMutation.mutate({ id: alias.id, data: updates });
  };

  const handleDeleteAlias = (id: number) => {
    if (confirm('Are you sure you want to delete this alias and all its mappings?')) {
      deleteAliasMutation.mutate(id);
    }
  };

  const handleCreateMapping = async (aliasId: number, storeId: number, locationId: string, locationName: string) => {
    try {
      await createMappingMutation.mutateAsync({
        aliasId,
        mapping: {
          store_id: storeId,
          shopify_location_id: locationId,
          shopify_location_name: locationName,
        },
      });
    } catch (error) {
      // Error already handled by mutation
      throw error;
    }
  };


  if (aliasesLoading) {
    return <LoadingSpinner />;
  }

  return (
    <div className="container mx-auto px-4 py-8">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="mb-8"
      >
        <h1 className="text-3xl font-bold text-gray-900 dark:text-dark-800 mb-4">Location Management</h1>
        <p className="text-gray-600 dark:text-dark-500">
          Assign aliases to your Shopify fulfillment locations for consistent rule management across all your stores.
        </p>
      </motion.div>

      {/* Fulfillment Locations from Stores */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1 }}
        className="card mb-8"
      >
        <h2 className="text-xl font-semibold text-gray-900 dark:text-dark-800 mb-6">Fulfillment Locations from Connected Stores</h2>
        
        {storeLocations && storeLocations.length > 0 ? (
          <div className="space-y-6">
            {storeLocations.map((store) => (
              <div key={store.store_id} className="border border-gray-200 dark:border-dark-200 rounded-lg p-4">
                <div className="mb-4">
                  <h3 className="font-medium text-gray-900 dark:text-dark-800">{store.store_name}</h3>
                  <p className="text-sm text-gray-500 dark:text-dark-400">{store.store_domain}</p>
                </div>
                
                {store.locations.length > 0 ? (
                  <div className="space-y-3">
                    {store.locations.map((location) => {
                      // Check if this location already has an alias
                      const existingMapping = aliases?.find(alias => 
                        alias.mappings.some(mapping => 
                          mapping.store_id === store.store_id && 
                          mapping.shopify_location_id === location.id
                        )
                      );
                      
                      return (
                        <div key={location.id} className="flex items-center justify-between p-3 bg-gray-50 dark:bg-dark-50 rounded">
                          <div>
                            <div className="font-medium text-gray-900 dark:text-dark-800">{location.name}</div>
                            <div className="text-xs text-gray-500 dark:text-dark-400">{location.id}</div>
                          </div>
                          
                          <div className="flex items-center gap-3">
                            {existingMapping ? (
                              <span className="badge badge-success">
                                Alias: {existingMapping.alias_name}
                              </span>
                            ) : (
                              <span className="badge badge-gray">No alias assigned</span>
                            )}
                            
                            <button
                              onClick={() => setAssigningLocation({
                                storeId: store.store_id,
                                locationId: location.id,
                                locationName: location.name,
                                storeName: store.store_name
                              })}
                              className="btn-secondary btn-sm"
                            >
                              {existingMapping ? 'Change Alias' : 'Assign Alias'}
                            </button>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <div className="text-sm text-gray-500 dark:text-dark-400 italic">
                    No fulfillment locations found for this store
                  </div>
                )}
              </div>
            ))}
          </div>
        ) : (
          <div className="text-center py-8 text-gray-500 dark:text-dark-400">
            No connected stores found. Please connect your Shopify stores first.
          </div>
        )}
      </motion.div>

      {/* Existing Aliases Section */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.2 }}
        className="card mb-8"
      >
        <h2 className="text-xl font-semibold text-gray-900 dark:text-dark-800 mb-6">Location Aliases</h2>


        {/* Aliases List */}
        <div className="space-y-4">
          {aliases?.map((alias) => (
            <div key={alias.id} className="border border-gray-200 dark:border-dark-200 rounded-lg p-4">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center">
                  <MapPinIcon className="h-5 w-5 text-shopify-600 mr-2" />
                  <div>
                    <h3 className="font-medium text-gray-900 dark:text-dark-800">{alias.alias_name}</h3>
                    {alias.description && (
                      <p className="text-sm text-gray-500 dark:text-dark-400">{alias.description}</p>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <span className={`badge ${alias.is_active ? 'badge-success' : 'badge-gray'}`}>
                    {alias.is_active ? 'Active' : 'Inactive'}
                  </span>
                  <button
                    onClick={() => setEditingAlias(alias)}
                    className="p-1 text-gray-400 dark:text-dark-400 hover:text-gray-600 dark:hover:text-dark-600"
                  >
                    <PencilIcon className="h-4 w-4" />
                  </button>
                  <button
                    onClick={() => handleDeleteAlias(alias.id)}
                    className="p-1 text-red-400 hover:text-red-600"
                  >
                    <TrashIcon className="h-4 w-4" />
                  </button>
                </div>
              </div>

              {/* Mapping Status */}
              <div className="bg-gray-50 dark:bg-dark-200 p-3 rounded">
                <div className="text-sm text-gray-600 dark:text-dark-500 mb-2">
                  Mapped to {alias.mappings.length} store{alias.mappings.length !== 1 ? 's' : ''}
                </div>
                <div className="flex flex-wrap gap-2">
                  {alias.mappings.map((mapping) => (
                    <span key={mapping.id} className="badge badge-shopify">
                      {mapping.store_name}: {mapping.shopify_location_name}
                    </span>
                  ))}
                  {alias.mappings.length === 0 && (
                    <span className="text-sm text-amber-600">No mappings configured</span>
                  )}
                </div>
              </div>
            </div>
          ))}

          {aliases?.length === 0 && (
            <div className="text-center py-8 text-gray-500">
              No location aliases created yet. Create your first alias to get started.
            </div>
          )}
        </div>
      </motion.div>

      {/* Assign Alias Modal */}
      {assigningLocation && (
        <div className="fixed inset-0 bg-black/50 dark:bg-black/70 flex items-center justify-center z-50">
          <div className="bg-white dark:bg-dark-100 rounded-lg p-6 max-w-md w-full mx-4">
            <h3 className="text-lg font-medium mb-4">
              Assign Alias to Location
            </h3>
            
            <div className="mb-4 p-3 bg-gray-50 rounded">
              <div className="text-sm text-gray-600">Store: {assigningLocation.storeName}</div>
              <div className="font-medium">{assigningLocation.locationName}</div>
              <div className="text-xs text-gray-500">{assigningLocation.locationId}</div>
            </div>
            
            <div className="space-y-4 mb-6">
              <div>
                <label className="label">Choose existing alias or create new</label>
                <select
                  value=""
                  onChange={(e) => {
                    if (e.target.value === "new") {
                      setNewAliasName('');
                    } else if (e.target.value) {
                      // Use existing alias
                      const aliasId = parseInt(e.target.value);
                      handleCreateMapping(aliasId, assigningLocation.storeId, assigningLocation.locationId, assigningLocation.locationName);
                      setAssigningLocation(null);
                    }
                  }}
                  className="input"
                >
                  <option value="">Select option...</option>
                  <option value="new">+ Create New Alias</option>
                  {aliases?.filter(alias => alias.is_active).map((alias) => (
                    <option key={alias.id} value={alias.id}>
                      {alias.alias_name}
                    </option>
                  ))}
                </select>
              </div>
              
              {newAliasName !== undefined && (
                <>
                  <div>
                    <label className="label">New Alias Name</label>
                    <input
                      type="text"
                      value={newAliasName}
                      onChange={(e) => setNewAliasName(e.target.value)}
                      className="input"
                      placeholder="e.g., Main Warehouse, East Coast Hub"
                      autoFocus
                    />
                  </div>
                  <div>
                    <label className="label">Description (Optional)</label>
                    <input
                      type="text"
                      value={newAliasDescription}
                      onChange={(e) => setNewAliasDescription(e.target.value)}
                      className="input"
                      placeholder="Brief description of this location"
                    />
                  </div>
                </>
              )}
            </div>
            
            <div className="flex gap-2">
              {newAliasName !== undefined && (
                <button
                  onClick={async () => {
                    if (!newAliasName.trim()) return;
                    
                    try {
                      // Create new alias first
                      const aliasResponse = await createAliasMutation.mutateAsync({
                        alias_name: newAliasName.trim(),
                        description: newAliasDescription.trim() || undefined,
                      });
                      
                      // Then create mapping
                      await handleCreateMapping(aliasResponse.id, assigningLocation.storeId, assigningLocation.locationId, assigningLocation.locationName);
                      
                      setAssigningLocation(null);
                      setNewAliasName('');
                      setNewAliasDescription('');
                    } catch (error) {
                      // Error already handled by mutation
                    }
                  }}
                  disabled={!newAliasName.trim() || createAliasMutation.isPending}
                  className="btn-primary"
                >
                  {createAliasMutation.isPending ? 'Creating...' : 'Create & Assign'}
                </button>
              )}
              <button
                onClick={() => {
                  setAssigningLocation(null);
                  setNewAliasName('');
                  setNewAliasDescription('');
                }}
                className="btn-secondary"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Edit Alias Modal */}
      {editingAlias && (
        <div className="fixed inset-0 bg-black/50 dark:bg-black/70 flex items-center justify-center z-50">
          <div className="bg-white dark:bg-dark-100 rounded-lg p-6 max-w-md w-full mx-4">
            <h3 className="text-lg font-medium mb-4">Edit Location Alias</h3>
            
            <div className="space-y-4 mb-6">
              <div>
                <label className="label">Alias Name</label>
                <input
                  type="text"
                  value={editingAlias.alias_name}
                  onChange={(e) => setEditingAlias({ ...editingAlias, alias_name: e.target.value })}
                  className="input"
                />
              </div>
              <div>
                <label className="label">Description</label>
                <input
                  type="text"
                  value={editingAlias.description || ''}
                  onChange={(e) => setEditingAlias({ ...editingAlias, description: e.target.value })}
                  className="input"
                />
              </div>
              <div className="flex items-center">
                <input
                  type="checkbox"
                  id="is_active"
                  checked={editingAlias.is_active}
                  onChange={(e) => setEditingAlias({ ...editingAlias, is_active: e.target.checked })}
                  className="mr-2"
                />
                <label htmlFor="is_active" className="text-sm">Active</label>
              </div>
            </div>
            
            <div className="flex gap-2">
              <button
                onClick={() => handleUpdateAlias(editingAlias, {
                  alias_name: editingAlias.alias_name,
                  description: editingAlias.description,
                  is_active: editingAlias.is_active,
                })}
                disabled={updateAliasMutation.isPending}
                className="btn-primary"
              >
                {updateAliasMutation.isPending ? 'Updating...' : 'Update'}
              </button>
              <button
                onClick={() => setEditingAlias(null)}
                className="btn-secondary"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default LocationManagement;