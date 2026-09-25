import React from "react";
import { CheckCircleIcon, ExclamationTriangleIcon, InformationCircleIcon } from "@heroicons/react/24/outline";

export type RiskLevel = "HIGH" | "MEDIUM" | "LOW" | "NONE" | "PENDING";
export type RiskRecommendation = "ACCEPT" | "INVESTIGATE" | "CANCEL" | "NONE";
type FactSentiment = "POSITIVE" | "NEGATIVE" | "NEUTRAL";

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
}

const LEVEL_LABEL: Partial<Record<RiskLevel, string>> = { HIGH: "High", MEDIUM: "Medium", LOW: "Low" };

const LEVEL_TEXT_CLASS: Partial<Record<RiskLevel, string>> = {
  HIGH: "text-red-700 dark:text-red-400",
  MEDIUM: "text-amber-700 dark:text-amber-400",
  LOW: "text-green-700 dark:text-green-400",
};

const LEVEL_BADGE_CLASS: Partial<Record<RiskLevel, string>> = {
  HIGH: "bg-red-100 text-red-800 dark:bg-red-900/20 dark:text-red-400",
  MEDIUM: "bg-amber-100 text-amber-800 dark:bg-amber-900/20 dark:text-amber-400",
  LOW: "bg-green-100 text-green-800 dark:bg-green-900/20 dark:text-green-400",
  PENDING: "bg-gray-100 text-gray-700 dark:bg-dark-200 dark:text-dark-600",
};

const ADVICE: Partial<Record<RiskRecommendation, string>> = {
  ACCEPT: "You can fulfill this order",
  INVESTIGATE: "Investigate this order before fulfilling it",
  CANCEL: "Consider canceling this order",
};

const levelText = (level: RiskLevel | null) => (level && LEVEL_LABEL[level] ? `${LEVEL_LABEL[level]} risk` : null);

const FactIcon: React.FC<{ sentiment: FactSentiment | null }> = ({ sentiment }) => {
  if (sentiment === "NEGATIVE") return <ExclamationTriangleIcon className="h-5 w-5 flex-none text-red-600 dark:text-red-400" />;
  if (sentiment === "POSITIVE") return <CheckCircleIcon className="h-5 w-5 flex-none text-green-700 dark:text-green-400" />;
  return <InformationCircleIcon className="h-5 w-5 flex-none text-gray-500 dark:text-dark-400" />;
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

export default OrderRiskEvaluation;
