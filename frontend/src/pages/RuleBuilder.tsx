import React, { useEffect } from "react";
import { useNavigate, useParams, Link } from "react-router-dom";
import { motion } from "framer-motion";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useForm, useFieldArray } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import {
  PlusIcon,
  TrashIcon,
  ArrowLeftIcon,
  AdjustmentsHorizontalIcon,
} from "@heroicons/react/24/outline";
import toast from "react-hot-toast";
import api from "../utils/api";
import { RuleForm, RuleSchema, Rule, RuleConditionGroup } from "../types";
import LoadingSpinner from "../components/LoadingSpinner";

const ruleSchema = z.object({
  name: z.string().min(3, "Rule name must be at least 3 characters"),
  description: z.string().optional(),
  conditions: z.union([
    z
      .array(
        z.object({
          field: z.string().min(1, "Field is required"),
          operator: z.string().min(1, "Operator is required"),
          value: z.any(),
        }),
      )
      .min(1, "At least one condition is required"),
    z.object({
      operator: z.enum(["AND", "OR"]),
      conditions: z
        .array(
          z.object({
            field: z.string().min(1, "Field is required"),
            operator: z.string().min(1, "Operator is required"),
            value: z.any(),
          }),
        )
        .min(1, "At least one condition is required"),
    }),
  ]),
  actions: z
    .array(
      z.object({
        type: z.string().min(1, "Action type is required"),
        parameters: z.record(z.any()),
      }),
    )
    .min(1, "At least one action is required"),
  priority: z.number().min(0).max(100),
  delay_ms: z.number().min(0).max(60000),
  is_active: z.boolean(),
});

const RuleBuilder: React.FC = () => {
  const navigate = useNavigate();
  const { id } = useParams();
  const queryClient = useQueryClient();
  const isEditing = Boolean(id);

  // State for managing logical operator
  const [logicalOperator, setLogicalOperator] = React.useState<"AND" | "OR">(
    "AND",
  );

  // Fetch rule schema
  const { data: schema } = useQuery<RuleSchema>({
    queryKey: ["rule-schema"],
    queryFn: async () => {
      const response = await api.get("/rules/schema");
      return response.data;
    },
  });

  // Fetch location aliases for fulfillment actions
  const { data: locationAliases } = useQuery({
    queryKey: ["location-aliases"],
    queryFn: async () => {
      const response = await api.get("/location-aliases");
      return response.data;
    },
  });

  // Fetch existing rule if editing
  const { data: existingRule } = useQuery<Rule>({
    queryKey: ["rule", id],
    queryFn: async () => {
      const response = await api.get(`/rules/${id}`);
      return response.data;
    },
    enabled: isEditing,
  });

  const {
    register,
    control,
    handleSubmit,
    watch,
    setValue,
    formState: { errors },
  } = useForm<RuleForm>({
    resolver: zodResolver(ruleSchema),
    defaultValues: {
      name: "",
      description: "",
      conditions: {
        operator: "AND" as const,
        conditions: [{ field: "", operator: "", value: "" }],
      },
      actions: [{ type: "", parameters: {} }],
      priority: 0,
      delay_ms: 10,
      is_active: true,
    },
  });

  const {
    fields: conditionFields,
    append: appendCondition,
    remove: removeCondition,
    replace: replaceConditions,
  } = useFieldArray({
    control,
    name: "conditions.conditions",
  });

  const {
    fields: actionFields,
    append: appendAction,
    remove: removeAction,
  } = useFieldArray({
    control,
    name: "actions",
  });

  // Load existing rule data
  useEffect(() => {
    if (existingRule) {
      setValue("name", existingRule.name);
      setValue("description", existingRule.description || "");

      // Handle both legacy (array) and new (object) condition formats
      let conditionsToSet: RuleConditionGroup;

      if (Array.isArray(existingRule.conditions)) {
        // Legacy format: convert to new format
        const processedConditions = existingRule.conditions.map((condition) => {
          if (
            (condition.operator === "in_list" ||
              condition.operator === "not_in_list") &&
            Array.isArray(condition.value)
          ) {
            return { ...condition, value: condition.value.join(", ") };
          }
          return condition;
        });

        conditionsToSet = {
          operator: "AND",
          conditions: processedConditions,
        };
        setLogicalOperator("AND");
      } else {
        // New format: use as-is
        const processedConditions = existingRule.conditions.conditions.map(
          (condition) => {
            if (
              (condition.operator === "in_list" ||
                condition.operator === "not_in_list") &&
              Array.isArray(condition.value)
            ) {
              return { ...condition, value: condition.value.join(", ") };
            }
            return condition;
          },
        );

        conditionsToSet = {
          operator: existingRule.conditions.operator,
          conditions: processedConditions,
        };
        setLogicalOperator(existingRule.conditions.operator);
      }

      // Clear existing conditions and set new ones
      setValue("conditions", conditionsToSet);

      // Force re-render of condition fields by replacing the entire conditions array
      // This ensures all conditions from the existing rule are displayed
      replaceConditions(conditionsToSet.conditions);

      setValue("actions", existingRule.actions);
      setValue("priority", existingRule.priority);
      setValue("delay_ms", existingRule.delay_ms || 10);
      setValue("is_active", existingRule.is_active);
    }
  }, [existingRule, setValue]);

  const createRuleMutation = useMutation({
    mutationFn: async (data: RuleForm) => {
      const response = await api.post("/rules", data);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["rules"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard-stats"] });
      toast.success("Rule created successfully!");
      navigate("/rules");
    },
    onError: (error: any) => {
      toast.error(error.response?.data?.detail || "Failed to create rule");
    },
  });

  const updateRuleMutation = useMutation({
    mutationFn: async (data: RuleForm) => {
      const response = await api.put(`/rules/${id}`, data);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["rules"] });
      queryClient.invalidateQueries({ queryKey: ["rule", id] });
      queryClient.invalidateQueries({ queryKey: ["dashboard-stats"] });
      toast.success("Rule updated successfully!");
      navigate("/rules");
    },
    onError: (error: any) => {
      toast.error(error.response?.data?.detail || "Failed to update rule");
    },
  });

  const onSubmit = (data: RuleForm) => {
    // Process conditions to convert comma-separated strings to arrays for list operators
    const processedConditions = Array.isArray(data.conditions)
      ? data.conditions
      : data.conditions.conditions;

    const processedConditionList = processedConditions.map((condition) => {
      if (
        condition.operator === "in_list" ||
        condition.operator === "not_in_list"
      ) {
        // Convert comma-separated string to array
        if (typeof condition.value === "string") {
          const trimmedValues = condition.value
            .split(",")
            .map((v) => v.trim())
            .filter((v) => v.length > 0);
          return { ...condition, value: trimmedValues };
        }
      }
      return condition;
    });

    const processedData = {
      ...data,
      conditions: {
        operator: logicalOperator,
        conditions: processedConditionList,
      },
    };

    if (isEditing) {
      updateRuleMutation.mutate(processedData);
    } else {
      createRuleMutation.mutate(processedData);
    }
  };

  const getOperatorsForField = (fieldType: string, fieldName?: string) => {
    if (!schema) return [];

    // Special case for fulfillment_location field - only allow equals and not_equals
    if (fieldName === "fulfillment_location") {
      return schema.operators.filter(
        (op) => op.operator === "equals" || op.operator === "not_equals",
      );
    }

    return schema.operators.filter((op) => op.types.includes(fieldType));
  };

  const getFieldType = (fieldName: string) => {
    if (!schema) return "string";
    const field = schema.fields.find((f) => f.field === fieldName);
    return field?.type || "string";
  };

  if (!schema) {
    return (
      <div className="flex items-center justify-center h-64">
        <LoadingSpinner size="lg" />
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <div className="flex items-center space-x-4">
        <button
          onClick={() => navigate("/rules")}
          className="p-2 text-gray-600 hover:bg-gray-100 dark:text-dark-500 dark:hover:bg-dark-200 rounded-lg"
        >
          <ArrowLeftIcon className="h-5 w-5" />
        </button>
        <div>
          <h1 className="text-3xl font-bold text-gray-900 dark:text-dark-800">
            {isEditing ? "Edit Rule" : "Create Rule"}
          </h1>
          <p className="mt-2 text-gray-600 dark:text-dark-500">
            {isEditing
              ? "Update your automation rule"
              : "Set up automated order processing"}
          </p>
        </div>
      </div>

      <form onSubmit={handleSubmit(onSubmit)} className="space-y-8">
        {/* Basic Information */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="card"
        >
          <h2 className="text-xl font-semibold text-gray-900 dark:text-dark-800 mb-6">
            Basic Information
          </h2>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div>
              <label className="label">Rule Name *</label>
              <input
                {...register("name")}
                type="text"
                className="input"
                placeholder="Enter rule name"
              />
              {errors.name && (
                <p className="mt-1 text-sm text-red-600">
                  {errors.name.message}
                </p>
              )}
            </div>

            <div>
              <label className="label">Priority</label>
              <input
                {...register("priority", { valueAsNumber: true })}
                type="number"
                min="0"
                max="100"
                className="input"
                placeholder="0"
              />
              {errors.priority && (
                <p className="mt-1 text-sm text-red-600">
                  {errors.priority.message}
                </p>
              )}
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mt-6">
            <div>
              <label className="label">Delay After Rule (ms)</label>
              <input
                {...register("delay_ms", { valueAsNumber: true })}
                type="number"
                min="0"
                max="60000"
                className="input"
                placeholder="10"
              />
              {errors.delay_ms && (
                <p className="mt-1 text-sm text-red-600">
                  {errors.delay_ms.message}
                </p>
              )}
              <p className="mt-1 text-xs text-gray-500 dark:text-dark-400">
                Time to wait after this rule executes before the next rule runs
                (0-60000ms)
              </p>
            </div>
          </div>

          <div className="mt-6">
            <label className="label">Description</label>
            <textarea
              {...register("description")}
              className="input"
              rows={3}
              placeholder="Describe what this rule does..."
            />
          </div>

          <div className="mt-6">
            <label className="flex items-center">
              <input
                {...register("is_active")}
                type="checkbox"
                className="rounded border-gray-300 text-shopify-600 focus:outline-none"
              />
              <span className="ml-2 text-sm text-gray-700 dark:text-dark-600">
                Activate this rule immediately
              </span>
            </label>
          </div>
        </motion.div>

        {/* Conditions */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1 }}
          className="card"
        >
          <div className="flex items-center justify-between mb-6">
            <div className="flex items-center space-x-4">
              <h2 className="text-xl font-semibold text-gray-900 dark:text-dark-800">
                Conditions
              </h2>
              {conditionFields.length > 1 && (
                <div className="flex items-center space-x-2">
                  <AdjustmentsHorizontalIcon className="h-5 w-5 text-gray-400" />
                  <select
                    value={logicalOperator}
                    onChange={(e) =>
                      setLogicalOperator(e.target.value as "AND" | "OR")
                    }
                    className="input text-sm px-3 py-1"
                  >
                    <option value="AND">
                      All conditions must be true (AND)
                    </option>
                    <option value="OR">Any condition can be true (OR)</option>
                  </select>
                </div>
              )}
            </div>
            <button
              type="button"
              onClick={() =>
                appendCondition({ field: "", operator: "", value: "" })
              }
              className="btn-secondary flex items-center"
            >
              <PlusIcon className="h-4 w-4 mr-2" />
              Add Condition
            </button>
          </div>

          {conditionFields.length > 1 && (
            <div className="mb-4 p-3 bg-blue-50 border border-blue-200 rounded-lg">
              <p className="text-sm text-blue-800">
                <strong>{logicalOperator === "AND" ? "All" : "Any"}</strong> of
                the conditions below must be met for this rule to apply.
                {logicalOperator === "AND"
                  ? " Every condition must be true."
                  : " At least one condition must be true."}
              </p>
            </div>
          )}

          <div className="space-y-4">
            {conditionFields.map((field, index) => (
              <div
                key={field.id}
                className="p-4 border border-gray-200 rounded-lg"
              >
                <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                  <div>
                    <label className="label">Field</label>
                    <select
                      {...register(`conditions.conditions.${index}.field`)}
                      className="input"
                    >
                      <option value="">Select field</option>
                      {schema.fields.map((field) => (
                        <option key={field.field} value={field.field}>
                          {field.label}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div>
                    <label className="label">Operator</label>
                    <select
                      {...register(`conditions.conditions.${index}.operator`)}
                      className="input"
                    >
                      <option value="">Select operator</option>
                      {getOperatorsForField(
                        getFieldType(
                          watch(`conditions.conditions.${index}.field`),
                        ),
                        watch(`conditions.conditions.${index}.field`),
                      ).map((op) => (
                        <option key={op.operator} value={op.operator}>
                          {op.label}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div>
                    <label className="label">Value</label>
                    {(() => {
                      const selectedField = watch(
                        `conditions.conditions.${index}.field`,
                      );
                      const selectedOperator = watch(
                        `conditions.conditions.${index}.operator`,
                      );
                      const isListOperator =
                        selectedOperator === "in_list" ||
                        selectedOperator === "not_in_list";
                      const isFulfillmentLocation =
                        selectedField === "fulfillment_location";

                      if (isFulfillmentLocation) {
                        return (
                          <div>
                            <select
                              {...register(
                                `conditions.conditions.${index}.value`,
                              )}
                              className="input"
                            >
                              <option value="">Select location</option>
                              {locationAliases
                                ?.filter((alias: any) => alias.is_active)
                                .map((alias: any) => (
                                  <option
                                    key={alias.id}
                                    value={alias.alias_name}
                                  >
                                    {alias.alias_name}
                                    {alias.mappings.length > 0 &&
                                      ` (${alias.mappings.length} store${
                                        alias.mappings.length !== 1 ? "s" : ""
                                      })`}
                                  </option>
                                ))}
                            </select>
                            {locationAliases?.length === 0 && (
                              <p className="text-sm text-amber-600 mt-1">
                                No location aliases configured.
                                <Link
                                  to="/locations"
                                  className="underline ml-1"
                                >
                                  Create one here
                                </Link>
                                .
                              </p>
                            )}
                            <p className="mt-1 text-xs text-gray-500">
                              Select a location alias to match against order
                              fulfillment locations
                            </p>
                          </div>
                        );
                      }

                      if (isListOperator) {
                        return (
                          <div>
                            <input
                              {...register(
                                `conditions.conditions.${index}.value`,
                              )}
                              type="text"
                              className="input"
                              placeholder="PA,NY,CA,TX (comma-separated)"
                            />
                            <p className="mt-1 text-xs text-gray-500">
                              Enter multiple values separated by commas (e.g.,
                              PA,NY,CA,TX)
                            </p>
                          </div>
                        );
                      }

                      return (
                        <input
                          {...register(`conditions.conditions.${index}.value`)}
                          type="text"
                          className="input"
                          placeholder="Enter value"
                        />
                      );
                    })()}
                  </div>

                  <div className="flex items-end">
                    {conditionFields.length > 1 && (
                      <button
                        type="button"
                        onClick={() => removeCondition(index)}
                        className="p-2 text-red-600 hover:bg-red-50 rounded"
                      >
                        <TrashIcon className="h-5 w-5" />
                      </button>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>

          {errors.conditions && (
            <p className="mt-2 text-sm text-red-600">
              {errors.conditions.message}
            </p>
          )}
        </motion.div>

        {/* Actions */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.2 }}
          className="card"
        >
          <div className="flex items-center justify-between mb-6">
            <h2 className="text-xl font-semibold text-gray-900 dark:text-dark-800">Actions</h2>
            <button
              type="button"
              onClick={() => appendAction({ type: "", parameters: {} })}
              className="btn-secondary flex items-center"
            >
              <PlusIcon className="h-4 w-4 mr-2" />
              Add Action
            </button>
          </div>

          <div className="space-y-4">
            {actionFields.map((field, index) => (
              <div
                key={field.id}
                className="p-4 border border-gray-200 rounded-lg"
              >
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  <div>
                    <label className="label">Action Type</label>
                    <select
                      {...register(`actions.${index}.type`)}
                      className="input"
                    >
                      <option value="">Select action</option>
                      {schema.action_types.map((action) => (
                        <option key={action.type} value={action.type}>
                          {action.label}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div>
                    <label className="label">Parameters</label>
                    {watch()?.actions?.[index]?.type ===
                    "set_fulfillment_location" ? (
                      <div>
                        <select
                          {...register(
                            `actions.${index}.parameters.location_alias`,
                          )}
                          className="input"
                        >
                          <option value="">Select location alias</option>
                          {locationAliases
                            ?.filter((alias: any) => alias.is_active)
                            .map((alias: any) => (
                              <option key={alias.id} value={alias.alias_name}>
                                {alias.alias_name}
                                {alias.mappings.length > 0 &&
                                  ` (${alias.mappings.length} store${
                                    alias.mappings.length !== 1 ? "s" : ""
                                  })`}
                              </option>
                            ))}
                        </select>
                        {locationAliases?.length === 0 && (
                          <p className="text-sm text-amber-600 mt-1">
                            No location aliases configured.
                            <Link to="/locations" className="underline ml-1">
                              Create one here
                            </Link>
                            .
                          </p>
                        )}
                      </div>
                    ) : watch()?.actions?.[index]?.type === "place_on_hold" ? (
                      <div className="space-y-2">
                        <select
                          {...register(`actions.${index}.parameters.reason`)}
                          className="input"
                        >
                          {(schema.hold_reasons || [{ value: "OTHER", label: "Other" }]).map(
                            (reason) => (
                              <option key={reason.value} value={reason.value}>
                                Hold reason: {reason.label}
                              </option>
                            ),
                          )}
                        </select>
                        <input
                          {...register(`actions.${index}.parameters.notes`)}
                          type="text"
                          className="input"
                          placeholder="Hold note shown in Shopify (optional)"
                        />
                        <p className="text-xs text-gray-500">
                          Holds every open fulfillment order of the order; release it in Shopify.
                        </p>
                      </div>
                    ) : (
                      <input
                        {...register(`actions.${index}.parameters.tags`)}
                        type="text"
                        className="input"
                        placeholder="Enter tags (comma separated)"
                      />
                    )}
                  </div>

                  <div className="flex items-end">
                    {actionFields.length > 1 && (
                      <button
                        type="button"
                        onClick={() => removeAction(index)}
                        className="p-2 text-red-600 hover:bg-red-50 rounded"
                      >
                        <TrashIcon className="h-5 w-5" />
                      </button>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>

          {errors.actions && (
            <p className="mt-2 text-sm text-red-600">
              {errors.actions.message}
            </p>
          )}
        </motion.div>

        {/* Submit */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.3 }}
          className="flex justify-end space-x-4"
        >
          <button
            type="button"
            onClick={() => navigate("/rules")}
            className="btn-secondary"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={
              createRuleMutation.isPending || updateRuleMutation.isPending
            }
            className="btn-primary"
          >
            {createRuleMutation.isPending || updateRuleMutation.isPending ? (
              <LoadingSpinner size="sm" />
            ) : isEditing ? (
              "Update Rule"
            ) : (
              "Create Rule"
            )}
          </button>
        </motion.div>
      </form>
    </div>
  );
};

export default RuleBuilder;
