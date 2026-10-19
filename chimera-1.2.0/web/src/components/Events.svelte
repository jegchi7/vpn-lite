<script lang="ts">
  import type { Event } from "../types";
  import { date, eventTitle } from "../lib";
  let { events, detailed = false }: { events: Event[]; detailed?: boolean } =
    $props();
</script>

<ol class="feed">
  {#each events as event, i}<li>
      <i
        class:warning={event.kind.includes("failed") ||
          ["foreign_down", "hop_down"].includes(event.kind)}
      ></i>
      <div>
        <b>{eventTitle(event)}</b><small>{event.actor_login || "Система"}</small
        >{#if detailed && event.detail}<p class="event-detail">
            {event.detail}
          </p>{/if}
      </div>
      <time datetime={new Date(event.created * 1000).toISOString()}
        >{date(event.created)}</time
      >
    </li>
  {:else}<li class="empty-inline">Здесь появятся события вашей сети.</li>{/each}
</ol>
