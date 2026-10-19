<script lang="ts">
  import type { Boot } from "../types";
  import Form from "./Form.svelte";
  import Badge from "./Badge.svelte";
  import Icon from "./Icon.svelte";
  import { date, usePasskey } from "../lib";
  let { boot }: { boot: Boot } = $props();
  let error = $state("");
  let busy = $state(false);
  let label = $state("");
  let password = $state("");
  async function register(event: SubmitEvent) {
    event.preventDefault();
    busy = true;
    error = "";
    try {
      await usePasskey(boot.user!.csrf, true, password, label);
    } catch (e) {
      error = e instanceof Error ? e.message : "Ключ входа не добавлен";
    } finally {
      password = "";
      busy = false;
    }
  }
</script>

<div class="page-heading">
  <div>
    <span class="eyebrow">Учётная запись</span>
    <h2>{boot.user!.login}</h2>
    <p>Вход, безопасность и связь с Telegram.</p>
  </div>
  <Badge tone="muted">{boot.user!.admin ? "Владелец" : "Пользователь"}</Badge>
</div>
<div class="two-columns">
  <section class="card padded">
    <span class="section-icon"><Icon name="smartphone" /></span>
    <h3>Telegram-бот</h3>
    <p class="muted">Те же устройства и профили, быстрый доступ с телефона.</p>
    {#if boot.user!.telegram_id}<Badge>Telegram привязан</Badge>
      <p class="hint num">ID {boot.user!.telegram_id}</p>
      <Form
        action="/account/unlink"
        csrf={boot.user!.csrf}
        confirm="Отвязать Telegram от этой учётной записи?"
        ><button class="button secondary">Отвязать</button></Form
      >{:else if boot.cfg.bot_username}<Form
        action="/account/telegram"
        csrf={boot.user!.csrf}
        ><button class="button primary-button"
          >Привязать @{boot.cfg.bot_username} <Icon name="arrow" /></button
        ></Form
      >{:else}<div class="note">
        Бот пока не настроен владельцем. Профили доступны в личном кабинете.
      </div>{/if}
  </section>
  <section class="card padded">
    <span class="section-icon"><Icon name="lock" /></span>
    <h3>Сменить пароль</h3>
    <Form action="/account/password" csrf={boot.user!.csrf}
      ><label
        >Текущий пароль<input
          name="old"
          type="password"
          autocomplete="current-password"
          required
          maxlength="256"
        /></label
      ><label
        >Новый пароль<input
          name="new"
          type="password"
          autocomplete="new-password"
          required
          minlength={boot.password_min || 8}
          maxlength="256"
        /></label
      >
      <p class="hint">
        Минимум {boot.password_min || 8} символов. После смены пароля потребуется
        войти заново.
      </p>
      <button class="button secondary">Сохранить пароль</button></Form
    >
  </section>
</div>
<section class="card padded">
  <span class="eyebrow">Вход без пароля</span>
  <h3>Ключи доступа</h3>
  <p class="muted">
    Вход с отпечатком, лицом, PIN-кодом устройства или аппаратным ключом.
  </p>
  {#each boot.passkeys || [] as key}<div class="key-row">
      <span class="dev-icon"><Icon name="key" /></span>
      <div>
        <b>{key.label}</b><small
          >Добавлен {date(key.created)} · Вход {date(key.last_used)}</small
        >
      </div>
      <Form
        action="/account/passkey-delete"
        csrf={boot.user!.csrf}
        confirm="Удалить этот ключ входа?"
        ><input type="hidden" name="credential_id" value={key.id} /><button
          class="text-button danger-text">Удалить</button
        ></Form
      >
    </div>{:else}<div class="note">
      Ключей входа пока нет. Пароль остаётся доступным способом входа.
    </div>{/each}{#if error}<p class="notice error" role="alert">
      {error}
    </p>{/if}
  <form onsubmit={register} class="inline-form">
    <label
      >Название ключа<input
        bind:value={label}
        placeholder="Например, мой телефон"
        maxlength="64"
        required
      /></label
    ><label
      >Подтвердите текущий пароль<input
        type="password"
        bind:value={password}
        autocomplete="current-password"
        required
      /></label
    ><button class="button primary-button" disabled={busy}
      ><Icon name="plus" />{busy
        ? "Подтвердите на устройстве…"
        : "Добавить ключ входа"}</button
    >
  </form>
</section>
