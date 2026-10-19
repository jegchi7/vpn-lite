<script lang="ts">
  import type { Boot, State } from "../types";
  import Icon from "./Icon.svelte";
  import Badge from "./Badge.svelte";
  import Form from "./Form.svelte";
  import Chart from "./Chart.svelte";
  import Events from "./Events.svelte";
  import Topology from "./Topology.svelte";
  import {
    bytes,
    rate,
    uptime,
    pathName,
    pathState,
    date,
    networkInfo,
  } from "../lib";
  let {
    boot,
    state: data,
    section,
    period = $bindable("24h"),
  }: { boot: Boot; state: State; section: string; period?: string } = $props();
  let search = $state("");
  let userFilter = $state("all");
  const geo = $derived(networkInfo(boot.cfg));
  const base = $derived(`/manage/${boot.cfg.admin_slug}`);
  const csrf = $derived(boot.user!.csrf);
  const users = $derived(data.users || []);
  const filtered = $derived(
    users.filter(
      (u) =>
        u.login.toLowerCase().includes(search.toLowerCase()) &&
        (userFilter === "all" ||
          (userFilter === "blocked" ? u.blocked : !u.blocked)),
    ),
  );
  const metrics = $derived(data.metrics);
  const available = $derived(
    !data.monitor.stale &&
      (data.monitor.active === "primary"
        ? data.monitor.primary
        : data.monitor.active === "backup"
          ? data.monitor.backup
          : undefined
      )?.state === "available",
  );
  const components: Record<string, string> = {
    "ruvpn-sing": "Ядро VPN",
    "ruvpn-awg": "AmneziaWG",
    "ruvpn-helper": "Помощник",
    "ruvpn-caddy": "HTTPS",
    "ruvpn-panel": "Панель и бот",
  };
  const protocolNames: Record<string, string> = {
    awg: "AmneziaWG",
    vless: "VLESS",
    service: "Служебные",
  };
  const protocolColors: Record<string, string> = {
    awg: "#b8f35d",
    vless: "#5fd6b0",
    service: "#f4bb5f",
  };
</script>

{#snippet people()}
  <div class="page-heading">
    <div>
      <span class="eyebrow">Доступ</span>
      <h2>
        {section === "access" ? "Приглашения и доступ" : "Пользователи"}
        <span class="count">{users.length} / {boot.cfg.limits.users}</span>
      </h2>
      <p>Личные учётные записи, устройства и восстановление входа.</p>
    </div>
    <a class="button primary-button" href="#invite-user"
      ><Icon name="plus" />Пригласить</a
    >
  </div>
  <div class="toolbar">
    <label class="search-field"
      ><Icon name="search" /><input
        bind:value={search}
        placeholder="Найти пользователя"
        aria-label="Поиск пользователя"
      /></label
    >
    <div class="seg">
      {#each [["all", "Все"], ["active", "Доступ разрешён"], ["blocked", "Заблокированные"]] as [id, label]}<button
          type="button"
          class:on={userFilter === id}
          onclick={() => (userFilter = id)}>{label}</button
        >{/each}
    </div>
  </div>
  <section class="card users-card">
    <div class="users-table-head">
      <span>Пользователь</span><span>Устройства</span><span>Состояние</span
      ><span>Управление</span>
    </div>
    {#each filtered as person}<div class="users-table-row">
        <div class="user-cell">
          <span class="avatar">{person.login.slice(0, 2).toUpperCase()}</span>
          <div>
            <b>{person.login}</b><small
              >{person.admin
                ? "Владелец"
                : person.telegram_id
                  ? "Telegram привязан"
                  : "Личный кабинет"}</small
            >
          </div>
        </div>
        <span class="num">{person.device_count} / {person.device_limit}</span
        ><Badge
          tone={person.blocked ? "amber" : person.activated ? "green" : "muted"}
          >{person.blocked
            ? "Заблокирован"
            : person.activated
              ? "Доступ разрешён"
              : "Приглашён"}</Badge
        >
        <details class="row-menu">
          <summary>Действия <Icon name="chevron" size={14} /></summary>
          <div class="row-menu-content">
            <Form action={`${base}/limit`} {csrf} class="limit-form"
              ><input type="hidden" name="section" value="users" /><input
                type="hidden"
                name="user_id"
                value={person.id}
              /><label
                >Лимит устройств<input
                  name="limit"
                  type="number"
                  min="1"
                  max={boot.cfg.limits.devices}
                  value={person.device_limit}
                  required
                /></label
              ><button class="button secondary">Сохранить</button></Form
            >{#if !person.blocked}<Form
                action={`${base}/${person.activated ? "reset" : "invite"}`}
                {csrf}
                ><input type="hidden" name="user_id" value={person.id} /><button
                  class="text-button"
                  >{person.activated
                    ? "Создать ссылку восстановления"
                    : "Новое приглашение"}</button
                ></Form
              >{/if}{#if person.id !== boot.user!.id}<Form
                action={`${base}/${person.blocked ? "unblock" : "block"}`}
                {csrf}
                confirm={person.blocked
                  ? ""
                  : `Заблокировать ${person.login}? Подключения пользователя будут отозваны на сервере.`}
                ><input type="hidden" name="section" value="users" /><input
                  type="hidden"
                  name="user_id"
                  value={person.id}
                /><button
                  class="text-button"
                  class:danger-text={!person.blocked}
                  >{person.blocked
                    ? "Разблокировать"
                    : "Заблокировать доступ"}</button
                ></Form
              >{/if}<Form
              action={`${base}/revoke-all`}
              {csrf}
              confirm={`Отозвать все устройства пользователя ${person.login}?`}
              ><input type="hidden" name="section" value="users" /><input
                type="hidden"
                name="user_id"
                value={person.id}
              /><button class="text-button danger-text"
                >Отозвать все устройства</button
              ></Form
            >
          </div>
        </details>
      </div>{:else}<div class="empty-state">
        <h3>Пользователи не найдены</h3>
        <p>Измените запрос или пригласите пользователя.</p>
      </div>{/each}
  </section>
  <section class="card padded" id="invite-user">
    <span class="eyebrow">Приглашение</span>
    <h3>Добавить пользователя</h3>
    <Form action={`${base}/user`} {csrf} class="inline-form"
      ><label
        >Логин<input
          name="login"
          pattern={"[a-z0-9_.-]{3,32}"}
          placeholder="Например, alex"
          required
          maxlength="32"
        /></label
      ><label
        >Устройств<input
          name="limit"
          type="number"
          min="1"
          max={boot.cfg.limits.devices}
          value={Math.min(3, boot.cfg.limits.devices)}
          required
        /></label
      ><button class="button primary-button"
        ><Icon name="plus" />Создать приглашение</button
      ></Form
    >
    <p class="hint">
      Одноразовая ссылка действует 24 часа. Пользователь сам задаёт пароль от 8
      символов.
    </p>
  </section>
{/snippet}
{#snippet gateways()}
  <div class="two-columns">
    {#each data.status?.gateways || [] as gateway}<section
        class="card padded gateway-card"
      >
        <div class="card-heading flush">
          <span class="stat-icon"
            ><Icon name={gateway.role === "entry" ? "server" : "globe"} /></span
          ><Badge
            tone={gateway.role === "entry"
              ? data.status?.components["ruvpn-sing"] === "active"
                ? "green"
                : "amber"
              : available
                ? "green"
                : "amber"}
            >{gateway.role === "entry"
              ? "Входной узел"
              : "Выходной узел"}</Badge
          >
        </div>
        <h3>
          {gateway.region === "ru" ? "Россия · RU" : "Зарубежный узел"}
        </h3>
        <p class="num muted">{gateway.endpoint}</p>
        {#if gateway.role === "entry"}<dl class="small-dl">
            <div>
              <dt>Работает</dt>
              <dd>{uptime(metrics?.uptime)}</dd>
            </div>
            <div>
              <dt>Процессор</dt>
              <dd>
                {!metrics?.stale && metrics?.cpu != null
                  ? metrics.cpu + "%"
                  : "—"}
              </dd>
            </div>
            <div>
              <dt>Память</dt>
              <dd>
                {!metrics?.stale && metrics?.memory != null
                  ? metrics.memory + "%"
                  : "—"}
              </dd>
            </div>
          </dl>{:else}<dl class="small-dl">
            <div>
              <dt>Основной</dt>
              <dd>
                {pathState(
                  data.monitor.stale ? "unknown" : data.monitor.primary?.state,
                )}
              </dd>
            </div>
            <div>
              <dt>Резервный</dt>
              <dd>
                {pathState(
                  data.monitor.stale ? "unknown" : data.monitor.backup?.state,
                )}
              </dd>
            </div>
            <div>
              <dt>Используется</dt>
              <dd>{pathName(data.monitor.active)}</dd>
            </div>
          </dl>{/if}
      </section>{:else}<section class="card padded">
        <p class="muted">Данные об узлах появятся после ответа помощника.</p>
      </section>{/each}
  </div>
{/snippet}
{#snippet network()}
  <Topology
    monitor={data.monitor}
    endpoint={boot.cfg.endpoint}
    reverse={geo.reverse}
  />
  <div class="two-columns">
    <section class="card padded">
      <span class="eyebrow">Управление маршрутом</span>
      <h3>{geo.branch}</h3>
      <Form action={`${base}/mode`} {csrf}
        ><input type="hidden" name="section" value="network" /><label
          >Режим<select name="mode" value={data.mode}
            ><option value="auto">Автоматически · основной в приоритете</option
            ><option value="primary">Только VLESS REALITY / TCP</option><option
              value="backup">Только Hysteria2 / UDP</option
            ></select
          ></label
        ><button class="button primary-button">Сохранить режим</button></Form
      >
      <p class="hint">
        Изменение применяется в следующем цикле проверки. Переключение может
        прервать текущие соединения.
      </p>
    </section>
    <section class="card padded">
      <span class="eyebrow">Службы</span>
      <h3>Компоненты шлюза</h3>
      <dl class="component-list">
        {#each Object.entries(data.status?.components || {}) as [name, status]}<div
          >
            <dt>{components[name] || name}</dt>
            <dd>
              <Badge tone={status === "active" ? "green" : "amber"}
                >{status === "active" ? "Запущен" : "Недоступен"}</Badge
              >
            </dd>
          </div>{/each}
      </dl>
      <Form
        action={`${base}/apply`}
        {csrf}
        confirm="Повторно применить текущую конфигурацию? VLESS-сессии кратко перезапустятся."
        ><input type="hidden" name="section" value="network" /><button
          class="button secondary">Повторить применение</button
        ></Form
      >
    </section>
  </div>
{/snippet}
{#if section === "users" || section === "access"}{@render people()}
{:else if section === "network"}{@render network()}
{:else if section === "gateways"}<div class="page-heading">
    <div>
      <span class="eyebrow">Инфраструктура</span>
      <h2>Узлы сети</h2>
      <p>{geo.summary} Между узлами — два защищённых транспорта.</p>
    </div>
  </div>
  {@render gateways()}
{:else if section === "routing"}
  <div class="page-heading">
    <div>
      <span class="eyebrow">Политика</span>
      <h2>Правила маршрутизации</h2>
      <p>Ручные назначения применяются перед списками сервисов и адресов.</p>
    </div>
  </div>
  <section class="card padded">
    <div class="rules-list">
      <div class="rules-head">
        <span>Порядок</span><span>Назначение</span><span>Маршрут</span><span
        ></span>
      </div>
      {#each data.rules || [] as rule}<div class="rule-row">
          <span class="num">{rule.priority}</span><span
            ><b>{rule.value}</b><small
              >{rule.kind === "suffix"
                ? "Домен и поддомены"
                : rule.kind === "domain"
                  ? "Точный домен"
                  : "IP / CIDR"}</small
            ></span
          ><Badge tone={rule.action === "BLOCK" ? "amber" : "muted"}
            >{rule.action === "RU_DIRECT"
              ? geo.ruRoute
              : rule.action === "FOREIGN"
                ? geo.foreignRoute
                : "Блокировать"}</Badge
          ><Form
            action={`${base}/delete-rule`}
            {csrf}
            confirm={`Удалить правило для ${rule.value}?`}
            ><input type="hidden" name="section" value="routing" /><input
              type="hidden"
              name="rule_id"
              value={rule.id}
            /><button class="text-button danger-text">Удалить</button></Form
          >
        </div>{:else}<p class="empty-inline">
          Ручных правил нет. Работают списки сервисов и адресов.
        </p>{/each}
    </div>
    <h3>Добавить правило</h3>
    <Form action={`${base}/rule`} {csrf} class="rule-form"
      ><input type="hidden" name="section" value="routing" /><label
        >Тип<select name="kind"
          ><option value="suffix">Домен и поддомены</option><option
            value="domain">Точный домен</option
          ><option value="cidr">IP / CIDR</option></select
        ></label
      ><label
        >Назначение<input
          name="value"
          placeholder="example.com"
          required
          maxlength="253"
        /></label
      ><label
        >Маршрут<select name="route"
          ><option value="FOREIGN">{geo.foreignRoute}</option><option
            value="RU_DIRECT">{geo.ruRoute}</option
          ><option value="BLOCK">Блокировать</option></select
        ></label
      ><label
        >Порядок<input
          name="priority"
          type="number"
          value="100"
          min="-10000"
          max="10000"
          required
        /></label
      ><button class="button primary-button">Добавить</button></Form
    >
    <p class="hint">
      Меньший порядок применяется раньше. Служебные запреты имеют приоритет.
    </p>
  </section>
  <div class="two-columns">
    <section class="card padded">
      <h3>Объяснить маршрут</h3>
      <Form action={`${base}/explain`} {csrf}
        ><label
          >Домен или IP<input
            name="value"
            placeholder="example.com или 1.1.1.1"
            maxlength="253"
            required
          /></label
        ><button class="button secondary"
          >Показать правило <Icon name="arrow" size={16} /></button
        ></Form
      >
      <p class="hint">Показывает решение политики, а не историю посещений.</p>
    </section>
    <section class="card padded">
      <h3>Списки сервисов и IP</h3>
      <p class="muted">
        Текущая версия: <span class="num"
          >{data.status?.lists_version || "—"}</span
        >
      </p>
      <p class="hint">
        Обновление не чаще раза в сутки. Ручные правила сохраняются.
      </p>
      <div class="actions">
        <Form action={`${base}/lists-update`} {csrf}
          ><input type="hidden" name="section" value="routing" /><button
            class="button secondary">Обновить списки</button
          ></Form
        ><Form
          action={`${base}/lists-rollback`}
          {csrf}
          confirm="Вернуть предыдущую версию списков?"
          ><input type="hidden" name="section" value="routing" /><button
            class="button secondary">Откатить списки</button
          ></Form
        >
      </div>
    </section>
  </div>
{:else if section === "events"}<div class="page-heading">
    <div>
      <span class="eyebrow">История управления</span>
      <h2>События сети</h2>
      <p>Действия пользователей и состояние маршрутов.</p>
    </div>
  </div>
  <section class="card padded">
    <h3>Последние применения</h3>
    <div class="revision-list">
      {#each data.revisions || [] as revision}<div>
          <Badge tone={revision.state === "applied" ? "green" : "amber"}
            >#{revision.id} · {revision.state === "applied"
              ? "Применено"
              : revision.state === "pending"
                ? "Применяется"
                : "Ошибка"}</Badge
          ><span>{date(revision.created)}</span>{#if revision.error}<p
              class="danger-text"
            >
              {revision.error}
            </p>{/if}
        </div>{/each}
    </div>
  </section>
  <section class="card"><Events events={data.events} detailed /></section>
{:else}
  <div class="admin-intro">
    <div>
      <Badge tone={available ? "green" : "amber"}
        ><i class="pulse"></i>{data.monitor.stale
          ? "Ожидание свежих данных"
          : available
            ? `${geo.branch} доступен`
            : "Маршрут требует внимания"}</Badge
      >
      <h2>Управление сетью</h2>
      <p>
        {available
          ? `Используется ${pathName(data.monitor.active)}. ${geo.summary}`
          : "Проверьте доступность путей и состояние компонентов."}
      </p>
    </div>
    <a href={`${base}#users`} class="button primary-button"
      ><Icon name="plus" />Пригласить пользователя</a
    >
  </div>
  <div class="stats-grid admin-stats">
    {#each [{ label: "Пользователи", value: String(users.length), detail: `Доступ разрешён: ${users.filter((u) => !u.blocked && u.activated).length}`, icon: "users" }, { label: "Устройства", value: String(users.reduce((n, u) => n + u.device_count, 0)), detail: "С действующим доступом", icon: "smartphone" }, { label: "Трафик за период", value: bytes(data.history?.totals.download != null || data.history?.totals.upload != null ? (data.history?.totals.download || 0) + (data.history?.totals.upload || 0) : null), detail: "Скачано и отправлено шлюзом", icon: "activity" }, { label: "Время работы входа", value: uptime(metrics?.uptime), detail: metrics?.stale ? "Нет свежих измерений" : `CPU ${metrics?.cpu == null ? "—" : metrics.cpu + "%"} · RAM ${metrics?.memory == null ? "—" : metrics.memory + "%"}`, icon: "server" }] as stat}<article
        class="card stat vstat"
      >
        <div class="stat-head">
          <small>{stat.label}</small><span class="stat-icon sm"
            ><Icon name={stat.icon} size={15} /></span
          >
        </div>
        <strong>{stat.value}</strong>
        <p>{stat.detail}</p>
      </article>{/each}
  </div>
  <div class="dashboard-grid wide-left">
    <section class="card">
      <div class="card-heading">
        <div>
          <span class="eyebrow">Шлюз</span>
          <h2>Трафик сети</h2>
        </div>
        <div class="seg">
          {#each [["24h", "24 ч"], ["7d", "7 д"], ["30d", "30 д"]] as [id, label]}<button
              type="button"
              class:on={period === id}
              onclick={() => (period = id)}>{label}</button
            >{/each}
        </div>
      </div>
      <div class="traffic-summary">
        <span
          ><i class="legend-dot"></i>Скачивание
          <b class="num">{rate(metrics?.stale ? null : metrics?.download)}</b> Мбит/с</span
        ><span
          ><i class="legend-dot mint"></i>Отправка
          <b class="num">{rate(metrics?.stale ? null : metrics?.upload)}</b> Мбит/с</span
        >
      </div>
      <Chart
        points={data.history?.points || []}
        label="История трафика шлюза"
      />
      <p class="chart-foot">
        Все соединения ядра, включая служебные. Сбор начинается после
        обновления. Квот и ограничений скорости нет.
      </p>
    </section>
    <div class="stack">
      <section class="card">
        <div class="card-heading">
          <div>
            <span class="eyebrow">Сейчас</span>
            <h2>Соединения</h2>
          </div>
          <Badge tone="muted"
            >{metrics?.stale ? "—" : (metrics?.connections ?? "—")}</Badge
          >
        </div>
        <div class="share-bar">
          {#each Object.entries(metrics?.protocols || {}) as [id, count]}{#if count}<i
                style:width={`${(count / Math.max(1, metrics?.connections || 1)) * 100}%`}
                style:background={protocolColors[id]}
              ></i>{/if}{/each}
        </div>
        <ul class="legend-list">
          {#each Object.entries(protocolNames) as [id, name]}<li>
              <i style:background={protocolColors[id]}></i>{name}<b class="num"
                >{metrics?.stale ? "—" : (metrics?.protocols?.[id] ?? "—")}</b
              >
            </li>{/each}
        </ul>
      </section>
      <section class="card padded">
        <span class="eyebrow">{geo.entryCode} · ресурсы</span>
        <h3>Нагрузка узла</h3>
        {#each [["Процессор", metrics?.cpu], ["Память", metrics?.memory]] as [name, value]}<div
            class="resource-row"
          >
            <span>{name}</span><b class="num"
              >{metrics?.stale || value == null ? "—" : value + "%"}</b
            >
            <div class="meter slim">
              <i style:width={`${metrics?.stale || value == null ? 0 : value}%`}
              ></i>
            </div>
          </div>{/each}
      </section>
    </div>
  </div>
  <div class="dashboard-grid">
    <Topology
      monitor={data.monitor}
      endpoint={boot.cfg.endpoint}
      reverse={geo.reverse}
    />
    <section class="card">
      <div class="card-heading">
        <div>
          <span class="eyebrow">Последние действия</span>
          <h2>События сети</h2>
        </div>
      </div>
      <Events events={data.events.slice(0, 4)} /><a
        class="text-button feed-link"
        href={`${base}#events`}>Весь журнал <Icon name="arrow" size={14} /></a
      >
    </section>
  </div>
{/if}
