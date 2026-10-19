import { deliveryLabels, monitoringLabels, renewalLabels, serviceLabels, usageLabels } from "@/lib/format";
import type {
  DeliveryStatus,
  Expiration,
  MonitoringStatus,
  RenewalStatus,
  ServiceStatus,
  UsageStatus,
} from "@/lib/types";

type Tone = "ok" | "info" | "warn" | "urgent" | "danger" | "neutral";

export function Badge({ tone, children, title }: { tone: Tone; children: React.ReactNode; title?: string }) {
  return (
    <span className={`badge ${tone}`} title={title}>
      {children}
    </span>
  );
}

export function UsageBadge({ status, prefix }: { status: UsageStatus; prefix?: string }) {
  return (
    <Badge tone={status === "active" ? "info" : "neutral"} title="Usage: whether a product or website uses it">
      <span className="dot" aria-hidden />
      {prefix && `${prefix}: `}
      {usageLabels[status]}
    </Badge>
  );
}

const serviceTone: Record<ServiceStatus, Tone> = { active: "ok", suspended: "urgent", expired: "danger", unknown: "neutral" };

export function ServiceBadge({ status, prefix }: { status: ServiceStatus; prefix?: string }) {
  return (
    <Badge tone={serviceTone[status]} title="Registration / service status">
      {prefix && `${prefix}: `}
      {serviceLabels[status]}
    </Badge>
  );
}

const renewalTone: Record<RenewalStatus, Tone> = { unknown: "neutral", renewed: "ok", not_renewed: "danger" };

export function RenewalBadge({ status }: { status: RenewalStatus }) {
  return <Badge tone={renewalTone[status]}>{renewalLabels[status]}</Badge>;
}

const monitoringTone: Record<MonitoringStatus, Tone> = {
  current: "ok",
  due: "info",
  partial: "warn",
  failed: "danger",
  manual: "neutral",
};

export function MonitoringBadge({ status, stale }: { status: MonitoringStatus; stale?: boolean }) {
  return (
    <span className="badges">
      <Badge tone={monitoringTone[status]} title="Monitoring status">
        {monitoringLabels[status]}
      </Badge>
      {stale && (
        <Badge tone="warn" title="No successful check recently">
          Stale
        </Badge>
      )}
    </span>
  );
}

const urgencyTone: Record<Expiration["urgency"], Tone> = {
  ok: "ok",
  upcoming: "warn",
  urgent: "urgent",
  today: "danger",
  overdue: "danger",
  unknown: "neutral",
};

/** Round indicator for how close a record is to expiring; pulses when action is due. */
export function ExpiryDot({ expiration }: { expiration: Expiration }) {
  const tone = urgencyTone[expiration.urgency];
  const pulse = expiration.urgency === "today" || expiration.urgency === "overdue" || expiration.urgency === "urgent";
  return <span className={`status-dot ${tone}${pulse ? " pulse" : ""}`} title={expiration.label} aria-hidden />;
}

export function ExpirationBadge({ expiration }: { expiration: Expiration }) {
  return <Badge tone={urgencyTone[expiration.urgency]}>{expiration.label}</Badge>;
}

const deliveryTone: Record<DeliveryStatus, Tone> = {
  queued: "info",
  sending: "info",
  sent: "ok",
  failed: "danger",
  cancelled: "neutral",
};

export function DeliveryBadge({ status }: { status: DeliveryStatus }) {
  return <Badge tone={deliveryTone[status]}>{deliveryLabels[status]}</Badge>;
}

export function CheckResultBadge({ result }: { result: "success" | "partial" | "failure" }) {
  const tone: Tone = result === "success" ? "ok" : result === "partial" ? "warn" : "danger";
  return <Badge tone={tone}>{result === "success" ? "Success" : result === "partial" ? "Partial" : "Failed"}</Badge>;
}
