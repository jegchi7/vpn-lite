<script lang="ts">
  import type { Monitor } from "../types";
  import Icon from "./Icon.svelte";
  import Badge from "./Badge.svelte";
  import { pathState } from "../lib";
  let {
    monitor,
    endpoint,
    reverse = false,
  }: { monitor: Monitor; endpoint: string; reverse?: boolean } = $props();
  let selected = $state("primary");
  const paths = [
    {
      id: "primary",
      name: "VLESS REALITY",
      port: "443 / TCP",
      color: "#b8f35d",
      note: "Основной защищённый путь между RU и зарубежным узлом.",
    },
    {
      id: "backup",
      name: "Hysteria2",
      port: "443 / UDP",
      color: "#5fd6b0",
      note: "Резервный защищённый путь с обфускацией Salamander.",
    },
  ];
  const active = $derived(paths.find((p) => p.id === selected)!);
  const pathStatus = (id: string) =>
    monitor.stale
      ? "unknown"
      : (id === "primary" ? monitor.primary : monitor.backup)?.state;
  const latency = (id: string) =>
    monitor.stale
      ? null
      : (id === "primary" ? monitor.primary : monitor.backup)?.latency_ms;
</script>

<section class="card map-card">
  <div class="card-heading">
    <div>
      <span class="eyebrow">Маршруты</span>
      <h2>Схема маршрутизации</h2>
    </div>
    <Badge tone={monitor.stale ? "muted" : "green"}
      >{reverse ? "Мир → RU" : "RU → мир"}</Badge
    >
  </div>
  <div class="stage-wrap">
    <div class="stage topology">
      <svg viewBox="0 0 840 360" aria-hidden="true">
        <defs
          ><pattern
            id="map-dots"
            x="0"
            y="0"
            width="22"
            height="22"
            patternUnits="userSpaceOnUse"
            ><circle
              cx="1"
              cy="1"
              r=".8"
              fill="#657e69"
              opacity=".25"
            /></pattern
          ></defs
        ><rect width="840" height="360" fill="url(#map-dots)" />
        <path
          d="M110 158H295"
          fill="none"
          stroke="#5b735f"
          stroke-width="1.5"
          stroke-dasharray="3 7"
        />
        <path
          d="M325 192V286"
          fill="none"
          stroke="#9cb388"
          stroke-width="1.5"
        />
        {#each paths as p, i}
          <path
            id={`route-${p.id}`}
            d={i === 0
              ? "M355 150C435 150 440 80 535 80S670 150 731 150"
              : "M355 170C435 170 440 238 535 238S670 170 731 170"}
            fill="none"
            stroke={p.color}
            stroke-width={monitor.active === p.id ? 2 : 1.2}
            stroke-opacity={pathStatus(p.id) === "available" ? 0.75 : 0.2}
            stroke-dasharray={monitor.active === p.id && !monitor.stale
              ? "0"
              : "4 7"}
          />
          {#if pathStatus(p.id) === "available" && monitor.active === p.id}<circle
              r="3"
              fill={p.color}
              ><animateMotion dur="4s" repeatCount="indefinite"
                ><mpath href={`#route-${p.id}`} /></animateMotion
              ></circle
            >{/if}
        {/each}
      </svg>
      <div class="tend client-node">
        <span><Icon name="laptop" /></span><b>Ваши устройства</b><small
          >AWG 3.1 / VLESS</small
        >
      </div>
      <div class="tend ru-node">
        <span><Icon name="server" /></span><b
          >{reverse ? "Зарубежный вход" : "RU · вход"}</b
        ><small>{endpoint}</small>
      </div>
      <div class="tend foreign-node">
        <span><Icon name="globe" /></span><b
          >{reverse ? "Россия · выход" : "Зарубежный выход"}</b
        ><small>Защищённый маршрут</small>
      </div>
      <div class="direct-node">
        <Icon name="globe" size={15} /><span
          >{reverse ? "Зарубежные сервисы" : "Сервисы РФ"}<small
            >{reverse ? "Напрямую с входа" : "Напрямую из RU"}</small
          ></span
        >
      </div>
      {#each paths as p, i}<button
          type="button"
          class="tnode"
          class:on={selected === p.id}
          class:route-live={pathStatus(p.id) === "available"}
          style:--c={p.color}
          style:left="64%"
          style:top={i === 0 ? "22.2%" : "66.1%"}
          onclick={() => (selected = p.id)}
          ><i></i>
          <div>
            <b>{p.name}</b><small
              >{pathStatus(p.id) === "available" && monitor.active === p.id
                ? "Используется"
                : pathState(pathStatus(p.id))}</small
            >
          </div></button
        >{/each}
    </div>
  </div>
  <div class="proto-tabs">
    {#each paths as p}<button
        type="button"
        class:on={selected === p.id}
        style:--c={p.color}
        onclick={() => (selected = p.id)}><i></i>{p.name}</button
      >{/each}
  </div>
  <div class="proto-detail">
    <p>{active.note}</p>
    <dl>
      <div>
        <dt>Транспорт</dt>
        <dd>{active.port}</dd>
      </div>
      <div>
        <dt>HTTPS-проверка</dt>
        <dd>{latency(selected) != null ? `${latency(selected)} мс` : "—"}</dd>
      </div>
      <div>
        <dt>Состояние</dt>
        <dd>{pathState(pathStatus(selected))}</dd>
      </div>
    </dl>
    <p class="hint">
      Протокол подключения выбирается в VPN-приложении. Межсерверный путь
      выбирает шлюз.
    </p>
  </div>
</section>
