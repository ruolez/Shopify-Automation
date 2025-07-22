import React, { useEffect } from "react";
import { useNavigate, useParams } from "react-router-dom";
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
import { fraudRuleApi, type FraudRuleForm, type FraudRule, type FraudRuleConditionGroup, type FraudRuleSchema } from "../utils/fraudRuleApi";
import LoadingSpinner from "./LoadingSpinner";

const fraudRuleSchema = z.object({
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

interface FraudRuleBuilderProps {
  onRuleCreated?: (rule: FraudRule) => void;
  onRuleUpdated?: (rule: FraudRule) => void;
  onCancel?: () => void;
  isEmbedded?: boolean;
  existingRuleId?: number;
}

const FraudRuleBuilder: React.FC<FraudRuleBuilderProps> = ({
  onRuleCreated,
  onRuleUpdated,
  onCancel,
  isEmbedded = false,
  existingRuleId
}) => {
  const navigate = useNavigate();
  const { id } = useParams();
  const queryClient = useQueryClient();
  const ruleId = existingRuleId || (id ? parseInt(id) : undefined);
  const isEditing = Boolean(ruleId);

  // State for managing logical operator
  const [logicalOperator, setLogicalOperator] = React.useState<"AND" | "OR">(
    "AND",
  );

  // Fetch fraud rule schema
  const { data: schema } = useQuery<FraudRuleSchema>({
    queryKey: ["fraud-rule-schema"],
    queryFn: fraudRuleApi.getSchema,
  });

  // Fetch existing rule if editing
  const { data: existingRule } = useQuery<FraudRule>({
    queryKey: ["fraud-rule", ruleId],
    queryFn: () => fraudRuleApi.getRule(ruleId!),
    enabled: isEditing && !!ruleId,
  });

  const {
    register,
    control,
    handleSubmit,
    watch,
    setValue,
    formState: { errors },
  } = useForm<FraudRuleForm>({
    resolver: zodResolver(fraudRuleSchema),
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
      let conditionsToSet: FraudRuleConditionGroup;

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
  }, [existingRule, setValue, replaceConditions]);

  const createRuleMutation = useMutation({
    mutationFn: fraudRuleApi.createRule,
    onSuccess: (rule) => {
      queryClient.invalidateQueries({ queryKey: ["fraud-rules"] });
      toast.success("Fraud rule created successfully!");
      if (onRuleCreated) {
        onRuleCreated(rule);
      } else if (!isEmbedded) {
        navigate("/fraud-detection");
      }
    },
    onError: (error: any) => {
      toast.error(error.response?.data?.detail || "Failed to create fraud rule");
    },
  });

  const updateRuleMutation = useMutation({
    mutationFn: (data: FraudRuleForm) => fraudRuleApi.updateRule(ruleId!, data),
    onSuccess: (rule) => {
      queryClient.invalidateQueries({ queryKey: ["fraud-rules"] });
      queryClient.invalidateQueries({ queryKey: ["fraud-rule", ruleId] });
      toast.success("Fraud rule updated successfully!");
      if (onRuleUpdated) {
        onRuleUpdated(rule);
      } else if (!isEmbedded) {
        navigate("/fraud-detection");
      }
    },
    onError: (error: any) => {
      toast.error(error.response?.data?.detail || "Failed to update fraud rule");
    },
  });

  const onSubmit = (data: FraudRuleForm) => {
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

    // Fraud-specific operator restrictions
    const fraudSpecificRestrictions: Record<string, string[]> = {
      shopify_fraud_risk_level: ["risk_level_equals", "risk_level_not_equals"],
      previous_order_delivery_status: ["delivery_status_contains", "delivery_status_not_contains"],
      fraud_order_total_multiple: ["multiple_greater_than", "greater_than", "less_than", "equals"],
    };

    if (fieldName && fraudSpecificRestrictions[fieldName]) {
      return schema.operators.filter(op => 
        fraudSpecificRestrictions[fieldName].includes(op.operator)
      );
    }

    return schema.operators.filter((op) => op.types.includes(fieldType));
  };

  const getFieldType = (fieldName: string) => {
    if (!schema) return "string";
    const field = schema.fields.find((f) => f.field === fieldName);
    return field?.type || "string";
  };

  const handleCancel = () => {
    if (onCancel) {
      onCancel();
    } else if (!isEmbedded) {
      navigate("/fraud-detection");
    }
  };

  if (!schema) {
    return (
      <div className="flex items-center justify-center h-64">
        <LoadingSpinner size="lg" />
      </div>
    );
  }

  const FormContent = () => (
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
              placeholder="Enter fraud rule name"
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
            placeholder="Describe what this fraud rule does..."
          />
        </div>

        <div className="mt-6">
          <label className="flex items-center">
            <input
              {...register("is_active")}
              type="checkbox"
              className="rounded border-gray-300 text-red-600 focus:ring-red-500"
            />
            <span className="ml-2 text-sm text-gray-700 dark:text-dark-600">
              Activate this fraud rule immediately
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
              Fraud Detection Conditions
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
            className="inline-flex items-center px-3 py-2 border border-gray-300 shadow-sm text-sm leading-4 font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-red-500 dark:bg-dark-100 dark:border-dark-200 dark:text-dark-600 dark:hover:bg-dark-200"
          >
            <PlusIcon className="h-4 w-4 mr-2" />
            Add Condition
          </button>
        </div>

        {conditionFields.length > 1 && (
          <div className="mb-4 p-3 bg-blue-50 border border-blue-200 rounded-lg dark:bg-blue-900/20 dark:border-blue-800">
            <p className="text-sm text-blue-800 dark:text-blue-200">
              <strong>{logicalOperator === "AND" ? "All" : "Any"}</strong> of
              the fraud conditions below must be met for this rule to apply.
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
              className="p-4 border border-gray-200 rounded-lg dark:border-dark-200"
            >
              <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                <div>
                  <label className="label">Fraud Field</label>
                  <select
                    {...register(`conditions.conditions.${index}.field`)}
                    className="input"
                  >
                    <option value="">Select fraud field</option>
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

                    // Special handling for fraud risk level
                    if (selectedField === "shopify_fraud_risk_level") {
                      return (
                        <select
                          {...register(
                            `conditions.conditions.${index}.value`,
                          )}
                          className="input"
                        >
                          <option value="">Select risk level</option>
                          <option value="LOW">Low Risk</option>
                          <option value="MEDIUM">Medium Risk</option>
                          <option value="HIGH">High Risk</option>
                        </select>
                      );
                    }

                    // Special handling for boolean fields
                    if (getFieldType(selectedField) === "boolean") {
                      return (
                        <select
                          {...register(
                            `conditions.conditions.${index}.value`,
                          )}
                          className="input"
                        >
                          <option value="">Select value</option>
                          <option value="true">True</option>
                          <option value="false">False</option>
                        </select>
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
                            placeholder="value1,value2,value3 (comma-separated)"
                          />
                          <p className="mt-1 text-xs text-gray-500">
                            Enter multiple values separated by commas
                          </p>
                        </div>
                      );
                    }

                    // Special handling for fraud_order_total_multiple field
                    if (selectedField === "fraud_order_total_multiple") {
                      return (
                        <div>
                          <input
                            {...register(`conditions.conditions.${index}.value`)}
                            type="number"
                            step="0.1"
                            min="0"
                            className="input"
                            placeholder="e.g., 3.0 for 3x larger"
                          />
                          <p className="mt-1 text-xs text-gray-500 dark:text-dark-400">
                            Compares current order total vs previous order (e.g., 2.5 = current order is 2.5x larger)
                          </p>
                        </div>
                      );
                    }

                    // Special handling for other number fields that should be decimal
                    if (getFieldType(selectedField) === "number") {
                      return (
                        <input
                          {...register(`conditions.conditions.${index}.value`)}
                          type="number"
                          step="0.01"
                          className="input"
                          placeholder="Enter number"
                        />
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
                      className="p-2 text-red-600 hover:bg-red-50 rounded dark:hover:bg-red-900/20"
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
          <h2 className="text-xl font-semibold text-gray-900 dark:text-dark-800">
            Fraud Actions
          </h2>
          <button
            type="button"
            onClick={() => appendAction({ type: "", parameters: {} })}
            className="inline-flex items-center px-3 py-2 border border-gray-300 shadow-sm text-sm leading-4 font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-red-500 dark:bg-dark-100 dark:border-dark-200 dark:text-dark-600 dark:hover:bg-dark-200"
          >
            <PlusIcon className="h-4 w-4 mr-2" />
            Add Action
          </button>
        </div>

        <div className="space-y-4">
          {actionFields.map((field, index) => (
            <div
              key={field.id}
              className="p-4 border border-gray-200 rounded-lg dark:border-dark-200"
            >
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <div>
                  <label className="label">Action Type</label>
                  <select
                    {...register(`actions.${index}.type`)}
                    className="input"
                  >
                    <option value="">Select fraud action</option>
                    {schema.action_types.map((action) => (
                      <option key={action.type} value={action.type}>
                        {action.label}
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="label">Parameters</label>
                  {watch(`actions.${index}.type`) === "place_on_hold" ? (
                    <div className="text-sm text-gray-500 dark:text-dark-400 mt-2">
                      No parameters needed - order will be held for fraud review
                    </div>
                  ) : (
                    <input
                      {...register(`actions.${index}.parameters.tags`)}
                      type="text"
                      className="input"
                      placeholder="Enter tags or values (comma separated)"
                    />
                  )}
                </div>

                <div className="flex items-end">
                  {actionFields.length > 1 && (
                    <button
                      type="button"
                      onClick={() => removeAction(index)}
                      className="p-2 text-red-600 hover:bg-red-50 rounded dark:hover:bg-red-900/20"
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
          onClick={handleCancel}
          className="inline-flex items-center px-4 py-2 border border-gray-300 shadow-sm text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-red-500 dark:bg-dark-100 dark:border-dark-200 dark:text-dark-600 dark:hover:bg-dark-200"
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={
            createRuleMutation.isPending || updateRuleMutation.isPending
          }
          className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md text-white bg-red-600 hover:bg-red-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-red-500 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {createRuleMutation.isPending || updateRuleMutation.isPending ? (
            <LoadingSpinner size="sm" />
          ) : isEditing ? (
            "Update Fraud Rule"
          ) : (
            "Create Fraud Rule"
          )}
        </button>
      </motion.div>
    </form>
  );

  if (isEmbedded) {
    return <FormContent />;
  }

  return (
    <div className="space-y-8">
      <div className="flex items-center space-x-4">
        <button
          onClick={handleCancel}
          className="p-2 text-gray-600 hover:bg-gray-100 dark:text-dark-500 dark:hover:bg-dark-200 rounded-lg"
        >
          <ArrowLeftIcon className="h-5 w-5" />
        </button>
        <div>
          <h1 className="text-3xl font-bold text-gray-900 dark:text-dark-800">
            {isEditing ? "Edit Fraud Rule" : "Create Fraud Rule"}
          </h1>
          <p className="mt-2 text-gray-600 dark:text-dark-500">
            {isEditing
              ? "Update your fraud detection rule"
              : "Set up automated fraud detection"}
          </p>
        </div>
      </div>

      <FormContent />
    </div>
  );
};

export default FraudRuleBuilder;