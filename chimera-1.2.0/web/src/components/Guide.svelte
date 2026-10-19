<script lang="ts">
  import type { Boot } from "../types";
  import { networkInfo } from "../lib";
  import Icon from "./Icon.svelte";
  let { boot }: { boot: Boot } = $props();
  const geo = $derived(networkInfo(boot.cfg));
  let platform = $state("Android");
</script>

<div class="page-heading">
  <div>
    <span class="eyebrow">Подключение</span>
    <h2>Начните с профиля</h2>
    <p>Выберите устройство и удобный протокол.</p>
  </div>
  <label class="platform"
    >Ваша система<select bind:value={platform}
      >{#each ["Android", "iOS", "Windows", "macOS", "Linux"] as system}<option
          >{system}</option
        >{/each}</select
    ></label
  >
</div>
<div class="two-columns">
  <section class="card padded prose">
    <span class="step">01 / AWG</span>
    <h3>AmneziaWG 3.1</h3>
    <ol>
      <li>Установите AmneziaVPN с поддержкой AWG 3.1 для {platform}.</li>
      <li>
        Откройте своё устройство в CHIMERA и выберите AmneziaVPN и скопируйте
        ключ vpn://.
      </li>
      <li>
        В AmneziaVPN выберите добавление подключения и импорт ключа из буфера,
        файла или QR-кода. Имя сервера — CHIMERA.
      </li>
      <li>Разрешите VPN и подключитесь в приложении.</li>
    </ol>
    <div class="note">
      Требуется поддержка AWG 3.1. Обычный клиент WireGuard не подходит.
    </div>
    <a
      class="text-button"
      href="https://github.com/amnezia-vpn/amnezia-client/releases"
      target="_blank"
      rel="noreferrer"
      >Официальные версии AmneziaVPN <Icon name="arrow" size={14} /></a
    >
  </section>
  <section class="card padded prose">
    <span class="step mint-text">02 / VLESS</span>
    <h3>VLESS REALITY</h3>
    <ol>
      <li>
        {platform === "Android"
          ? "Откройте Happ или v2rayNG."
          : platform === "Windows"
            ? "Откройте Happ или v2rayN."
            : "Откройте совместимый клиент VLESS REALITY + Vision."}
      </li>
      <li>
        Откройте устройство в CHIMERA, выберите VLESS и импортируйте ссылку или
        QR-код.
      </li>
      <li>
        Включите полный режим VPN/TUN, DNS через VPN и захват или блокировку
        IPv6.
      </li>
      <li>Имя профиля в приложении — CHIMERA. Подключитесь в клиенте.</li>
    </ol>
    <div class="note">
      Сохраните параметры полученной ссылки. DNS шлюза: <span class="num"
        >{boot.cfg.awg.gateway}</span
      >.
    </div>
    <a
      class="text-button"
      href="https://github.com/Happ-proxy/happ-android/releases"
      target="_blank"
      rel="noreferrer">Happ для Android <Icon name="arrow" size={14} /></a
    >
  </section>
</div>
<section class="card padded prose">
  <h3>Если подключение не работает</h3>
  <details>
    <summary>Приложение подключилось, но сайты не открываются</summary>
    <p>
      Убедитесь, что выбран полный VPN/TUN и DNS идёт через туннель. Проверьте
      выбранный профиль и переподключитесь. Можно попробовать другой вход: AWG
      или VLESS.
    </p>
  </details>
  <details>
    <summary>После замены ключей</summary>
    <p>
      Скачайте профиль заново и импортируйте его в клиент. Старые ключи после
      успешного применения больше не работают.
    </p>
  </details>
  <details>
    <summary>Панель не открывается при включённом VPN</summary>
    <p>
      Панель и служебные адреса из пользовательского туннеля закрыты. Временно
      отключите VPN для доступа к личному кабинету.
    </p>
  </details>
  <details>
    <summary>Как работает выбор маршрута</summary>
    <p>
      {geo.summary}
      {geo.failure} Ограничений скорости и трафика в CHIMERA нет.
    </p>
  </details>
</section>
