-- Check fraud analysis duplicate detection status
-- This query shows recent fraud analyses and their duplicate detection values

-- Show recent fraud analyses with duplicate detection info
SELECT 
    fa.id,
    fa.order_name,
    fa.customer_name,
    fa.is_first_time_customer,
    fa.duplicate_within_7days,
    fa.analysis_timestamp,
    fa.shopify_fraud_risk_level,
    s.duplicate_detection_days as user_setting_days,
    u.email as user_email
FROM fraud_analysis fa
JOIN shopify_stores ss ON fa.store_id = ss.id
JOIN users u ON fa.user_id = u.id
LEFT JOIN settings s ON s.user_id = u.id
WHERE fa.analysis_timestamp >= datetime('now', '-7 days')
ORDER BY fa.analysis_timestamp DESC
LIMIT 20;

-- Check if any fraud rules are checking duplicate_within_7days
SELECT 
    fdr.id,
    fdr.name,
    fdr.conditions,
    fdr.is_active,
    fdr.priority,
    u.email as user_email
FROM fraud_detection_rules fdr
JOIN users u ON fdr.user_id = u.id
WHERE fdr.conditions LIKE '%duplicate_within_7days%'
  AND fdr.is_active = 1
ORDER BY fdr.priority;

-- Show orders with multiple fraud analyses (potential duplicates)
SELECT 
    order_name,
    COUNT(*) as analysis_count,
    GROUP_CONCAT(duplicate_within_7days) as duplicate_values,
    GROUP_CONCAT(analysis_timestamp) as timestamps
FROM fraud_analysis
WHERE analysis_timestamp >= datetime('now', '-7 days')
GROUP BY order_name
HAVING COUNT(*) > 1
ORDER BY analysis_count DESC;