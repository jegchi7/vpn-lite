<script lang="ts">
  import type { Sample } from "../types";
  import { time } from "../lib";
  let {
    points = [],
    label = "Трафик",
    compact = false,
  }: { points: Sample[]; label?: string; compact?: boolean } = $props();
  const id = $props.id();
  let hover = $state<number | null>(null);
  const values = $derived(
    points.map((p) => ({
      ...p,
      down: p.download == null ? null : (p.download * 8) / 1e6,
      up: p.upload == null ? null : (p.upload * 8) / 1e6,
    })),
  );
  const max = $derived(
    Math.max(0.1, ...values.flatMap((p) => [p.down || 0, p.up || 0])) * 1.15,
  );
  const usable = $derived(values.some((p) => p.down != null || p.up != null));
  const path = (key: "down" | "up") => {
    let open = false;
    return values
      .map((p, i) => {
        const value = p[key];
        if (value == null) {
          open = false;
          return "";
        }
        const command = open ? "L" : "M";
        open = true;
        return `${command}${values.length === 1 ? 300 : (i / (values.length - 1)) * 600},${185 - (value / max) * 165}`;
      })
      .join(" ");
  };
  function move(e: MouseEvent) {
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
    hover = Math.min(
      points.length - 1,
      Math.max(
        0,
        Math.round(((e.clientX - r.left) / r.width) * (points.length - 1)),
      ),
    );
  }
</script>

<div class="traffic-chart" class:compact role="img" aria-label={label}>
  {#if usable}
    <div class="chart-y">
      <span>{max.toFixed(1)}</span><span>{(max / 2).toFixed(1)}</span><span
        >0 <small>Мбит/с</small></span
      >
    </div>
    <div
      class="chart"
      role="presentation"
      onmousemove={move}
      onmouseleave={() => (hover = null)}
    >
      <svg viewBox="0 0 600 200" preserveAspectRatio="none" aria-hidden="true">
        <defs
          ><linearGradient {id} x1="0" x2="0" y1="0" y2="1"
            ><stop offset="0" stop-color="#b8f35d" stop-opacity=".22" /><stop
              offset="1"
              stop-color="#b8f35d"
              stop-opacity="0"
            /></linearGradient
          ></defs
        >
        {#each [20, 75, 130, 185] as y}<line
            x1="0"
            x2="600"
            y1={y}
            y2={y}
            stroke="currentColor"
            stroke-dasharray="2 6"
            class="chart-grid"
          />{/each}
        {#if values.length > 1 && values.every((p) => p.down != null)}<path
            d={`${path("down")} L600 200 L0 200Z`}
            fill={`url(#${id})`}
            opacity=".7"
          />{/if}
        <path
          d={path("down")}
          fill="none"
          stroke="#b8f35d"
          stroke-width="2"
          vector-effect="non-scaling-stroke"
        /><path
          d={path("up")}
          fill="none"
          stroke="#5fd6b0"
          stroke-width="1.5"
          vector-effect="non-scaling-stroke"
        />
        {#if values.length === 1}<circle
            cx="300"
            cy={185 - ((values[0].down || 0) / max) * 165}
            r="3"
            fill="#b8f35d"
          />{/if}
      </svg>
      {#if hover != null && values[hover]}<span
          class="chart-line"
          style:left={`${points.length === 1 ? 50 : (hover / (points.length - 1)) * 100}%`}
        ></span><span class="chart-tip"
          ><b
            >↓ {values[hover].down?.toFixed(2) ?? "—"} · ↑ {values[
              hover
            ].up?.toFixed(2) ?? "—"} Мбит/с</b
          >{time(values[hover].created)}</span
        >{/if}
    </div>
    <div class="chart-x">
      <span>{time(points[0].created)}</span><span
        >{time(points[Math.floor(points.length / 2)].created)}</span
      ><span>{time(points[points.length - 1].created)}</span>
    </div>
  {:else}<div class="chart-empty">
      <span class="empty-chart-mark">⌁</span><b>Пока нет измерений</b>
      <p>График появится по мере сбора данных.</p>
    </div>{/if}
</div>
