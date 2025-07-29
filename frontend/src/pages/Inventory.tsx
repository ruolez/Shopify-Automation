import React, { useState, useEffect, useRef } from "react";
import { motion } from "framer-motion";
import {
  PencilIcon,
  CheckIcon,
  XMarkIcon,
  ArrowPathIcon,
  ChevronDownIcon,
  ChevronUpIcon,
  MapPinIcon,
  InformationCircleIcon,
} from "@heroicons/react/24/outline";
import { Listbox, Transition } from "@headlessui/react";
import toast from "react-hot-toast";
import api from "../utils/api";
import LoadingSpinner from "../components/LoadingSpinner";

interface InventoryQuantities {
  available: number;
  on_hand: number;
  committed: number;
  verification_quantity?: number;
  verification_metadata?: {
    orders_processed: number;
    days_back: number;
    excluded_tag?: string;
    error?: string;
  };
}

interface InventoryLevel {
  store_id: number;
  store_name: string;
  location_id: string;
  location_name: string;
  location_alias?: string;
  quantities: InventoryQuantities;
  inventory_item_id?: string;  // Store-specific inventory item ID
}

interface ProductVariant {
  variant_id: string;
  title: string;
  sku?: string;
  barcode?: string;
  product_id: string;
  product_title: string;
  inventory_item_id: string;
}

interface InventoryData {
  barcode: string;
  variants: ProductVariant[];
  inventory_levels: InventoryLevel[];
  verification_summary?: {
    total_quantity: number;
    excluded_tag?: string;
    details: Array<{
      store_id: number;
      quantity: number;
      orders_processed: number;
      error?: string;
    }>;
  };
}

interface EditingCell {
  storeId: number;
  locationId: string;
  field: "available" | "on_hand";
  value: number;
}

interface LocationAlias {
  id: number;
  alias_name: string;
  mapping_count: number;
}

const Inventory: React.FC = () => {
  const [barcode, setBarcode] = useState("");
  const [loading, setLoading] = useState(false);
  const [inventoryData, setInventoryData] = useState<InventoryData | null>(null);
  const [editingCells, setEditingCells] = useState<Map<string, EditingCell>>(new Map());
  const [pendingUpdates, setPendingUpdates] = useState<Map<string, EditingCell>>(new Map());
  const [updating, setUpdating] = useState(false);
  const [expandedVariants, setExpandedVariants] = useState<Set<string>>(new Set());
  const [locationAliases, setLocationAliases] = useState<LocationAlias[]>([]);
  const [selectedLocationAliases, setSelectedLocationAliases] = useState<LocationAlias[]>([]);
  const [loadingAliases, setLoadingAliases] = useState(false);
  const [liveQuantity, setLiveQuantity] = useState<string>("");
  const [liveQuantityDifference, setLiveQuantityDifference] = useState<number | null>(null);
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const barcodeInputRef = useRef<HTMLInputElement>(null);
  const liveQuantityInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    loadLocationAliases();
  }, []);

  useEffect(() => {
    // Focus on live quantity input when inventory data is loaded and verification is available
    if (inventoryData && inventoryData.verification_summary && liveQuantityInputRef.current) {
      liveQuantityInputRef.current.focus();
    }
  }, [inventoryData]);

  const loadLocationAliases = async () => {
    setLoadingAliases(true);
    try {
      const response = await api.get("/inventory/location-aliases");
      setLocationAliases(response.data);
    } catch (err: any) {
      console.error("Error loading location aliases:", err);
      toast.error("Failed to load location aliases");
    } finally {
      setLoadingAliases(false);
    }
  };

  const handleSearch = async () => {
    if (!barcode.trim()) {
      toast.error("Please enter a barcode");
      return;
    }

    setLoading(true);
    setInventoryData(null);
    setEditingCells(new Map());
    setPendingUpdates(new Map());
    setLiveQuantity("");
    setLiveQuantityDifference(null);

    try {
      // Build query params with location filter
      const params = new URLSearchParams();
      if (selectedLocationAliases.length > 0) {
        params.append("location_aliases", selectedLocationAliases.map(a => a.alias_name).join(","));
      }
      
      const url = `/inventory/${barcode}/levels${params.toString() ? `?${params.toString()}` : ""}`;
      const response = await api.get(url);
      setInventoryData(response.data);
      
      if (!response.data.variants || response.data.variants.length === 0) {
        toast.error("No products found with this barcode");
      } else {
        // Start with all variants collapsed
        setExpandedVariants(new Set());
        // Removed toast notification for search results
      }
    } catch (err: any) {
      console.error("Search error:", err);
      toast.error(err.response?.data?.detail || "Failed to search inventory");
    } finally {
      setLoading(false);
    }
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") {
      handleSearch();
    }
  };

  const handleLiveQuantitySubmit = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && inventoryData) {
      const quantity = parseInt(liveQuantity);
      
      if (isNaN(quantity)) {
        toast.error("Please enter a valid number");
        return;
      }
      
      // Calculate total verification quantity
      const totalVerification = inventoryData.inventory_levels.reduce(
        (sum, level) => sum + (level.quantities.verification_quantity || 0),
        0
      );
      
      // Calculate difference: live quantity - verification
      const difference = quantity - totalVerification;
      setLiveQuantityDifference(difference);
      
      // Calculate difference without showing toast
    }
  };

  const handleBulkUpdateToCalculatedDifference = async () => {
    if (liveQuantityDifference === null || !inventoryData) {
      return;
    }

    const locationCount = inventoryData.inventory_levels.length;
    
    if (!confirm(`Update available inventory to ${liveQuantityDifference} for ${locationCount} location(s)?`)) {
      return;
    }

    setUpdating(true);

    try {
      // Prepare updates for all displayed inventory levels
      const updates = inventoryData.inventory_levels.map(level => ({
        store_id: level.store_id,
        location_id: level.location_id,
        inventory_item_id: level.inventory_item_id || inventoryData.variants[0]?.inventory_item_id,
        available: liveQuantityDifference
      })).filter(update => update.inventory_item_id); // Filter out any without inventory item ID

      if (updates.length === 0) {
        toast.error("No valid locations to update");
        return;
      }

      const response = await api.put("/inventory/update", { updates });

      if (response.data.successful > 0) {
        toast.success(`Successfully updated inventory at ${response.data.successful} location(s)`);
        
        // Clear the live quantity inputs
        setLiveQuantity("");
        setLiveQuantityDifference(null);
        
        // Focus back on the barcode input and select all text
        if (barcodeInputRef.current) {
          barcodeInputRef.current.focus();
          barcodeInputRef.current.select();
        }
      } else {
        toast.error("Failed to update inventory");
      }
    } catch (err: any) {
      console.error("Bulk update error:", err);
      toast.error(err.response?.data?.detail || "Failed to update inventory");
    } finally {
      setUpdating(false);
    }
  };

  const getCellKey = (storeId: number, locationId: string, field: string) => {
    return `${storeId}-${locationId}-${field}`;
  };

  const handleEdit = (level: InventoryLevel, field: "available" | "on_hand") => {
    const key = getCellKey(level.store_id, level.location_id, field);
    const value = level.quantities[field];
    
    setEditingCells(new Map(editingCells.set(key, {
      storeId: level.store_id,
      locationId: level.location_id,
      field,
      value
    })));
  };

  const handleCancelEdit = (storeId: number, locationId: string, field: string) => {
    const key = getCellKey(storeId, locationId, field);
    const newEditing = new Map(editingCells);
    newEditing.delete(key);
    setEditingCells(newEditing);
  };

  const handleSaveEdit = (storeId: number, locationId: string, field: string) => {
    const key = getCellKey(storeId, locationId, field);
    const editingCell = editingCells.get(key);
    
    if (editingCell) {
      setPendingUpdates(new Map(pendingUpdates.set(key, editingCell)));
      const newEditing = new Map(editingCells);
      newEditing.delete(key);
      setEditingCells(newEditing);
    }
  };

  const handleValueChange = (storeId: number, locationId: string, field: string, value: string) => {
    const key = getCellKey(storeId, locationId, field);
    const numValue = parseInt(value) || 0;
    
    if (numValue < 0) return;
    
    const current = editingCells.get(key);
    if (current) {
      setEditingCells(new Map(editingCells.set(key, {
        ...current,
        value: numValue
      })));
    }
  };

  const handleUpdateAll = async () => {
    if (pendingUpdates.size === 0) {
      toast.error("No changes to update");
      return;
    }

    if (!confirm(`Update inventory at ${pendingUpdates.size} location(s)?`)) {
      return;
    }

    setUpdating(true);

    try {
      // Group updates by store and location
      const updates: any[] = [];

      pendingUpdates.forEach((update) => {
        // Find the inventory level for this location
        const level = inventoryData?.inventory_levels.find(
          l => l.store_id === update.storeId && l.location_id === update.locationId
        );
        
        if (!level) return;

        // Use the store-specific inventory item ID from the level
        const inventoryItemId = level.inventory_item_id || inventoryData?.variants[0]?.inventory_item_id;
        if (!inventoryItemId) return;

        // Check if we already have an update for this location
        const existingUpdate = updates.find(
          u => u.store_id === update.storeId && u.location_id === update.locationId
        );

        if (existingUpdate) {
          // Add the field to existing update
          existingUpdate[update.field] = update.value;
        } else {
          // Create new update entry
          const newUpdate: any = {
            store_id: update.storeId,
            location_id: update.locationId,
            inventory_item_id: inventoryItemId,
          };
          newUpdate[update.field] = update.value;
          updates.push(newUpdate);
        }
      });

      const response = await api.put("/inventory/update", { updates });

      if (response.data.successful > 0) {
        toast.success(`Successfully updated inventory at ${response.data.successful} location(s)`);
        setPendingUpdates(new Map());
        // Refresh the data
        await handleSearch();
      } else {
        toast.error("Failed to update inventory");
      }
    } catch (err: any) {
      console.error("Update error:", err);
      toast.error(err.response?.data?.detail || "Failed to update inventory");
    } finally {
      setUpdating(false);
    }
  };

  const toggleVariant = (variantId: string) => {
    const newExpanded = new Set(expandedVariants);
    if (newExpanded.has(variantId)) {
      newExpanded.delete(variantId);
    } else {
      newExpanded.add(variantId);
    }
    setExpandedVariants(newExpanded);
  };

  const getInventoryLevelsForVariant = (_variantId: string) => {
    // In this implementation, we're showing all inventory levels
    // In a real multi-variant scenario, you'd filter by variant
    return inventoryData?.inventory_levels || [];
  };

  const hasPendingUpdate = (storeId: number, locationId: string, field: string) => {
    const key = getCellKey(storeId, locationId, field);
    return pendingUpdates.has(key);
  };

  const getPendingValue = (storeId: number, locationId: string, field: string) => {
    const key = getCellKey(storeId, locationId, field);
    return pendingUpdates.get(key)?.value;
  };

  return (
    <div className="space-y-6">
      <motion.div
        initial={{ opacity: 0, y: -20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3 }}
      >
        <h1 className="text-2xl sm:text-3xl font-bold text-gray-900 dark:text-dark-700">
          Inventory Update
        </h1>
      </motion.div>

      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3, delay: 0.1 }}
        className="bg-white dark:bg-dark-100 rounded-lg shadow-md p-6"
      >
        <div className="space-y-4">
          {/* Location Filter */}
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-dark-600 mb-2">
              Filter by Location (optional)
            </label>
            <Listbox 
              value={selectedLocationAliases} 
              onChange={(value) => {
                setSelectedLocationAliases(value);
                // Close dropdown after a small delay for smooth transition
                setTimeout(() => {
                  setDropdownOpen(false);
                  // Focus on barcode input after dropdown closes
                  if (barcodeInputRef.current) {
                    barcodeInputRef.current.focus();
                  }
                }, 150);
              }} 
              multiple
            >
              <div className="relative">
                <Listbox.Button 
                  onClick={() => setDropdownOpen(!dropdownOpen)}
                  className="relative w-full cursor-pointer rounded-lg bg-white dark:bg-dark-50 py-2 pl-3 pr-10 text-left border border-gray-300 dark:border-dark-300 focus:outline-none focus:ring-2 focus:ring-shopify-500 dark:focus:ring-shopify-300">
                  <span className="flex items-center">
                    <MapPinIcon className="h-5 w-5 text-gray-400 dark:text-dark-400 mr-2" />
                    <span className="block truncate">
                      {selectedLocationAliases.length === 0
                        ? "All locations"
                        : `${selectedLocationAliases.length} location${selectedLocationAliases.length === 1 ? "" : "s"} selected`}
                    </span>
                  </span>
                  <span className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-2">
                    <ChevronDownIcon className="h-5 w-5 text-gray-400" aria-hidden="true" />
                  </span>
                </Listbox.Button>
                <Transition
                  show={dropdownOpen}
                  leave="transition ease-in duration-100"
                  leaveFrom="opacity-100"
                  leaveTo="opacity-0"
                >
                  <Listbox.Options className="absolute z-10 mt-1 max-h-60 w-full overflow-auto rounded-md bg-white dark:bg-dark-100 py-1 text-base shadow-lg ring-1 ring-black ring-opacity-5 focus:outline-none sm:text-sm">
                    {loadingAliases ? (
                      <div className="px-4 py-2 text-gray-500 dark:text-dark-500">Loading...</div>
                    ) : locationAliases.length === 0 ? (
                      <div className="px-4 py-2 text-gray-500 dark:text-dark-500">No location aliases found</div>
                    ) : (
                      locationAliases.map((alias) => (
                        <Listbox.Option
                          key={alias.id}
                          value={alias}
                          className={({ active }) =>
                            `relative cursor-pointer select-none py-2 pl-10 pr-4 ${
                              active
                                ? "bg-shopify-100 dark:bg-shopify-800/30 text-shopify-900 dark:text-shopify-300"
                                : "text-gray-900 dark:text-dark-700"
                            }`
                          }
                        >
                          {({ selected }) => (
                            <>
                              <span className={`block truncate ${selected ? "font-medium" : "font-normal"}`}>
                                {alias.alias_name}
                                <span className="text-sm text-gray-500 dark:text-dark-500 ml-2">
                                  ({alias.mapping_count} mapping{alias.mapping_count !== 1 ? "s" : ""})
                                </span>
                              </span>
                              {selected ? (
                                <span className="absolute inset-y-0 left-0 flex items-center pl-3 text-shopify-600 dark:text-shopify-400">
                                  <CheckIcon className="h-5 w-5" aria-hidden="true" />
                                </span>
                              ) : null}
                            </>
                          )}
                        </Listbox.Option>
                      ))
                    )}
                  </Listbox.Options>
                </Transition>
              </div>
            </Listbox>
          </div>

          {/* Search Bar */}
          <div className="flex flex-col gap-4">
            <div className="flex flex-col sm:flex-row gap-2">
              <div className="flex-1">
                <div className="relative">
                  <input
                    ref={barcodeInputRef}
                    type="text"
                    value={barcode}
                    onChange={(e) => setBarcode(e.target.value)}
                    onKeyPress={handleKeyPress}
                    placeholder="Enter UPC barcode"
                    className="w-full px-3 py-2 border border-gray-300 dark:border-dark-300 rounded-lg focus:ring-2 focus:ring-shopify-500 dark:focus:ring-shopify-300 focus:border-transparent bg-white dark:bg-dark-50 text-gray-900 dark:text-dark-700 placeholder-gray-500 dark:placeholder-dark-400"
                  />
                </div>
              </div>
            </div>
            {inventoryData && pendingUpdates.size > 0 && (
              <div className="flex flex-col sm:flex-row gap-2">
                <button
                  onClick={handleUpdateAll}
                  disabled={updating}
                  className="px-4 py-2 bg-green-600 hover:bg-green-700 dark:bg-green-500 dark:hover:bg-green-600 text-white rounded-lg transition-colors duration-200 flex items-center justify-center gap-2 text-sm sm:text-base"
                >
                  {updating ? (
                    <>
                      <LoadingSpinner size="sm" />
                      Updating...
                    </>
                  ) : (
                    <>
                      <CheckIcon className="h-5 w-5" />
                      Update All ({pendingUpdates.size})
                    </>
                  )}
                </button>
                <button
                  onClick={() => setPendingUpdates(new Map())}
                  disabled={updating}
                  className="px-4 py-2 bg-gray-600 hover:bg-gray-700 dark:bg-gray-500 dark:hover:bg-gray-600 text-white rounded-lg transition-colors duration-200 text-sm sm:text-base"
                >
                  Clear Changes
                </button>
              </div>
            )}
          </div>
        </div>
      </motion.div>

      {loading && (
        <div className="flex justify-center py-12">
          <LoadingSpinner size="lg" />
        </div>
      )}

      {inventoryData && inventoryData.variants.length > 0 && (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, delay: 0.2 }}
          className="space-y-4"
        >
          {inventoryData.variants.map((variant) => {
            // Calculate total committed across all stores
            const totalCommitted = inventoryData.inventory_levels.reduce(
              (sum, level) => sum + level.quantities.committed, 
              0
            );
            
            // Calculate total verification quantity across all stores
            const totalVerification = inventoryData.inventory_levels.reduce(
              (sum, level) => sum + (level.quantities.verification_quantity || 0), 
              0
            );
            
            // Get available from first inventory level (same across all stores)
            const totalAvailable = inventoryData.inventory_levels.length > 0 
              ? inventoryData.inventory_levels[0].quantities.available 
              : 0;
            
            // Check if verification is available
            const hasVerification = inventoryData.verification_summary !== undefined;

            return (
              <div key={variant.variant_id} className="bg-white dark:bg-dark-100 rounded-lg shadow-md overflow-hidden">
                <button
                  onClick={() => toggleVariant(variant.variant_id)}
                  className="w-full px-3 sm:px-4 py-3 bg-gray-50 dark:bg-dark-200 hover:bg-gray-100 dark:hover:bg-dark-300 transition-colors duration-200 flex items-center justify-between"
                >
                  <div className="text-left min-w-0">
                    <div className="flex flex-col sm:flex-row sm:items-center gap-1 sm:gap-3">
                      <h3 className="text-sm sm:text-base font-medium text-gray-900 dark:text-dark-700 truncate">
                        {variant.product_title}
                      </h3>
                      <div className="flex gap-2 flex-wrap">
                        <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-green-100 dark:bg-green-900/30 text-green-800 dark:text-green-300">
                          Available: {totalAvailable}
                        </span>
                        <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-blue-100 dark:bg-blue-900/30 text-blue-800 dark:text-blue-300">
                          Committed: {totalCommitted}
                        </span>
                        {hasVerification && (
                          <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-amber-100 dark:bg-amber-900/30 text-amber-800 dark:text-amber-300">
                            Verification: {totalVerification}
                          </span>
                        )}
                      </div>
                    </div>
                    <p className="text-xs text-gray-600 dark:text-dark-500 mt-1 truncate">
                      <span className="hidden sm:inline">Variant: {variant.title} • </span>
                      <span className="sm:hidden">{variant.title} • </span>
                      SKU: {variant.sku || "N/A"} • Barcode: {variant.barcode || barcode}
                    </p>
                  </div>
                {expandedVariants.has(variant.variant_id) ? (
                  <ChevronUpIcon className="h-5 w-5 text-gray-400" />
                ) : (
                  <ChevronDownIcon className="h-5 w-5 text-gray-400" />
                )}
              </button>

              {expandedVariants.has(variant.variant_id) && (
                <div className="overflow-x-auto -mx-4 px-4 sm:mx-0 sm:px-0">
                  <table className="w-full min-w-[640px]">
                    <thead className="bg-gray-50 dark:bg-dark-200 border-b border-gray-200 dark:border-dark-300">
                      <tr>
                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-dark-500 uppercase tracking-wider">
                          Store
                        </th>
                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-dark-500 uppercase tracking-wider">
                          Location
                        </th>
                        <th className="px-6 py-3 text-center text-xs font-medium text-gray-500 dark:text-dark-500 uppercase tracking-wider">
                          On Hand
                        </th>
                        <th className="px-6 py-3 text-center text-xs font-medium text-gray-500 dark:text-dark-500 uppercase tracking-wider">
                          Available
                        </th>
                        <th className="px-6 py-3 text-center text-xs font-medium text-gray-500 dark:text-dark-500 uppercase tracking-wider">
                          Committed
                        </th>
                        {hasVerification && (
                          <th className="px-6 py-3 text-center text-xs font-medium text-gray-500 dark:text-dark-500 uppercase tracking-wider">
                            <div className="flex items-center justify-center gap-1">
                              <span>Verification</span>
                              <InformationCircleIcon 
                                className="h-4 w-4 text-gray-400 dark:text-dark-400 cursor-help"
                                title="Shows quantity from unfulfilled orders in the past 4 days"
                              />
                            </div>
                          </th>
                        )}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-200 dark:divide-dark-300">
                      {getInventoryLevelsForVariant(variant.variant_id).map((level) => {
                        const onHandKey = getCellKey(level.store_id, level.location_id, "on_hand");
                        const availableKey = getCellKey(level.store_id, level.location_id, "available");
                        const isEditingOnHand = editingCells.has(onHandKey);
                        const isEditingAvailable = editingCells.has(availableKey);
                        const hasPendingOnHand = hasPendingUpdate(level.store_id, level.location_id, "on_hand");
                        const hasPendingAvailable = hasPendingUpdate(level.store_id, level.location_id, "available");

                        return (
                          <tr key={`${level.store_id}-${level.location_id}`} className="hover:bg-gray-50 dark:hover:bg-dark-50">
                            <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900 dark:text-dark-700">
                              {level.store_name}
                            </td>
                            <td className="px-6 py-4 whitespace-nowrap text-sm">
                              {level.location_alias ? (
                                <div>
                                  <div className="text-gray-900 dark:text-dark-700">{level.location_alias}</div>
                                  <div className="text-xs text-gray-500 dark:text-dark-500">{level.location_name}</div>
                                </div>
                              ) : (
                                <div className="text-gray-900 dark:text-dark-700">{level.location_name}</div>
                              )}
                            </td>
                            <td className="px-6 py-4 whitespace-nowrap text-sm text-center">
                              {isEditingOnHand ? (
                                <div className="flex items-center justify-center gap-1">
                                  <input
                                    type="number"
                                    min="0"
                                    value={editingCells.get(onHandKey)?.value}
                                    onChange={(e) => handleValueChange(level.store_id, level.location_id, "on_hand", e.target.value)}
                                    className="w-20 px-2 py-1 border border-gray-300 dark:border-dark-300 rounded text-center focus:ring-2 focus:ring-shopify-500 dark:focus:ring-shopify-300 focus:border-transparent bg-white dark:bg-dark-50 text-gray-900 dark:text-dark-700"
                                  />
                                  <button
                                    onClick={() => handleSaveEdit(level.store_id, level.location_id, "on_hand")}
                                    className="p-1 text-green-600 hover:text-green-700 dark:text-green-500 dark:hover:text-green-600"
                                  >
                                    <CheckIcon className="h-4 w-4" />
                                  </button>
                                  <button
                                    onClick={() => handleCancelEdit(level.store_id, level.location_id, "on_hand")}
                                    className="p-1 text-red-600 hover:text-red-700 dark:text-red-500 dark:hover:text-red-600"
                                  >
                                    <XMarkIcon className="h-4 w-4" />
                                  </button>
                                </div>
                              ) : (
                                <div className="flex items-center justify-center gap-1">
                                  <span className={`${hasPendingOnHand ? "font-semibold text-yellow-600 dark:text-yellow-500" : "text-gray-900 dark:text-dark-700"}`}>
                                    {hasPendingOnHand ? getPendingValue(level.store_id, level.location_id, "on_hand") : level.quantities.on_hand}
                                  </span>
                                  <button
                                    onClick={() => handleEdit(level, "on_hand")}
                                    className="p-1 text-gray-400 hover:text-gray-600 dark:text-dark-400 dark:hover:text-dark-600"
                                  >
                                    <PencilIcon className="h-4 w-4" />
                                  </button>
                                </div>
                              )}
                            </td>
                            <td className="px-6 py-4 whitespace-nowrap text-sm text-center">
                              {isEditingAvailable ? (
                                <div className="flex items-center justify-center gap-1">
                                  <input
                                    type="number"
                                    min="0"
                                    value={editingCells.get(availableKey)?.value}
                                    onChange={(e) => handleValueChange(level.store_id, level.location_id, "available", e.target.value)}
                                    className="w-20 px-2 py-1 border border-gray-300 dark:border-dark-300 rounded text-center focus:ring-2 focus:ring-shopify-500 dark:focus:ring-shopify-300 focus:border-transparent bg-white dark:bg-dark-50 text-gray-900 dark:text-dark-700"
                                  />
                                  <button
                                    onClick={() => handleSaveEdit(level.store_id, level.location_id, "available")}
                                    className="p-1 text-green-600 hover:text-green-700 dark:text-green-500 dark:hover:text-green-600"
                                  >
                                    <CheckIcon className="h-4 w-4" />
                                  </button>
                                  <button
                                    onClick={() => handleCancelEdit(level.store_id, level.location_id, "available")}
                                    className="p-1 text-red-600 hover:text-red-700 dark:text-red-500 dark:hover:text-red-600"
                                  >
                                    <XMarkIcon className="h-4 w-4" />
                                  </button>
                                </div>
                              ) : (
                                <div className="flex items-center justify-center gap-1">
                                  <span className={`${hasPendingAvailable ? "font-semibold text-yellow-600 dark:text-yellow-500" : "text-gray-900 dark:text-dark-700"}`}>
                                    {hasPendingAvailable ? getPendingValue(level.store_id, level.location_id, "available") : level.quantities.available}
                                  </span>
                                  <button
                                    onClick={() => handleEdit(level, "available")}
                                    className="p-1 text-gray-400 hover:text-gray-600 dark:text-dark-400 dark:hover:text-dark-600"
                                  >
                                    <PencilIcon className="h-4 w-4" />
                                  </button>
                                </div>
                              )}
                            </td>
                            <td className="px-6 py-4 whitespace-nowrap text-sm text-center text-gray-500 dark:text-dark-500">
                              {level.quantities.committed}
                            </td>
                            {hasVerification && (
                              <td className="px-6 py-4 whitespace-nowrap text-sm text-center">
                                {level.quantities.verification_metadata?.error ? (
                                  <span className="text-red-500 dark:text-red-400" title={level.quantities.verification_metadata.error}>
                                    Error
                                  </span>
                                ) : (
                                  <span 
                                    className={`${
                                      level.quantities.verification_quantity !== level.quantities.committed 
                                        ? "text-amber-600 dark:text-amber-500 font-medium" 
                                        : "text-gray-500 dark:text-dark-500"
                                    }`}
                                    title={level.quantities.verification_metadata ? 
                                      `Processed ${level.quantities.verification_metadata.orders_processed} orders from past ${level.quantities.verification_metadata.days_back} days${
                                        level.quantities.verification_metadata.excluded_tag ? 
                                        ` (excluding tag: ${level.quantities.verification_metadata.excluded_tag})` : 
                                        ''
                                      }` : 
                                      'No verification data'
                                    }
                                  >
                                    {level.quantities.verification_quantity ?? '-'}
                                  </span>
                                )}
                              </td>
                            )}
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
            );
          })}
        </motion.div>
      )}
      
      {inventoryData && inventoryData.verification_summary && (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, delay: 0.3 }}
          className="bg-white dark:bg-dark-100 rounded-lg shadow-md p-6 mt-6"
        >
          <div className="space-y-4">
            <div className="flex justify-center">
              <input
                ref={liveQuantityInputRef}
                type="number"
                value={liveQuantity}
                onChange={(e) => setLiveQuantity(e.target.value)}
                onKeyPress={handleLiveQuantitySubmit}
                placeholder="Live Quantity"
                className="w-full max-w-md px-4 sm:px-6 py-3 sm:py-4 text-lg sm:text-xl border border-gray-300 dark:border-dark-300 rounded-lg focus:ring-2 focus:ring-shopify-500 dark:focus:ring-shopify-300 focus:border-transparent bg-white dark:bg-dark-50 text-gray-900 dark:text-dark-700 placeholder-gray-500 dark:placeholder-dark-400"
              />
            </div>
            
            {liveQuantityDifference !== null && (
              <>
                <div className="mt-4 flex justify-center">
                  <span className={`text-3xl font-bold ${
                    liveQuantityDifference === 0 
                      ? "text-green-600 dark:text-green-500" 
                      : liveQuantityDifference > 0 
                      ? "text-green-600 dark:text-green-500"
                      : "text-red-600 dark:text-red-500"
                  }`}>
                    {liveQuantityDifference}
                  </span>
                </div>
                
                <div className="mt-4 flex justify-center">
                  <button
                    onClick={handleBulkUpdateToCalculatedDifference}
                    disabled={updating}
                    className="px-4 sm:px-6 py-2 bg-shopify-600 hover:bg-shopify-700 dark:bg-shopify-500 dark:hover:bg-shopify-600 text-white rounded-lg transition-colors duration-200 flex items-center justify-center gap-2 text-sm sm:text-base w-full max-w-xs"
                  >
                    {updating ? (
                      <>
                        <LoadingSpinner size="sm" />
                        Updating...
                      </>
                    ) : (
                      <>
                        <ArrowPathIcon className="h-5 w-5" />
                        <span>Update All Locations</span>
                      </>
                    )}
                  </button>
                </div>
              </>
            )}
          </div>
        </motion.div>
      )}
    </div>
  );
};

export default Inventory;