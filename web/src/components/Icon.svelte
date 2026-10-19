<script lang="ts">
  let { name = "shield", size = 18 }: { name?: string; size?: number } =
    $props();
</script>

<svg
  aria-hidden="true"
  class="icon"
  fill="none"
  height={size}
  width={size}
  viewBox="0 0 24 24"
>
  {#if name === "activity"}<path d="M3 12h4l2.4-7 4.2 14 2.2-7H21" />
  {:else if name === "arrow"}<path d="M5 12h14m-6-6 6 6-6 6" />
  {:else if name === "chevron"}<path d="m9 18 6-6-6-6" />
  {:else if name === "down"}<path d="M12 5v14m-6-6 6 6 6-6" />
  {:else if name === "up"}<path d="M12 19V5m-6 6 6-6 6 6" />
  {:else if name === "grid"}<rect
      x="3"
      y="3"
      width="7"
      height="7"
      rx="1.5"
    /><rect x="14" y="3" width="7" height="7" rx="1.5" /><rect
      x="3"
      y="14"
      width="7"
      height="7"
      rx="1.5"
    /><rect x="14" y="14" width="7" height="7" rx="1.5" />
  {:else if name === "globe"}<circle cx="12" cy="12" r="9" /><path
      d="M3 12h18M12 3c3 3.5 3 14 0 18M12 3c-3 3.5-3 14 0 18"
    />
  {:else if name === "key"}<circle cx="8" cy="15" r="4" /><path
      d="m11 12 8-8m-3 3 3 3"
    />
  {:else if name === "laptop"}<rect
      x="4"
      y="4"
      width="16"
      height="12"
      rx="2"
    /><path d="M2 20h20" />
  {:else if name === "lock"}<rect
      x="4"
      y="10"
      width="16"
      height="11"
      rx="2"
    /><path d="M8 10V7a4 4 0 0 1 8 0v3" />
  {:else if name === "menu"}<path d="M4 7h16M4 12h16M4 17h16" />
  {:else if name === "close"}<path d="m6 6 12 12M6 18 18 6" />
  {:else if name === "plus"}<path d="M12 5v14M5 12h14" />
  {:else if name === "server"}<rect
      x="3"
      y="4"
      width="18"
      height="6"
      rx="2"
    /><rect x="3" y="14" width="18" height="6" rx="2" /><path
      d="M7 7h.01M7 17h.01"
    />
  {:else if name === "smartphone"}<rect
      x="6"
      y="2"
      width="12"
      height="20"
      rx="3"
    /><path d="M10 18h4" />
  {:else if name === "users"}<path
      d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M22 21v-2a4 4 0 0 0-3-3.9M16 3.1a4 4 0 0 1 0 7.8"
    /><circle cx="9" cy="7" r="4" />
  {:else if name === "copy"}<rect
      x="9"
      y="9"
      width="11"
      height="11"
      rx="2"
    /><path d="M15 9V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h3" />
  {:else if name === "check"}<path d="m5 12 4 4L19 6" />
  {:else if name === "search"}<circle cx="10.5" cy="10.5" r="6.5" /><path
      d="m16 16 5 5"
    />
  {:else if name === "logout"}<path d="M10 4H5v16h5M9 12h12m-4-4 4 4-4 4" />
  {:else if name === "route"}<circle cx="5" cy="5" r="2" /><circle
      cx="19"
      cy="19"
      r="2"
    /><path d="M7 5h9a4 4 0 0 1 0 8H8a4 4 0 0 0 0 8h9" />
  {:else if name === "book"}<path
      d="M12 5v16M3 3c4 0 6 1 9 3 3-2 5-3 9-3v16c-4 0-6 1-9 3-3-2-5-3-9-3V3Z"
    />
  {:else if name === "chimera"}<path d="m12 3 8 5v8l-8 5-8-5V8l8-5Z" /><path
      d="m8 9 4 3 4-3m-4 3v5"
    />
  {:else}<path
      d="M12 3 4.5 6v5.5c0 4.6 3.2 7.8 7.5 9.5 4.3-1.7 7.5-4.9 7.5-9.5V6L12 3Z"
    />{/if}
</svg>
