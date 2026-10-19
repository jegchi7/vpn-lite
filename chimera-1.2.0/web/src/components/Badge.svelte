<script lang="ts">
  import type { Snippet } from "svelte";
  let { tone = "green", children }: { tone?: string; children: Snippet } =
    $props();
</script>

<span class="badge {tone}">{@render children()}</span>
