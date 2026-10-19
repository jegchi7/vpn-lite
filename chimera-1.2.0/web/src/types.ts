export interface User {
  id: number;
  login: string;
  admin: number;
  device_limit: number;
  telegram_id: number | null;
  csrf: string;
}
export interface Usage {
  download: number | null;
  upload: number | null;
  download_total: number | null;
  upload_total: number | null;
  last_handshake?: number;
}
export interface Device {
  id: string;
  name: string;
  desired: number;
  state: string;
  created: number;
  ip?: string;
  usage?: Usage | null;
}
export interface Path {
  state?: string;
  latency_ms?: number | null;
  failures?: number;
  successes?: number;
  destinations?: { state: string; latency_ms: number | null }[];
}
export interface Monitor {
  active?: string;
  mode?: string;
  checked_at?: number;
  stale: boolean;
  primary?: Path;
  backup?: Path;
}
export interface Sample {
  created: number;
  download: number | null;
  upload: number | null;
  cpu?: number | null;
  memory?: number | null;
  connections?: number | null;
}
export interface Metrics {
  checked_at?: number;
  stale: boolean;
  download?: number | null;
  upload?: number | null;
  download_total?: number;
  upload_total?: number;
  uptime?: number;
  cpu?: number | null;
  memory?: number;
  connections?: number;
  core_available?: boolean;
  protocols?: Record<string, number>;
}
export interface Event {
  created: number;
  kind: string;
  detail: string;
  actor_login?: string | null;
}
export interface ManagedUser {
  id: number;
  login: string;
  admin: number;
  blocked: number;
  device_limit: number;
  device_count: number;
  telegram_id: number | null;
  activated: number;
  created: number;
}
export interface Rule {
  id: number;
  kind: string;
  value: string;
  action: string;
  priority: number;
}
export interface State {
  checked_at: number;
  devices: Device[];
  monitor: Monitor;
  usage: Usage;
  telemetry_stale: boolean;
  events: Event[];
  metrics?: Metrics;
  history?: {
    period: string;
    points: Sample[];
    totals: { download: number | null; upload: number | null };
  };
  users?: ManagedUser[];
  rules?: Rule[];
  mode?: string;
  status?: {
    components: Record<string, string>;
    revision?: number;
    lists_version?: string;
    gateways?: {
      role: string;
      region: string;
      endpoint: string;
      port: number;
    }[];
  };
  revisions?: {
    id: number;
    state: string;
    error: string | null;
    created: number;
  }[];
}
export interface Boot {
  view: string;
  user?: User | null;
  cfg: {
    endpoint: string;
    topology?: { entry: "ru" | "foreign"; remote: "ru" | "foreign" };
    url: string;
    bot_username: string;
    admin_slug?: string;
    limits: { devices: number; users: number };
    awg: { gateway: string; port: number };
    vless: { port: number; server_name: string };
  };
  state?: State;
  csrf?: string;
  error?: string;
  password_min?: number;
  login?: string;
  value?: string;
  intent?: string;
  device?: Device;
  profile?: string | null;
  protocol?: string;
  title?: string;
  note?: string;
  link?: string;
  result?: { value: string; route: string; reason: string };
  passkeys?: {
    id: string;
    label: string;
    created: number;
    last_used: number | null;
  }[];
}
