<script lang="ts">
  import type { Boot } from "../types";
  import Badge from "./Badge.svelte";
  import Icon from "./Icon.svelte";
  import Form from "./Form.svelte";
  import { deviceState } from "../lib";
  let { boot }: { boot: Boot } = $props();
  let copied = $state(false);
  let copyError = $state("");
  const device = $derived(boot.device!);
  const protocol = $derived(boot.protocol || "amnezia");
  async function copy() {
    try {
      await navigator.clipboard.writeText(boot.profile || "");
      copied = true;
      setTimeout(() => (copied = false), 2200);
    } catch {
      copyError =
        "Не удалось скопировать. Откройте текст профиля и выделите его вручную.";
    }
  }
</script>

<a class="back" href="/#devices">← Мои устройства</a>
<div class="page-heading">
  <div>
    <span class="eyebrow">Личный профиль</span>
    <h2>{device.name}</h2>
    <p>Импортируйте профиль в приложение на своём устройстве.</p>
  </div>
  <Badge tone={device.desired && device.state === "applied" ? "green" : "amber"}
    >{deviceState(device)}</Badge
  >
</div>
{#if boot.profile}<div class="tabs">
    {#each [["amnezia", "AmneziaVPN"], ["awg", "AWG · .conf"], ["vless", "VLESS · Happ / v2rayNG"], ["singbox", "sing-box · JSON"]] as [id, label]}<a
        class:active={protocol === id}
        href={`?protocol=${id}`}>{label}</a
      >{/each}
  </div>
  <div class="profile-grid">
    <section class="card import-card">
      <span class="eyebrow"
        >{protocol === "singbox" ? "Файл конфигурации" : "Быстрый импорт"}</span
      >
      <h3>
        {protocol === "singbox" ? "Профиль для sing-box" : "Сканируйте QR-код"}
      </h3>
      {#if protocol !== "singbox"}<img
          class="qr"
          width="260"
          height="260"
          src={`/device/${device.id}/qr?protocol=${protocol}`}
          alt="QR-код вашего профиля"
        />{:else}<div class="file-orb">
          <Icon name="key" size={42} /><span>.json</span>
        </div>{/if}<a
        class="button primary-button full"
        href={`/device/${device.id}/download?protocol=${protocol}`}
        ><Icon name="down" />Скачать {["awg", "amnezia"].includes(protocol)
          ? protocol === "amnezia"
            ? "CHIMERA.vpn"
            : "CHIMERA.conf"
          : protocol === "vless"
            ? "VLESS-ссылку"
            : "JSON-профиль"}</a
      >
      <p class="hint">
        {["awg", "amnezia"].includes(protocol)
          ? protocol === "amnezia"
            ? "Имя в приложении: CHIMERA · " + device.name
            : "Совместимый .conf без имени сервера. Для имени выберите AmneziaVPN."
          : protocol === "vless"
            ? "Имя в приложении: CHIMERA · " + device.name
            : "Для ядра sing-box 1.14.3."}
      </p>
    </section>
    <section class="card padded">
      <span class="eyebrow">Подключение</span>
      <h3>
        {["awg", "amnezia"].includes(protocol)
          ? "AmneziaWG 3.1"
          : "VLESS REALITY"}
      </h3>
      <ol class="setup-steps">
        <li>
          <span>01</span>
          <div>
            <b>Откройте VPN-приложение</b>
            <p>
              {protocol === "vless"
                ? "Happ или v2rayNG на Android; совместимый клиент на других устройствах."
                : ["awg", "amnezia"].includes(protocol)
                  ? "Используйте AmneziaVPN с поддержкой AWG 3.1."
                  : "Откройте приложение с ядром sing-box указанной версии."}
            </p>
          </div>
        </li>
        <li>
          <span>02</span>
          <div>
            <b>Добавьте профиль</b>
            <p>
              Сканируйте QR-код, импортируйте файл или вставьте скопированную
              ссылку.
            </p>
          </div>
        </li>
        <li>
          <span>03</span>
          <div>
            <b>Подключитесь в приложении</b>
            <p>Разрешите VPN, включите полный VPN/TUN и DNS через туннель.</p>
          </div>
        </li>
      </ol>
      <button class="button secondary full" type="button" onclick={copy}
        ><Icon name={copied ? "check" : "copy"} />{copied
          ? "Скопировано"
          : protocol === "vless"
            ? "Скопировать VLESS-ссылку"
            : "Скопировать конфигурацию"}</button
      >{#if copyError}<p class="notice error">{copyError}</p>{/if}
      <details class="profile-details">
        <summary>Показать текст профиля</summary><textarea
          class="profile"
          rows="12"
          readonly
          spellcheck="false"
          aria-label="Конфигурация доступа">{boot.profile}</textarea
        >
      </details>
      <a href="/guide" class="text-button"
        >Подробная инструкция <Icon name="arrow" size={14} /></a
      >
    </section>
  </div>
{:else}<section class="card empty-state">
    <Icon name="lock" size={32} />
    <h3>
      {!device.desired && device.state === "applied"
        ? "Доступ отозван"
        : "Профиль пока недоступен"}
    </h3>
    <p>
      {device.state === "failed"
        ? "Изменение не применилось. Прежний доступ ещё может действовать; обратитесь к владельцу."
        : "Для нового подключения создайте устройство в личном кабинете."}
    </p>
  </section>{/if}
{#if device.desired}<section class="card padded">
    <h3>Название устройства</h3>
    <Form
      action={`/device/${device.id}/rename`}
      csrf={boot.user!.csrf}
      class="inline-form"
      ><label
        >Название<input
          name="name"
          value={device.name}
          required
          maxlength="48"
        /></label
      ><button class="button secondary">Сохранить</button></Form
    >
  </section>{/if}
<section class="card danger-zone">
  <div>
    <h3>{device.desired ? "Управление доступом" : "Удаление профиля"}</h3>
    <p>
      {device.desired
        ? "Замена ключей потребует заново импортировать профиль. VLESS-сессии кратко перезапустятся."
        : "Удаление очищает список устройств и сохранённые ключи уже отозванного профиля."}
    </p>
  </div>
  <div class="actions">
    {#if device.desired && device.state === "applied"}<Form
        action={`/device/${device.id}/rotate`}
        csrf={boot.user!.csrf}
        confirm="Заменить ключи устройства? Потребуется заново импортировать профиль."
        ><button class="button secondary">Заменить ключи</button></Form
      ><Form
        action={`/device/${device.id}/revoke`}
        csrf={boot.user!.csrf}
        confirm={`Отозвать доступ «${device.name}» на сервере?`}
        ><button class="button danger">Отозвать доступ</button></Form
      >{:else if !device.desired && device.state === "applied"}<Form
        action={`/device/${device.id}/delete`}
        csrf={boot.user!.csrf}
        confirm="Удалить отозванное устройство и его сохранённый профиль?"
        ><button class="button danger">Удалить профиль</button></Form
      >{/if}
  </div>
</section>
