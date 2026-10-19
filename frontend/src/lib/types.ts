export type UsageStatus = "active" | "inactive";
export type ServiceStatus = "active" | "suspended" | "expired" | "unknown";
export type RenewalStatus = "unknown" | "renewed" | "not_renewed";
export type MonitoringStatus = "current" | "due" | "partial" | "failed" | "manual";
export type DataSource = "manual" | "rdap" | "whois" | "provider";
export type Urgency = "ok" | "upcoming" | "urgent" | "today" | "overdue" | "unknown";
export type DeliveryStatus = "queued" | "sending" | "sent" | "failed" | "cancelled";

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface Expiration {
  days_remaining: number | null;
  urgency: Urgency;
  label: string;
}

export interface RecordBase {
  id: string;
  expiration_date: string | null;
  expiration_source: DataSource;
  expiration_verified_at: string | null;
  expiration: Expiration;
  usage_status: UsageStatus;
  service_status: ServiceStatus;
  service_status_source: DataSource;
  renewal_status: RenewalStatus;
  renewal_confirmed_for_date: string | null;
  auto_check_enabled: boolean;
  notifications_enabled: boolean;
  monitoring_status: MonitoringStatus;
  last_checked_at: string | null;
  last_successful_check_at: string | null;
  next_check_at: string | null;
  check_requested_at: string | null;
  last_check_error: string | null;
  is_stale: boolean;
  notes: string | null;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
}

export interface HostingRef {
  id: string;
  name: string;
  provider_name: string;
}

export interface Domain extends RecordBase {
  domain_name: string;
  normalized_domain_name: string;
  display_name: string;
  hosting_account: HostingRef | null;
  registrar: RegistrarRef | null;
  registration_date: string | null;
  registrar_name: string | null;
  registry_statuses: string[];
}

export interface DomainSummary {
  id: string;
  domain_name: string;
  expiration_date: string | null;
  expiration: Expiration;
  usage_status: UsageStatus;
  service_status: ServiceStatus;
  monitoring_status: MonitoringStatus;
}

export interface Hosting extends RecordBase {
  name: string;
  provider_name: string;
  registrar: RegistrarRef | null;
  purchase_date: string | null;
  has_admin_url: boolean;
  integration: { id: string; name: string; adapter: string } | null;
  external_ref: string | null;
  domain_count: number;
}

export interface HostingDetail extends Hosting {
  domains: DomainSummary[];
}

export interface MonitoringCheck {
  id: string;
  record_type: "domain" | "hosting";
  source: string;
  result: "success" | "partial" | "failure";
  checked_at: string;
  duration_ms: number | null;
  observed_data: Record<string, unknown>;
  changes: Record<string, { from: unknown; to: unknown }>;
  conflicts: Record<string, { saved: unknown; observed: unknown; reason: string }>;
  error_code: string | null;
  error_message: string | null;
}

export interface AuditEvent {
  id: string;
  created_at: string;
  actor: string;
  action: string;
  record_type: string | null;
  record_id: string | null;
  details: Record<string, unknown>;
}

export interface NotificationEvent {
  id: string;
  is_test: boolean;
  record_type: "domain" | "hosting" | null;
  domain_id: string | null;
  hosting_account_id: string | null;
  record_name: string | null;
  expiration_date_at_send: string | null;
  reminder_interval: string;
  recipient: string;
  subject: string | null;
  delivery_status: DeliveryStatus;
  attempt_count: number;
  next_attempt_at: string | null;
  last_attempt_at: string | null;
  provider_message_id: string | null;
  sent_at: string | null;
  last_error: string | null;
  created_at: string;
}

export interface NotificationSettings {
  notifications_enabled: boolean;
  notification_recipients: string[];
  reminder_days_before: number[];
  remind_on_expiration_day: boolean;
  overdue_reminder_days: number;
  remind_suspended: boolean;
  ses_region: string | null;
  ses_sender: string | null;
  ses_configuration_set: string | null;
  ses_auth_method: "default_chain" | "access_keys";
  ses_credentials_set: boolean;
  ses_last_validated_at: string | null;
  ses_last_validation: SesChecks | Record<string, never>;
}

export interface SesChecks {
  region: string | null;
  sender: string | null;
  credentials: boolean | null;
  sending_enabled: boolean | null;
  production_access: boolean | null;
  sender_verified: boolean | null;
  quota: { max_24_hour_send: number; max_send_rate: number; sent_last_24_hours: number } | null;
  problems: string[];
}

export interface TestEmailResult {
  ok: boolean;
  accepted: boolean;
  message: string;
  checks: SesChecks;
  provider_message_id?: string | null;
}

export interface GeneralSettings {
  timezone: string;
  domain_check_interval_hours: number;
  hosting_check_interval_hours: number;
  stale_after_hours: number;
  public_page_enabled: boolean;
}

export interface FieldSpec {
  key: string;
  label: string;
  required: boolean;
  help: string;
}

export interface AdapterInfo {
  key: string;
  label: string;
  description: string;
  auth_method: string;
  supported_fields: string[];
  config_fields: FieldSpec[];
  secret_fields: FieldSpec[];
}

export interface Integration {
  id: string;
  name: string;
  adapter: string;
  enabled: boolean;
  config: Record<string, unknown>;
  secret_set: boolean;
  last_tested_at: string | null;
  last_test_ok: boolean | null;
  last_test_message: string | null;
  hosting_account_count: number;
  created_at: string;
}

export interface SummaryCounts {
  total: number;
  active: number;
  inactive: number;
  expired: number;
  suspended: number;
  unknown_expiration: number;
  overdue: number;
  expiring_30_days: number;
  monitoring_failed: number;
  monitoring_partial: number;
  stale: number;
}

export interface UpcomingItem {
  record_type: "domain" | "hosting";
  id: string;
  name: string;
  expiration_date: string;
  expiration: Expiration;
  usage_status: UsageStatus;
  service_status: ServiceStatus;
  context: string;
}

export interface Dashboard {
  today: string;
  timezone: string;
  domains: SummaryCounts;
  hosting: SummaryCounts;
  upcoming: UpcomingItem[];
  notifications_last_7_days: { sent: number; failed: number; queued: number };
  notifications_enabled: boolean;
  jobs: { name: string; last_started_at: string | null; last_finished_at: string | null; last_status: string | null; last_error: string | null }[];
  scheduler_stale: boolean;
  warnings: string[];
}

export interface CheckQueued {
  status: "queued" | "already_queued" | "not_supported" | "completed";
  requested_at: string | null;
  message: string;
}

export interface RegistrarRef {
  id: string;
  name: string;
}

export interface Registrar extends RegistrarRef {
  website: string | null;
  notes: string | null;
  for_domains: boolean;
  for_hosting: boolean;
  domain_count: number;
  hosting_count: number;
  created_at: string;
  updated_at: string;
}
