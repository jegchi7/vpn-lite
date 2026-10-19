<script lang="ts">
  import { onMount, untrack } from "svelte";
  import type { Boot, State, Sample } from "./types";
  import Auth from "./components/Auth.svelte";
  import Logo from "./components/Logo.svelte";
  import Icon from "./components/Icon.svelte";
  import Form from "./components/Form.svelte";
  import Badge from "./components/Badge.svelte";
  import UserDashboard from "./components/UserDashboard.svelte";
  import Admin from "./components/Admin.svelte";
  import Device from "./components/Device.svelte";
  import Account from "./components/Account.svelte";
  import Guide from "./components/Guide.svelte";
  import { jsonRequest, date, networkInfo } from "./lib";
  let { boot }: { boot: Boot } = $props();
  const geo = $derived(networkInfo(boot.cfg));
  const empty: State = {
    checked_at: 0,
    devices: [],
    monitor: { stale: true },
    usage: {
      download: null,
      upload: null,
      download_total: null,
      upload_total: null,
    },
    telemetry_stale: true,
    events: [],
  };
  let data = $state<State>(untrack(() => boot.state || empty));
  let live = $state<Sample[]>([]);
  let period = $state("24h");
  let hash = $state(location.hash.slice(1));
  let navOpen = $state(false);
  let refreshError = $state("");
  let copied = $state(false);
  let controller: AbortController | undefined;
  let lastPeriod = "24h";
  const administrative = $derived(boot.view === "admin");
  const base = $derived(`/manage/${boot.cfg.admin_slug}`);
  const activeSection = $derived(
    boot.view === "devices"
      ? hash === "new-device"
        ? "devices"
        : ["overview", "devices", "network", "activity"].includes(hash)
          ? hash
          : "overview"
      : administrative
        ? hash === "invite-user"
          ? "users"
          : [
                "overview",
                "network",
                "users",
                "access",
                "gateways",
                "routing",
                "events",
              ].includes(hash)
            ? hash
            : "overview"
        : boot.view === "device"
          ? "devices"
          : boot.view,
  );
  const navigation = $derived(
    administrative
      ? [
          ["overview", "grid", "Обзор"],
          ["network", "activity", "Сеть"],
          ["users", "users", "Пользователи"],
          ["access", "key", "Доступ"],
          ["gateways", "server", "Узлы"],
          ["routing", "route", "Маршрутизация"],
          ["events", "activity", "События"],
        ]
      : [
          ["overview", "grid", "Обзор"],
          ["devices", "smartphone", "Устройства"],
          ["network", "globe", "Сеть"],
          ["activity", "activity", "Мои действия"],
        ],
  );
  const titles: Record<string, string> = {
    overview: "Обзор сети",
    devices: "Мои устройства",
    network: "Сеть и маршруты",
    activity: "Мои действия",
    users: "Пользователи",
    access: "Управление доступом",
    gateways: "Узлы сети",
    routing: "Маршрутизация",
    events: "События сети",
    account: "Учётная запись",
    guide: "Подключение",
    invitation: "Приглашение",
    explain: "Результат проверки",
    error: "Действие не выполнено",
  };
  const available = $derived(
    !data.monitor.stale &&
      (data.monitor.active === "primary"
        ? data.monitor.primary
        : data.monitor.active === "backup"
          ? data.monitor.backup
          : undefined
      )?.state === "available",
  );
  async function refresh() {
    if (!boot.user || document.hidden) return;
    controller?.abort();
    const request = new AbortController();
    controller = request;
    try {
      const next: State = await jsonRequest(
        administrative
          ? `/api/manage/${boot.cfg.admin_slug}?period=${period}`
          : "/api/state",
        undefined,
        request.signal,
      );
      data = next;
      refreshError = "";
      if (
        !next.telemetry_stale &&
        (next.usage.download != null || next.usage.upload != null)
      )
        live = [
          ...live.slice(-59),
          {
            created: next.checked_at,
            download: next.usage.download,
            upload: next.usage.upload,
          },
        ];
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") return;
      refreshError =
        "Не удалось обновить данные. Показан последний полученный статус.";
      data.monitor = { ...data.monitor, stale: true };
      data.telemetry_stale = true;
      data.usage = {
        download: null,
        upload: null,
        download_total: null,
        upload_total: null,
      };
      if (data.metrics) data.metrics = { ...data.metrics, stale: true };
    }
  }
  $effect(() => {
    if (period !== lastPeriod) {
      lastPeriod = period;
      void refresh();
    }
  });
  onMount(() => {
    if (boot.user) {
      if (
        !data.telemetry_stale &&
        (data.usage.download != null || data.usage.upload != null)
      )
        live = [
          {
            created: data.checked_at,
            download: data.usage.download,
            upload: data.usage.upload,
          },
        ];
    }
    const changeHash = () => {
      if (location.hash !== "#main-content") hash = location.hash.slice(1);
      navOpen = false;
    };
    const visible = () => {
      if (!document.hidden) void refresh();
    };
    window.addEventListener("hashchange", changeHash);
    document.addEventListener("visibilitychange", visible);
    const timer = setInterval(() => void refresh(), 10000);
    return () => {
      clearInterval(timer);
      controller?.abort();
      window.removeEventListener("hashchange", changeHash);
      document.removeEventListener("visibilitychange", visible);
    };
  });
  async function copyLink() {
    try {
      await navigator.clipboard.writeText(boot.link || "");
      copied = true;
      setTimeout(() => (copied = false), 2200);
    } catch {
      refreshError = "Выделите и скопируйте ссылку вручную.";
    }
  }
</script>

<svelte:head
  ><title
    >CHIMERA · {boot.user
      ? titles[activeSection] || "Личный кабинет"
      : "Вход"}</title
  ></svelte:head
>
{#if !boot.user && boot.view !== "error"}<Auth {boot} />
{:else if !boot.user}<main class="public-error">
    <Logo />
    <section class="card padded">
      <span class="eyebrow">CHIMERA</span>
      <h1>Действие не выполнено</h1>
      <p>{boot.error}</p>
      <a class="button secondary" href="/login">Вернуться ко входу</a>
    </section>
  </main>
{:else}<a href="#main-content" class="skip-link">Перейти к содержимому</a>
  <div class="app-shell">
    {#if navOpen}<button
        type="button"
        class="nav-scrim"
        aria-label="Закрыть меню"
        onclick={() => (navOpen = false)}
      ></button>{/if}
    <aside class="sidebar" class:mobile-open={navOpen} id="main-navigation">
      <Logo />
      <nav aria-label="Основная навигация">
        {#each navigation as [id, icon, label]}<a
            class:active={activeSection === id}
            aria-current={activeSection === id ? "page" : undefined}
            href={`${administrative ? base : "/"}#${id}`}
            title={label}
            onclick={() => (navOpen = false)}
            ><Icon name={icon} /><span>{label}</span></a
          >{/each}{#if !administrative && boot.user.admin}<a
            href={base}
            title="Панель владельца"
            ><Icon name="server" /><span>Управление</span></a
          >{:else if administrative}<a href="/" title="Личный кабинет"
            ><Icon name="smartphone" /><span>Личный кабинет</span></a
          >{/if}
      </nav>
      <div class="sidebar-bottom">
        <div class="help-card">
          <b>Подключить устройство</b>
          <p>Инструкции для телефона и компьютера.</p>
          <a href="/guide">Открыть инструкции <Icon name="arrow" size={14} /></a
          >
        </div>
        <a class="account" href="/account" title="Учётная запись"
          ><span>{boot.user.login.slice(0, 2).toUpperCase()}</span>
          <div>
            <b>{boot.user.login}</b><small
              >{boot.user.admin ? "Владелец" : "Личный доступ"}</small
            >
          </div>
          <Icon name="chevron" size={15} /></a
        ><Form action="/logout" csrf={boot.user.csrf}
          ><button class="logout" title="Выйти"
            ><Icon name="logout" size={16} /><span>Выйти</span></button
          ></Form
        >
      </div>
    </aside>
    <main class="main">
      <header class="topbar">
        <button
          class="mobile-menu"
          type="button"
          aria-label={navOpen ? "Закрыть меню" : "Открыть меню"}
          aria-expanded={navOpen}
          aria-controls="main-navigation"
          onclick={() => (navOpen = !navOpen)}
          ><Icon name={navOpen ? "close" : "menu"} /></button
        >
        <div>
          <span class="eyebrow"
            >{administrative ? "Панель владельца" : "Личный кабинет"}</span
          >
          <h1>{titles[activeSection] || "CHIMERA"}</h1>
        </div>
        <div
          class="live-pill"
          class:unavailable={!available}
          title={`Последняя проверка: ${date(data.monitor.checked_at)}`}
        >
          <i></i>{available
            ? "Путь доступен"
            : data.monitor.stale
              ? "Нет свежих данных"
              : "Проверьте сеть"}
        </div>
      </header>
      <div class="content" id="main-content">
        {#if refreshError}<div class="notice warning" role="status">
            {refreshError}
          </div>{/if}
        {#if boot.view === "admin"}<Admin
            {boot}
            state={data}
            section={activeSection}
            bind:period
          />
        {:else if boot.view === "devices"}<UserDashboard
            {boot}
            state={data}
            section={activeSection}
            {live}
          />
        {:else if boot.view === "device"}<Device {boot} />
        {:else if boot.view === "account"}<Account {boot} />
        {:else if boot.view === "guide"}<Guide {boot} />
        {:else if boot.view === "invitation"}<section class="card message-card">
            <span class="section-icon"><Icon name="key" size={28} /></span><span
              class="eyebrow">Личный доступ</span
            >
            <h2>{boot.title}</h2>
            <p>{boot.note}</p>
            <label
              >Ссылка<input
                class="num"
                value={boot.link}
                readonly
                aria-label="Ссылка приглашения"
                onclick={(e) => e.currentTarget.select()}
              /></label
            >
            <div class="actions">
              <button
                type="button"
                class="button primary-button"
                onclick={copyLink}
                ><Icon name={copied ? "check" : "copy"} />{copied
                  ? "Скопировано"
                  : "Скопировать ссылку"}</button
              >{#if boot.link?.startsWith("https://t.me/")}<a
                  class="button secondary"
                  href={boot.link}
                  target="_blank"
                  rel="noreferrer">Открыть Telegram <Icon name="arrow" /></a
                >{/if}
            </div>
            <a
              class="text-button"
              href={boot.link?.startsWith("https://t.me/")
                ? "/account"
                : `${base}#users`}>← Вернуться</a
            >
          </section>
        {:else if boot.view === "explain"}<section class="card message-card">
            <span class="eyebrow">Предполагаемый маршрут</span>
            <h2>
              {boot.result?.route === "RU_DIRECT"
                ? geo.ruRoute
                : boot.result?.route === "FOREIGN"
                  ? geo.foreignRoute
                  : boot.result?.route === "BLOCK"
                    ? "Заблокировано"
                    : boot.result?.route}
            </h2>
            <Badge tone="muted">{boot.result?.value || "—"}</Badge>
            <p>{boot.result?.reason}</p>
            <div class="note">
              Это объяснение правила маршрутизации, а не наблюдение за реальным
              сеансом.
            </div>
            <a class="button secondary" href={`${base}#routing`}
              >Вернуться к правилам</a
            >
          </section>
        {:else if boot.view === "error"}<section class="card message-card">
            <span class="eyebrow">Действие не выполнено</span>
            <h2>Проверьте данные</h2>
            <p class="notice error" role="alert">{boot.error}</p>
            <div class="actions">
              <a class="button secondary" href="/">Личный кабинет</a
              >{#if boot.user.admin}<a class="button secondary" href={base}
                  >Управление</a
                >{/if}
            </div>
          </section>{/if}
        <footer class="page-footer">
          <span>CHIMERA <i>·</i> Частная VPN-сеть</span><a href="/guide"
            >Подключение и помощь <Icon name="arrow" size={13} /></a
          >
        </footer>
      </div>
    </main>
  </div>{/if}
