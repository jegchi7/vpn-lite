<script lang="ts">
  import Icon from "./Icon.svelte";
  let { compact = false } = $props();
</script>

<a class="brand" href="/" aria-label="CHIMERA — главная"
  ><span class="brand-mark"><Icon name="chimera" size={24} /></span
  >{#if !compact}<span><b>CHIMERA</b><small>Частная сеть</small></span>{/if}</a
>
