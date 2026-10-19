<script lang="ts">
  import type { Boot, State } from "../types";
  import Badge from "./Badge.svelte";
  import Icon from "./Icon.svelte";
  import Form from "./Form.svelte";
  import { deviceState, date } from "../lib";
  let { boot, state: data }: { boot: Boot; state: State } = $props();
  let search = $state("");
  let filter = $state("all");
  const count = $derived(data.devices.filter((d) => d.desired).length);
  const revoked = $derived(
    data.devices.filter((d) => !d.desired && d.state === "applied").length,
  );
  const filtered = $derived(
    data.devices.filter(
      (d) =>
        d.name.toLowerCase().includes(search.toLowerCase()) &&
        (filter === "all" || (filter === "active" ? d.desired : !d.desired)),
    ),
  );
</script>

<div class="page-heading">
  <div>
    <span class="eyebrow">Подключения</span>
    <h2>
      Мои устройства <span class="count"
        >{count} / {boot.user!.device_limit}</span
      >
    </h2>
    <p>У каждого устройства свой профиль и ключи доступа.</p>
  </div>
  <a href="#new-device" class="button primary-button"
    ><Icon name="plus" />Добавить устройство</a
  >
</div>
<div class="toolbar">
  <div class="seg">
    {#each [["all", "Все"], ["active", "Активные"], ["revoked", "Отозванные"]] as [id, label]}<button
        type="button"
        class:on={filter === id}
        onclick={() => (filter = id)}>{label}</button
      >{/each}
  </div>
  <label class="search-field"
    ><Icon name="search" /><input
      aria-label="Поиск устройства"
      placeholder="Найти устройство"
      bind:value={search}
    /></label
  >{#if revoked}<Form
      action="/devices/clear-revoked"
      csrf={boot.user!.csrf}
      confirm={`Удалить ${revoked} отозванных устройств и их сохранённые профили? Активные устройства сохранятся.`}
      ><button class="text-button danger-text"
        >Очистить отозванные ({revoked})</button
      ></Form
    >{/if}
</div>
<div class="device-grid">
  {#each filtered as device}<article
      class="card device-tile"
      class:inactive={!device.desired}
    >
      <div class="tile-top">
        <span class="dev-icon" class:on={!!device.desired}
          ><Icon
            name={/phone|телефон|android|iphone/i.test(device.name)
              ? "smartphone"
              : "laptop"}
            size={22}
          /></span
        ><Badge
          tone={device.state !== "applied"
            ? "amber"
            : device.desired
              ? "green"
              : "muted"}>{deviceState(device)}</Badge
        >
      </div>
      <h3>{device.name}</h3>
      <p class="muted">AmneziaWG 3.1 · VLESS REALITY</p>
      <dl class="small-dl">
        <div>
          <dt>Адрес AWG</dt>
          <dd class="num">{device.ip}</dd>
        </div>
        <div>
          <dt>Добавлено</dt>
          <dd>{date(device.created)}</dd>
        </div>
      </dl>
      <div class="tile-actions">
        <a
          class="button"
          class:secondary={!device.desired}
          href={`/device/${device.id}`}
          >{device.desired ? "Открыть профиль" : "Подробнее"}<Icon
            name="arrow"
            size={16}
          /></a
        >{#if !device.desired && device.state === "applied"}<Form
            action={`/device/${device.id}/delete`}
            csrf={boot.user!.csrf}
            confirm={`Удалить отозванное устройство «${device.name}» и его профиль?`}
            ><button class="text-button danger-text">Удалить</button></Form
          >{/if}
      </div>
    </article>{:else}<div class="card empty-state">
      <Icon name="smartphone" size={32} />
      <h3>{search ? "Ничего не найдено" : "Здесь будут ваши устройства"}</h3>
      <p>
        {search
          ? "Попробуйте другое название."
          : "Создайте первый профиль для телефона или компьютера."}
      </p>
    </div>{/each}
  <article class="card add-card" id="new-device">
    <span class="add-icon"><Icon name="plus" size={26} /></span><span
      class="eyebrow">Новое подключение</span
    >
    <h3>Добавить устройство</h3>
    <Form action="/devices" csrf={boot.user!.csrf}
      ><input type="hidden" name="intent" value={boot.intent} /><label
        >Название<input
          name="name"
          placeholder="Например, мой телефон"
          maxlength="48"
          required
          disabled={count >= boot.user!.device_limit}
        /></label
      ><button
        class="button primary-button full"
        disabled={count >= boot.user!.device_limit}
        >Создать профиль <Icon name="arrow" size={16} /></button
      ></Form
    >
    <p class="hint">
      {count >= boot.user!.device_limit
        ? "Достигнут лимит устройств. Отзовите ненужное или обратитесь к владельцу."
        : "Один профиль — два способа подключения."}
    </p>
  </article>
</div>
