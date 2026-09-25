import React from "react";
import { Listbox } from "@headlessui/react";
import {
  CheckCircleIcon,
  CheckIcon,
  ChevronUpDownIcon,
  ExclamationTriangleIcon,
  InformationCircleIcon,
} from "@heroicons/react/24/outline";

export type RiskLevel = "HIGH" | "MEDIUM" | "LOW" | "NONE" | "PENDING";
export type RiskRecommendation = "ACCEPT" | "INVESTIGATE" | "CANCEL" | "NONE";
export type CardholderMatch = "MATCH" | "LAST_NAME_ONLY" | "MISMATCH";
type FactSentiment = "POSITIVE" | "NEGATIVE" | "NEUTRAL";

export interface CardholderCheck {
  status: CardholderMatch;
  card_names: string[];
  billing_name: string | null;
  shipping_name: string | null;
}

export interface OrderRisk {
  level: RiskLevel | null;
  recommendation: RiskRecommendation | null;
  assessments: {
    // null means Shopify's own assessment; otherwise the fraud app's name
    provider: string | null;
    level: RiskLevel | null;
    facts: { description: string; sentiment: FactSentiment | null }[];
  }[];
  ip: string | null;
  ip_location: string | null;
  cardholder: CardholderCheck | null;
}

const LEVEL_LABEL: Partial<Record<RiskLevel, string>> = { HIGH: "High", MEDIUM: "Medium", LOW: "Low" };

const LEVEL_TEXT_CLASS: Partial<Record<RiskLevel, string>> = {
  HIGH: "text-red-700 dark:text-red-400",
  MEDIUM: "text-amber-700 dark:text-amber-400",
  LOW: "text-green-700 dark:text-green-400",
};

const RED_BADGE = "bg-red-100 text-red-800 dark:bg-red-900/20 dark:text-red-400";
const AMBER_BADGE = "bg-amber-100 text-amber-800 dark:bg-amber-900/20 dark:text-amber-400";
const GREEN_BADGE = "bg-green-100 text-green-800 dark:bg-green-900/20 dark:text-green-400";

const LEVEL_BADGE_CLASS: Partial<Record<RiskLevel, string>> = {
  HIGH: RED_BADGE,
  MEDIUM: AMBER_BADGE,
  LOW: GREEN_BADGE,
  PENDING: "bg-gray-100 text-gray-700 dark:bg-dark-200 dark:text-dark-600",
};

const ADVICE: Partial<Record<RiskRecommendation, string>> = {
  ACCEPT: "You can fulfill this order",
  INVESTIGATE: "Investigate this order before fulfilling it",
  CANCEL: "Consider canceling this order",
};

const CARDHOLDER_BADGE: Record<CardholderMatch, { label: string; className: string }> = {
  MISMATCH: { label: "Name mismatch", className: RED_BADGE },
  LAST_NAME_ONLY: { label: "Last name only", className: AMBER_BADGE },
  MATCH: { label: "Name matches", className: GREEN_BADGE },
};

const levelText = (level: RiskLevel | null) => (level && LEVEL_LABEL[level] ? `${LEVEL_LABEL[level]} risk` : null);

const FactIcon: React.FC<{ sentiment: FactSentiment | null }> = ({ sentiment }) => {
  if (sentiment === "NEGATIVE") return <ExclamationTriangleIcon className="h-5 w-5 flex-none text-red-600 dark:text-red-400" />;
  if (sentiment === "POSITIVE") return <CheckCircleIcon className="h-5 w-5 flex-none text-green-700 dark:text-green-400" />;
  return <InformationCircleIcon className="h-5 w-5 flex-none text-gray-500 dark:text-dark-400" />;
};

export const CardholderMatchBadge: React.FC<{ match: CardholderMatch | null | undefined; title?: string }> = ({
  match,
  title,
}) => {
  if (!match || !CARDHOLDER_BADGE[match]) return null;
  const { label, className } = CARDHOLDER_BADGE[match];
  return (
    <span title={title} className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${className}`}>
      {label}
    </span>
  );
};

const CARDHOLDER_RESULT: Record<CardholderMatch, { text: string; icon: React.ReactNode }> = {
  MATCH: { text: "Name on card matches the order", icon: <FactIcon sentiment="POSITIVE" /> },
  LAST_NAME_ONLY: {
    text: "Only the last name on the card matches the order",
    icon: <ExclamationTriangleIcon className="h-5 w-5 flex-none text-amber-600 dark:text-amber-400" />,
  },
  MISMATCH: { text: "Name on card does not match the billing or shipping name", icon: <FactIcon sentiment="NEGATIVE" /> },
};

const CardholderNameCheck: React.FC<{ check: CardholderCheck }> = ({ check }) => {
  const names = [
    [check.card_names.length > 1 ? "Names on cards" : "Name on card", check.card_names.join(", ")],
    ["Billing", check.billing_name],
    ["Shipping", check.shipping_name],
  ].filter(([, name]) => name);
  return (
    <div data-cardholder-match={check.status} className="flex gap-2 text-sm text-gray-800 dark:text-dark-800">
      {CARDHOLDER_RESULT[check.status].icon}
      <div>
        <div>{CARDHOLDER_RESULT[check.status].text}</div>
        <div className="text-xs text-gray-500 dark:text-dark-400">{names.map(([label, name]) => `${label}: ${name}`).join(" · ")}</div>
      </div>
    </div>
  );
};

export const RiskLevelBadge: React.FC<{ level: RiskLevel | null | undefined }> = ({ level }) => {
  if (!level || !LEVEL_BADGE_CLASS[level]) return null;
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${LEVEL_BADGE_CLASS[level]}`}>
      {level === "PENDING" ? "Risk pending" : levelText(level)}
    </span>
  );
};

const OrderRiskEvaluation: React.FC<{ risk: OrderRisk }> = ({ risk }) => {
  const pending = risk.level === "PENDING";
  const headline = levelText(risk.level);
  const advice = pending ? "Risk analysis in progress" : risk.recommendation && ADVICE[risk.recommendation];
  const labelAssessments = risk.assessments.length > 1;

  return (
    <div>
      <div className="text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-dark-400 mb-2">Order risk evaluation</div>
      <div className="rounded-md border border-gray-200 dark:border-dark-200 p-4 space-y-3">
        {(headline || advice) && (
          <div>
            {headline && !pending && (
              <div className={`text-sm font-semibold ${(risk.level && LEVEL_TEXT_CLASS[risk.level]) || "text-gray-800 dark:text-dark-800"}`}>
                {headline}
              </div>
            )}
            {advice && <p className="text-sm text-gray-700 dark:text-dark-700">{advice}</p>}
          </div>
        )}

        {risk.assessments.map((assessment, index) =>
          assessment.facts.length === 0 && !labelAssessments ? null : (
            <div key={index}>
              {labelAssessments && (
                <div className="mb-1 text-xs font-medium text-gray-600 dark:text-dark-500">
                  {`${assessment.provider || "Shopify"}: ${levelText(assessment.level) || "No risk level"}`}
                </div>
              )}
              {assessment.facts.length > 0 && (
                <ul className="space-y-2 rounded-md bg-gray-50 dark:bg-dark-50 p-3">
                  {assessment.facts.map((fact, factIndex) => (
                    <li key={factIndex} data-sentiment={fact.sentiment ?? undefined} className="flex gap-2 text-sm text-gray-800 dark:text-dark-800">
                      <FactIcon sentiment={fact.sentiment} />
                      <span>{fact.description}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ),
        )}

        {risk.cardholder && <CardholderNameCheck check={risk.cardholder} />}

        {risk.ip && (
          <div className="text-xs text-gray-500 dark:text-dark-400">
            <div>{`IP address: ${risk.ip}`}</div>
            {risk.ip_location && <div>{`Location of IP address used to place the order is ${risk.ip_location}`}</div>}
          </div>
        )}
      </div>
    </div>
  );
};

function BadgeMultiSelect<T extends string>({
  options,
  value,
  onChange,
  badge,
  placeholder,
  id,
}: {
  options: { value: T; label: string }[];
  value: T[];
  onChange: (values: T[]) => void;
  badge: (value: T) => React.ReactNode;
  placeholder: string;
  id?: string;
}) {
  const summary = options
    .filter((option) => value.includes(option.value))
    .map(({ label }) => label)
    .join(", ");
  return (
    <Listbox
      value={value}
      onChange={(selected: T[]) => onChange(options.map((option) => option.value).filter((v) => selected.includes(v)))}
      multiple
    >
      <div className="relative">
        <Listbox.Button
          id={id}
          className="relative h-10 w-full cursor-pointer rounded-md border border-gray-300 dark:border-dark-300 bg-white dark:bg-dark-100 pl-5 pr-10 text-left text-gray-900 dark:text-dark-800 shadow-sm focus:outline-none focus:border-shopify-500 sm:text-sm"
        >
          <span className="block truncate">{summary || placeholder}</span>
          <span className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-2">
            <ChevronUpDownIcon className="h-5 w-5 text-gray-400" aria-hidden="true" />
          </span>
        </Listbox.Button>
        <Listbox.Options className="absolute z-10 mt-1 w-full overflow-auto rounded-md bg-white dark:bg-dark-100 py-1 text-sm shadow-lg ring-1 ring-black ring-opacity-5 focus:outline-none">
          {options.map((option) => (
            <Listbox.Option
              key={option.value}
              value={option.value}
              className={({ active }) =>
                `relative cursor-pointer select-none py-2 pl-9 pr-4 ${
                  active ? "bg-shopify-50 dark:bg-dark-200" : ""
                } text-gray-900 dark:text-dark-800`
              }
            >
              {({ selected }) => (
                <>
                  {selected && (
                    <span className="absolute inset-y-0 left-0 flex items-center pl-3 text-shopify-600 dark:text-shopify-400">
                      <CheckIcon className="h-4 w-4" aria-hidden="true" />
                    </span>
                  )}
                  {badge(option.value)}
                  <span className="sr-only">{option.label}</span>
                </>
              )}
            </Listbox.Option>
          ))}
        </Listbox.Options>
      </div>
    </Listbox>
  );
}

const FILTER_LEVELS: { value: RiskLevel; label: string }[] = [
  { value: "HIGH", label: "High" },
  { value: "MEDIUM", label: "Medium" },
  { value: "LOW", label: "Low" },
  { value: "PENDING", label: "Pending" },
];

export const RiskLevelFilter: React.FC<{ value: RiskLevel[]; onChange: (levels: RiskLevel[]) => void; id?: string }> = ({
  value,
  onChange,
  id,
}) => (
  <BadgeMultiSelect
    id={id}
    options={FILTER_LEVELS}
    value={value}
    onChange={onChange}
    badge={(level) => <RiskLevelBadge level={level} />}
    placeholder="All Levels"
  />
);

const FILTER_CARDHOLDER_MATCHES: { value: CardholderMatch; label: string }[] = [
  { value: "MISMATCH", label: "Mismatch" },
  { value: "LAST_NAME_ONLY", label: "Last name only" },
  { value: "MATCH", label: "Match" },
];

export const CardholderMatchFilter: React.FC<{
  value: CardholderMatch[];
  onChange: (matches: CardholderMatch[]) => void;
  id?: string;
}> = ({ value, onChange, id }) => (
  <BadgeMultiSelect
    id={id}
    options={FILTER_CARDHOLDER_MATCHES}
    value={value}
    onChange={onChange}
    badge={(match) => <CardholderMatchBadge match={match} />}
    placeholder="Any Match"
  />
);

export default OrderRiskEvaluation;
