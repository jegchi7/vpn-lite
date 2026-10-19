<script lang="ts">
  import type { Snippet } from "svelte";
  let {
    action,
    csrf,
    children,
    confirm: confirmation = "",
    class: className = "",
  }: {
    action?: string;
    csrf?: string;
    children: Snippet;
    confirm?: string;
    class?: string;
  } = $props();
  let busy = $state(false);
  function submit(event: SubmitEvent) {
    if (busy || (confirmation && !window.confirm(confirmation))) {
      event.preventDefault();
      return;
    }
    busy = true;
  }
</script>

<form
  method="post"
  {action}
  class={className}
  onsubmit={submit}
  aria-busy={busy}
>
  {#if csrf}<input type="hidden" name="csrf" value={csrf} />{/if}
  {@render children()}
</form>
