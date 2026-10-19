<script lang="ts">
  import type { Boot } from "../types";
  import Logo from "./Logo.svelte";
  import Icon from "./Icon.svelte";
  import Form from "./Form.svelte";
  import { usePasskey } from "../lib";
  let { boot }: { boot: Boot } = $props();
  let visible = $state(false);
  let remember = $state(false);
  let busy = $state(false);
  let error = $state("");
  let password = $state("");
  let repeat = $state("");
  const settingPassword = $derived(["join", "reset"].includes(boot.view));
  const title = $derived(
    boot.view === "join"
      ? "Настройка доступа"
      : boot.view === "reset"
        ? "Новый пароль"
        : boot.view === "help-login"
          ? "Восстановление доступа"
          : boot.view === "one-shot"
            ? "Ваш профиль готов"
            : "Вход в CHIMERA",
  );
  function contour(radius: number, seed: number) {
    return (
      Array.from({ length: 96 }, (_, i) => {
        const t = (i / 96) * Math.PI * 2;
        const k =
          1 +
          0.09 * Math.sin(3 * t + seed) +
          0.05 * Math.sin(5 * t + seed * 1.7) +
          0.03 * Math.sin(2 * t - seed);
        return `${i ? "L" : "M"}${(500 + radius * k * Math.cos(t)).toFixed(1)} ${(500 + radius * k * 0.84 * Math.sin(t)).toFixed(1)}`;
      }).join(" ") + "Z"
    );
  }
  async function loginKey() {
    busy = true;
    error = "";
    try {
      await usePasskey(boot.csrf || "", false, "", "", remember);
    } catch (e) {
      error = e instanceof Error ? e.message : "Не удалось войти";
    } finally {
      busy = false;
    }
  }
  function validate(event: SubmitEvent) {
    if (password !== repeat) {
      event.preventDefault();
      error = "Пароли не совпадают";
    }
  }
</script>

<main class="login-page">
  <div class="login-art">
    <div class="contours" aria-hidden="true">
      {#each [0.2, 1.4, 2.6, 3.8] as seed, layer}<div
          class="contour-layer"
          style:--dur={`${60 - layer * 9}s`}
          style:opacity={0.16 + layer * 0.12}
        >
          <svg viewBox="0 0 1000 1000"
            >{#each Array.from({ length: 8 - layer }) as _, i}<path
                d={contour(70 + i * (52 + layer * 9), seed + i * 0.32)}
                fill="none"
                stroke="#b8f35d"
                stroke-width={layer === 3 ? 1.4 : 1}
              />{/each}</svg
          >
        </div>{/each}
    </div>
    <Logo />
    <div class="art-foot">
      <span class="eyebrow">Частная VPN-сеть</span>
      <ul>
        <li><i></i>AmneziaWG 3.1</li>
        <li><i class="mint"></i>VLESS REALITY</li>
      </ul>
    </div>
  </div>
  <div class="login-panel">
    <div class="login-box">
      <div class="mobile-logo"><Logo /></div>
      <span class="eyebrow">CHIMERA / ЛИЧНЫЙ КАБИНЕТ</span>
      <h1>{title}</h1>
      {#if boot.view === "help-login"}<p class="lede">
          Попросите владельца сети создать ссылку восстановления для вашего
          логина.
        </p>
        <div class="note">
          Ссылка позволит задать новый пароль. Ваши VPN-профили сохранятся.
        </div>
        <a href="/login" class="button primary-button full"
          >Вернуться ко входу <Icon name="arrow" /></a
        >
      {:else if boot.view === "one-shot"}<p class="lede">
          Одноразовое скачивание личного профиля.
        </p>
        <div class="note">
          Ссылка действует 5 минут и расходуется при скачивании. Импортируйте
          файл в VPN-приложение.
        </div>
        <Form
          ><button class="sign-in">Скачать профиль <Icon name="down" /></button
          ></Form
        >
      {:else if settingPassword}<p class="lede">
          Доступ для <b>{boot.login}</b>. Задайте пароль от {boot.password_min ||
            8} символов.
        </p>
        {#if error}<div class="notice error" role="alert">{error}</div>{/if}
        <form method="post" onsubmit={validate}>
          <input type="hidden" name="csrf" value={boot.csrf} /><label
            >Пароль
            <div class="password-field">
              <input
                name="password"
                type={visible ? "text" : "password"}
                bind:value={password}
                minlength={boot.password_min || 8}
                maxlength="256"
                required
                autocomplete="new-password"
              /><button type="button" onclick={() => (visible = !visible)}
                >{visible ? "Скрыть" : "Показать"}</button
              >
            </div></label
          ><label
            >Повторите пароль<input
              type="password"
              bind:value={repeat}
              required
              autocomplete="new-password"
            /></label
          ><button class="sign-in"
            >{boot.view === "reset" ? "Сохранить пароль" : "Создать доступ"}
            <Icon name="arrow" /></button
          >
        </form>
        <p class="hint">Ссылка используется один раз.</p>
      {:else}<p class="lede">Войдите в свою частную сеть.</p>
        {#if boot.error || error}<div class="notice error" role="alert">
            {error || "Логин или пароль не подошли. Попробуйте ещё раз."}
          </div>{/if}
        <Form action="/login" csrf={boot.csrf}
          ><label
            >Логин<input
              name="login"
              required
              maxlength="32"
              autocomplete="username"
              autocapitalize="off"
              spellcheck="false"
              placeholder="Ваш логин"
            /></label
          ><label
            >Пароль
            <div class="password-field">
              <input
                name="password"
                required
                maxlength="256"
                type={visible ? "text" : "password"}
                autocomplete="current-password"
                placeholder="Ваш пароль"
              /><button type="button" onclick={() => (visible = !visible)}
                >{visible ? "Скрыть" : "Показать"}</button
              >
            </div></label
          >
          <div class="form-meta">
            <label class="checkbox"
              ><input
                name="remember"
                type="checkbox"
                bind:checked={remember}
              />Запомнить на 7 дней</label
            ><a href="/help-login">Забыли пароль?</a>
          </div>
          <button class="sign-in">Войти <Icon name="arrow" /></button></Form
        >
        <div class="divider"><span>или</span></div>
        <button class="passkey" type="button" disabled={busy} onclick={loginKey}
          ><Icon name="key" />{busy
            ? "Подтвердите вход…"
            : "Войти с ключом доступа"}</button
        >
        <p class="login-foot">Только по приглашению владельца сети.</p>
      {/if}
    </div>
    <span class="login-copyright">CHIMERA <span>Личный доступ к VPN</span></span
    >
  </div>
</main>
