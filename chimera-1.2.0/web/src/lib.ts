import type { Boot, Event } from "./types";

export function networkInfo(cfg: Boot["cfg"]) {
  const reverse = cfg.topology?.entry === "foreign";
  return {
    reverse,
    entry: reverse ? "Зарубежный вход" : "Вход RU",
    entryCountry: reverse ? "Зарубежный" : "Россия",
    entryCode: reverse ? "Зарубежный вход" : "RU",
    remote: reverse ? "Выход RU" : "Зарубежный выход",
    branch: reverse ? "Путь в Россию" : "Зарубежный путь",
    ruRoute: reverse ? "Через сервер RU" : "Напрямую из RU",
    foreignRoute: reverse ? "Напрямую за рубежом" : "Через зарубежный узел",
    summary: reverse
      ? "Клиенты подключаются к зарубежному узлу. Российские назначения идут через сервер RU, остальные выходят прямо с зарубежного входа."
      : "Клиенты подключаются к RU. Российские назначения выходят напрямую из RU, остальные идут через зарубежный узел.",
    failure: reverse
      ? "Если оба пути до RU недоступны, российская ветка блокируется. Зарубежный трафик продолжает выходить напрямую."
      : "Если оба зарубежных пути недоступны, зарубежная ветка блокируется. Российский трафик продолжает выходить напрямую из RU.",
  };
}

export const bytes = (n?: number | null): string => {
  if (n == null) return "—";
  const i = n > 0 ? Math.min(4, Math.floor(Math.log(n) / Math.log(1024))) : 0;
  return `${(n / 1024 ** i).toLocaleString("ru", { maximumFractionDigits: i ? 1 : 0 })} ${["Б", "КБ", "МБ", "ГБ", "ТБ"][i]}`;
};
export const rate = (n?: number | null) =>
  n == null
    ? "—"
    : ((n * 8) / 1e6).toLocaleString("ru", { maximumFractionDigits: 2 });
export const date = (n?: number | null) =>
  n
    ? new Date(n * 1000).toLocaleString("ru", {
        day: "numeric",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "Ещё не было";
export const time = (n: number) =>
  new Date(n * 1000).toLocaleTimeString("ru", {
    hour: "2-digit",
    minute: "2-digit",
  });
export const uptime = (n?: number) =>
  n == null
    ? "—"
    : n >= 86400
      ? `${Math.floor(n / 86400)} д ${Math.floor((n % 86400) / 3600)} ч`
      : `${Math.floor(n / 3600)} ч ${Math.floor((n % 3600) / 60)} мин`;
export const pathName = (v?: string) =>
  ({ primary: "VLESS REALITY", backup: "Hysteria2", closed: "Путь закрыт" })[
    v || ""
  ] || "Ожидание данных";
export const pathState = (v?: string) =>
  ({
    available: "Доступен",
    unavailable: "Недоступен",
    unknown: "Нет данных",
    disabled: "Отключён",
  })[v || ""] || "Нет данных";
export const deviceState = (d: { desired: number; state: string }) =>
  d.state === "failed"
    ? "Ошибка применения"
    : d.state === "pending"
      ? "Применяется"
      : !d.desired
        ? "Доступ отозван"
        : "Профиль готов";
export const eventTitle = (e: Event) =>
  ({
    user_created: "Создан пользователь",
    device_created: "Добавлено устройство",
    device_revoke: "Отозвано устройство",
    device_rotated: "Заменены ключи",
    device_rotate: "Заменены ключи",
    device_renamed: "Переименовано устройство",
    user_block: "Пользователь заблокирован",
    user_unblock: "Доступ пользователя восстановлен",
    revoke_all: "Отозваны все устройства",
    password_changed: "Изменён пароль",
    invitation_created: "Создано приглашение",
    invitation_consumed: "Приглашение использовано",
    applied: "Конфигурация применена",
    apply_failed: "Ошибка применения",
    path_changed: "Переключён межсерверный путь",
    path_mode: "Изменён режим маршрута",
    foreign_down: "Зарубежные пути недоступны",
    foreign_recovered: "Зарубежный путь восстановлен",
    hop_down: "Межсерверные пути недоступны",
    hop_recovered: "Межсерверный путь восстановлен",
    rule_added: "Добавлено правило",
    rule_deleted: "Удалено правило",
    telegram_unlinked: "Telegram отвязан",
    passkey_added: "Добавлен ключ входа",
    passkey_removed: "Удалён ключ входа",
    passkey_login: "Вход с ключом доступа",
    device_limit_changed: "Изменён лимит устройств",
    revoked_deleted: "Удалены отозванные профили",
  })[e.kind] || "Изменение настроек";

export async function jsonRequest(
  path: string,
  data?: Record<string, unknown>,
  signal?: AbortSignal,
) {
  const response = await fetch(path, {
    credentials: "same-origin",
    cache: "no-store",
    signal,
    ...(data
      ? {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(data),
        }
      : {}),
  });
  if (response.redirected && new URL(response.url).pathname === "/login") {
    location.assign("/login");
    throw new Error("Войдите заново");
  }
  if (!response.headers.get("content-type")?.includes("application/json"))
    throw new Error("Сервер не ответил. Обновите страницу.");
  const result = await response.json();
  if (!response.ok)
    throw new Error(result.error || result.detail || "Действие не выполнено");
  return result;
}

function decode(value: string): ArrayBuffer {
  const raw = atob(value.replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from(raw, (x) => x.charCodeAt(0)).buffer;
}
function encode(value: ArrayBuffer | null) {
  if (!value) return null;
  return btoa(String.fromCharCode(...new Uint8Array(value)))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}
function credentialJSON(credential: PublicKeyCredential) {
  const response = credential.response;
  const base = {
    id: credential.id,
    rawId: encode(credential.rawId),
    type: credential.type,
    clientExtensionResults: credential.getClientExtensionResults(),
    authenticatorAttachment: credential.authenticatorAttachment,
  };
  return response instanceof AuthenticatorAttestationResponse
    ? {
        ...base,
        response: {
          clientDataJSON: encode(response.clientDataJSON),
          attestationObject: encode(response.attestationObject),
          transports: response.getTransports(),
        },
      }
    : {
        ...base,
        response: {
          clientDataJSON: encode(response.clientDataJSON),
          authenticatorData: encode(
            (response as AuthenticatorAssertionResponse).authenticatorData,
          ),
          signature: encode(
            (response as AuthenticatorAssertionResponse).signature,
          ),
          userHandle: encode(
            (response as AuthenticatorAssertionResponse).userHandle,
          ),
        },
      };
}
export async function usePasskey(
  csrf: string,
  register = false,
  password = "",
  label = "",
  remember = false,
) {
  if (!window.PublicKeyCredential || !window.isSecureContext)
    throw new Error("Ключи входа доступны в совместимом браузере по HTTPS.");
  const base = `/api/passkeys/${register ? "register" : "login"}`;
  const options = await jsonRequest(`${base}/begin`, { csrf, password });
  const key = options.publicKey;
  key.challenge = decode(key.challenge);
  if (register) {
    key.user.id = decode(key.user.id);
    key.excludeCredentials = (key.excludeCredentials || []).map(
      (c: { id: string }) => ({ ...c, id: decode(c.id) }),
    );
  } else if (key.allowCredentials)
    key.allowCredentials = key.allowCredentials.map((c: { id: string }) => ({
      ...c,
      id: decode(c.id),
    }));
  let credential;
  try {
    credential = register
      ? await navigator.credentials.create({ publicKey: key })
      : await navigator.credentials.get({ publicKey: key });
  } catch (e) {
    if (e instanceof DOMException && e.name === "NotAllowedError")
      throw new Error("Подтверждение отменено или время ожидания истекло.");
    throw e;
  }
  if (!(credential instanceof PublicKeyCredential))
    throw new Error("Ключ входа не получен");
  const result = await jsonRequest(`${base}/complete`, {
    csrf,
    credential: credentialJSON(credential),
    label,
    remember,
  });
  location.assign(result.redirect);
}
