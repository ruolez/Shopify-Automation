import React from "react";
import { Dialog } from "@headlessui/react";
import { useQuery } from "@tanstack/react-query";
import api from "../utils/api";
import LoadingSpinner from "./LoadingSpinner";
import ProfitBreakdown, { formatMoney, ProfitCondition, ProfitDetails } from "./ProfitBreakdown";
import { formatDate } from "../utils/dateFormat";

interface Address {
  name: string | null;
  address1: string | null;
  address2: string | null;
  city: string | null;
  province: string | null;
  zip: string | null;
  country: string | null;
  phone: string | null;
}

interface LineItemDetail {
  id: string;
  title: string;
  variant_title: string | null;
  sku: string | null;
  quantity: number;
  unit_price: number | null;
  unit_price_original: number | null;
  unit_cost: number | null;
  revenue: number | null;
  cost: number | null;
  profit: number | null;
  margin_percent: number | null;
  gift_card: boolean;
  missing_cost: boolean;
}

export interface OrderDetail {
  store: { id: number; name: string; domain: string };
  order: {
    id: string;
    name: string;
    created_at: string | null;
    financial_status: string | null;
    fulfillment_status: string | null;
    tags: string[];
    note: string | null;
    currency: string | null;
    subtotal: number | null;
    shipping_collected: number | null;
    tax: number | null;
    total: number | null;
    taxes_included: boolean;
    shipping_method: string | null;
    total_weight_grams: number | null;
    item_count: number;
    line_items_truncated: boolean;
  };
  customer: {
    name: string | null;
    email: string | null;
    phone: string | null;
    orders_count: number | null;
    shipping_address: Address | null;
    billing_address: Address | null;
  };
  line_items: LineItemDetail[];
  shipping_estimate: ProfitDetails["shipping_estimate"] | null;
  profit: ProfitDetails;
  profit_conditions: ProfitCondition[];
  // When a profit rule last ran on the order; null means the profit was calculated live
  profit_recorded_at: string | null;
}

const marginClass = (margin: number | null) => {
  if (margin === null) return "text-gray-400";
  if (margin < 0) return "text-red-600 dark:text-red-400 font-semibold";
  if (margin < 15) return "text-amber-600 dark:text-amber-400 font-semibold";
  return "text-green-700 dark:text-green-400";
};

const percent = (value: number | null) => (value === null ? "—" : `${value.toFixed(1)}%`);

const AddressBlock: React.FC<{ title: string; address: Address | null }> = ({ title, address }) => (
  <div>
    <div className="text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-dark-400">{title}</div>
    {address ? (
      <div className="mt-1 text-sm text-gray-700 dark:text-dark-700">
        {address.name && <div>{address.name}</div>}
        {address.address1 && <div>{address.address1}</div>}
        {address.address2 && <div>{address.address2}</div>}
        <div>{[address.city, address.province, address.zip].filter(Boolean).join(", ")}</div>
        {address.country && <div>{address.country}</div>}
        {address.phone && <div>{address.phone}</div>}
      </div>
    ) : (
      <div className="mt-1 text-sm text-gray-400">—</div>
    )}
  </div>
);

const Stat: React.FC<{ label: string; value: React.ReactNode }> = ({ label, value }) => (
  <div>
    <div className="text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-dark-400">{label}</div>
    <div className="mt-0.5 text-sm text-gray-800 dark:text-dark-800">{value ?? "—"}</div>
  </div>
);

const shippingSourceText = (estimate: OrderDetail["shipping_estimate"]) => {
  if (!estimate || estimate.source === "none") return "No estimate available (no similar shipped orders and no default amount)";
  if (estimate.source === "default") return "Default shipping amount (no similar shipped orders found)";
  return `Average of ${estimate.samples} similar shipped order${estimate.samples === 1 ? "" : "s"} to ${
    estimate.shipping_state || "this state"
  } within ±${estimate.tolerance_g} g`;
};

const OrderDetailModal: React.FC<{
  open: boolean;
  onClose: () => void;
  storeId: number | null;
  orderId: string | null;
  orderNumber?: string;
  timezone?: string;
  dateFormat?: string;
}> = ({ open, onClose, storeId, orderId, orderNumber, timezone, dateFormat }) => {
  const { data, isLoading, error } = useQuery<OrderDetail>({
    queryKey: ["order-detail", storeId, orderId],
    queryFn: async () =>
      (await api.get("/order-logs/order-detail", { params: { store_id: storeId, order_id: orderId } })).data,
    enabled: open && storeId !== null && !!orderId,
    staleTime: 60_000,
    retry: false,
  });

  const currency = data?.order.currency || data?.profit?.currency || "USD";
  const money = (amount: number | null | undefined) => formatMoney(amount, currency);

  return (
    <Dialog open={open} onClose={onClose} className="relative z-50">
      <div className="fixed inset-0 bg-black/40" aria-hidden="true" />
      <div className="fixed inset-0 overflow-y-auto">
        <div className="flex min-h-full items-start justify-center p-4 sm:p-8">
          <Dialog.Panel className="w-full max-w-5xl rounded-lg bg-white dark:bg-dark-100 shadow-xl">
            <div className="flex items-start justify-between border-b border-gray-200 dark:border-dark-200 px-6 py-4">
              <div>
                <Dialog.Title className="text-lg font-semibold text-gray-900 dark:text-dark-800">
                  Order {data?.order.name || orderNumber || ""}
                </Dialog.Title>
                {data && (
                  <p className="text-sm text-gray-500 dark:text-dark-400">
                    {data.store.name} · {data.order.created_at ? formatDate(data.order.created_at, { timezone, dateFormat }) : ""}
                    {data.order.financial_status && ` · ${data.order.financial_status.toLowerCase()}`}
                    {data.order.fulfillment_status && ` · ${data.order.fulfillment_status.toLowerCase().replace(/_/g, " ")}`}
                  </p>
                )}
              </div>
              <button
                onClick={onClose}
                className="rounded-md px-2 py-1 text-sm text-gray-500 hover:bg-gray-100 dark:hover:bg-dark-200"
                aria-label="Close"
              >
                ✕
              </button>
            </div>

            <div className="px-6 py-5 space-y-6">
              {isLoading && (
                <div className="flex justify-center py-12">
                  <LoadingSpinner size="sm" />
                </div>
              )}
              {error && (
                <div className="text-sm text-red-600 dark:text-red-400">
                  {(error as any)?.response?.data?.detail || "Failed to load the order"}
                </div>
              )}

              {data && (
                <>
                  <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
                    <Stat label="Order total" value={money(data.order.total)} />
                    <Stat label="Items" value={data.order.item_count} />
                    <Stat label="Shipping method" value={data.order.shipping_method} />
                    <Stat
                      label="Weight"
                      value={data.order.total_weight_grams !== null ? `${Math.round(data.order.total_weight_grams)} g` : "—"}
                    />
                  </div>
                  {data.order.tags.length > 0 && (
                    <div className="flex flex-wrap gap-1">
                      {data.order.tags.map((tag) => (
                        <span key={tag} className="rounded-full bg-gray-100 dark:bg-dark-200 px-2 py-0.5 text-xs text-gray-700 dark:text-dark-700">
                          {tag}
                        </span>
                      ))}
                    </div>
                  )}

                  <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                    <div>
                      <div className="text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-dark-400">Customer</div>
                      <div className="mt-1 text-sm text-gray-700 dark:text-dark-700">
                        <div>{data.customer.name || "—"}</div>
                        {data.customer.email && <div>{data.customer.email}</div>}
                        {data.customer.phone && <div>{data.customer.phone}</div>}
                        {data.customer.orders_count !== null && (
                          <div className="text-gray-500 dark:text-dark-400">{data.customer.orders_count} orders</div>
                        )}
                      </div>
                    </div>
                    <AddressBlock title="Ship to" address={data.customer.shipping_address} />
                    <AddressBlock title="Bill to" address={data.customer.billing_address} />
                  </div>

                  <div>
                    <div className="text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-dark-400 mb-2">Products</div>
                    <div className="overflow-x-auto rounded-md border border-gray-200 dark:border-dark-200">
                      <table className="min-w-full text-sm">
                        <thead className="bg-gray-50 dark:bg-dark-50 text-xs uppercase tracking-wider text-gray-500 dark:text-dark-400">
                          <tr>
                            <th className="px-3 py-2 text-left">Product</th>
                            <th className="px-3 py-2 text-right">Qty</th>
                            <th className="px-3 py-2 text-right">Price</th>
                            <th className="px-3 py-2 text-right">Cost</th>
                            <th className="px-3 py-2 text-right">Revenue</th>
                            <th className="px-3 py-2 text-right">Profit</th>
                            <th className="px-3 py-2 text-right">Margin</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-gray-200 dark:divide-dark-200">
                          {data.line_items.map((item) => (
                            <tr key={item.id} className={item.margin_percent !== null && item.margin_percent < 0 ? "bg-red-50 dark:bg-red-900/10" : ""}>
                              <td className="px-3 py-2 text-gray-800 dark:text-dark-800">
                                <div>{item.title}</div>
                                <div className="text-xs text-gray-500 dark:text-dark-400">
                                  {[item.variant_title, item.sku].filter(Boolean).join(" · ")}
                                  {item.gift_card && " · gift card"}
                                  {item.missing_cost && (
                                    <span className="text-amber-600 dark:text-amber-400"> · no cost set in Shopify</span>
                                  )}
                                </div>
                              </td>
                              <td className="px-3 py-2 text-right tabular-nums">{item.quantity}</td>
                              <td className="px-3 py-2 text-right tabular-nums whitespace-nowrap">
                                {money(item.unit_price)}
                                {item.unit_price_original !== null && item.unit_price !== null && item.unit_price_original > item.unit_price && (
                                  <div className="text-xs text-gray-400 line-through">{money(item.unit_price_original)}</div>
                                )}
                              </td>
                              <td className="px-3 py-2 text-right tabular-nums whitespace-nowrap">{item.unit_cost === null ? "—" : money(item.unit_cost)}</td>
                              <td className="px-3 py-2 text-right tabular-nums whitespace-nowrap">{money(item.revenue)}</td>
                              <td className={`px-3 py-2 text-right tabular-nums whitespace-nowrap ${marginClass(item.margin_percent)}`}>{money(item.profit)}</td>
                              <td className={`px-3 py-2 text-right tabular-nums whitespace-nowrap ${marginClass(item.margin_percent)}`}>{percent(item.margin_percent)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    {data.order.line_items_truncated && (
                      <p className="mt-1 text-xs text-amber-600 dark:text-amber-400">Not all line items could be loaded.</p>
                    )}
                  </div>

                  <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
                    <div>
                      <div className="text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-dark-400 mb-2">Estimated shipping</div>
                      <div className="text-sm text-gray-700 dark:text-dark-700">
                        <div className="text-lg font-semibold text-gray-900 dark:text-dark-800">
                          {data.profit.shipping_cost === null ? "—" : money(data.profit.shipping_cost)}
                        </div>
                        <div className="text-xs text-gray-500 dark:text-dark-400">{shippingSourceText(data.shipping_estimate)}</div>
                        {data.order.shipping_collected !== null && (
                          <div className="mt-1 text-xs text-gray-500 dark:text-dark-400">
                            Customer paid {money(data.order.shipping_collected)} for shipping
                          </div>
                        )}
                      </div>
                    </div>
                    <div>
                      <div className="text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-dark-400 mb-2">Profit calculation</div>
                      <ProfitBreakdown
                        profit={{ ...data.profit, shipping_estimate: data.shipping_estimate || undefined }}
                        conditions={data.profit_conditions}
                      />
                    </div>
                  </div>
                  <p className="text-xs text-gray-400 dark:text-dark-300">
                    {data.profit_recorded_at
                      ? `Shipping estimate and profit as recorded when the rule ran · ${formatDate(data.profit_recorded_at, { timezone, dateFormat })}`
                      : "Shipping estimate and profit calculated now · no profit rule has evaluated this order"}
                  </p>
                </>
              )}
            </div>
          </Dialog.Panel>
        </div>
      </div>
    </Dialog>
  );
};

export default OrderDetailModal;
