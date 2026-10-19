<script lang="ts">
  import type { Boot, State, Sample } from "../types";
  import Badge from "./Badge.svelte";
  import Icon from "./Icon.svelte";
  import Chart from "./Chart.svelte";
  import Devices from "./Devices.svelte";
  import Events from "./Events.svelte";
  import Topology from "./Topology.svelte";
  import { bytes, rate, pathName, deviceState, networkInfo } from "../lib";
  let {
    boot,
    state,
    section,
    live,
  }: { boot: Boot; state: State; section: string; live: Sample[] } = $props();
  const geo = $derived(networkInfo(boot.cfg));
  const count = $derived(state.devices.filter((d) => d.desired).length);
  const available = $derived(
    !state.monitor.stale &&
      ["primary", "backup"].includes(state.monitor.active || "") &&
      (state.monitor.active === "primary"
        ? state.monitor.primary
        : state.monitor.backup
      )?.state === "available",
  );
</script>

{#if section === "devices"}<Devices {boot} {state} />
{:else if section === "network"}<div class="page-heading">
    <div>
      <span class="eyebrow">Сеть</span>
      <h2>Как идёт трафик</h2>
      <p>{geo.summary}</p>
    </div>
  </div>
  <Topology
    monitor={state.monitor}
    endpoint={boot.cfg.endpoint}
    reverse={geo.reverse}
  />
  <section class="card padded">
    <h3>Если межсерверный путь недоступен</h3>
    <p class="muted">
      {geo.failure}
    </p>
  </section>
{:else if section === "activity"}<section class="card">
    <div class="card-heading">
      <div>
        <span class="eyebrow">История</span>
        <h2>Мои действия</h2>
      </div>
    </div>
    <Events events={state.events} />
  </section>
{:else}
  <section class="hero-grid">
    <article class="card hero-card">
      <div class="hero-top">
        <Badge tone={available ? "green" : "amber"}
          ><i class="pulse"></i>{available
            ? `${geo.branch} доступен`
            : state.monitor.stale
              ? "Ожидание статуса"
              : "Проверьте маршрут"}</Badge
        ><span class="subtle">Личный доступ</span>
      </div>
      <div class="hero-core">
        <div class="shield-orb" class:off={!available}>
          <i></i><i></i><span><Icon name="shield" size={30} /></span>
        </div>
        <div>
          <h2>Ваша сеть</h2>
          <p>
            {available
              ? `${geo.branch}: ${pathName(state.monitor.active)}.`
              : `${geo.branch}: доступность пока не подтверждена.`}
          </p>
        </div>
      </div>
      <div class="hero-metrics">
        <div>
          <small>Устройств</small><b class="num"
            >{count}<span> / {boot.user!.device_limit}</span></b
          >
        </div>
        <div>
          <small>Скачано · AWG</small><b class="num"
            >{bytes(state.usage.download_total)}</b
          >
        </div>
        <div>
          <small>Отправлено · AWG</small><b class="num"
            >{bytes(state.usage.upload_total)}</b
          >
        </div>
      </div>
      <a href="/#devices" class="hero-link"
        >Мои профили подключения <Icon name="arrow" size={16} /></a
      >
    </article>
    <article class="card throughput-card">
      <div class="card-heading">
        <div>
          <span class="eyebrow">Сейчас</span>
          <h2>Трафик AmneziaWG</h2>
        </div>
        <div class="rate">
          <span
            ><Icon name="down" size={14} /><b class="num"
              >{rate(state.usage.download)}</b
            ></span
          ><span class="dim"
            ><Icon name="up" size={14} /><b class="num"
              >{rate(state.usage.upload)}</b
            ></span
          >
        </div>
      </div>
      <Chart points={live} label="Трафик ваших устройств AmneziaWG" compact />
      <p class="chart-foot">
        {state.telemetry_stale
          ? "Измерения временно недоступны."
          : "Скорость в Мбит/с. Обновление каждые 10 секунд."} Статистика VLESS по
        отдельным устройствам не собирается.
      </p>
    </article>
  </section>
  <div class="stats-grid">
    <article class="card stat">
      <div>
        <small>Точка входа</small><strong>{geo.entryCountry}</strong>
        <p class="num">{boot.cfg.endpoint}</p>
      </div>
      <span class="stat-icon"><Icon name="server" /></span>
    </article>
    <article class="card stat">
      <div>
        <small>Способы подключения</small><strong>2 <em>протокола</em></strong>
        <p>AmneziaWG 3.1 · VLESS REALITY</p>
      </div>
      <span class="stat-icon"><Icon name="route" /></span>
    </article>
    <article class="card stat">
      <div>
        <small>Ваш доступ</small><strong>Без квот</strong>
        <p>Трафик и скорость не ограничены</p>
      </div>
      <span class="stat-icon"><Icon name="activity" /></span>
    </article>
  </div>
  <div class="dashboard-grid">
    <Topology
      monitor={state.monitor}
      endpoint={boot.cfg.endpoint}
      reverse={geo.reverse}
    />
    <section class="card devices-card">
      <div class="card-heading">
        <div>
          <span class="eyebrow">Подключения</span>
          <h2>Ваши устройства</h2>
        </div>
        <a href="/#devices" class="text-button"
          >Все <Icon name="arrow" size={14} /></a
        >
      </div>
      {#each state.devices.filter((d) => d.desired).slice(0, 4) as d}<a
          class="device-row"
          href={`/device/${d.id}`}
          ><span class="dev-icon on"><Icon name="smartphone" /></span>
          <div><b>{d.name}</b><small>{d.ip} · {deviceState(d)}</small></div>
          <Icon name="chevron" size={16} /></a
        >{:else}<p class="empty-inline">
          Начните с добавления устройства.
        </p>{/each}<a class="add-device" href="/#devices"
        ><span><Icon name="plus" /></span>
        <div>
          <b>Добавить устройство</b><small
            >Доступно слотов: {Math.max(
              0,
              boot.user!.device_limit - count,
            )}</small
          >
        </div></a
      >
    </section>
  </div>
{/if}
