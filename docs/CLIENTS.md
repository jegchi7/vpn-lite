# Клиенты и формат профилей CHIMERA

Владелец подтвердил работу AWG и VLESS в Happ/v2rayNG на Android 19 октября
2026 года. Новый именованный Amnezia-импорт требует ручного импорта после обновления.

| Формат | Клиент | Имя при импорте |
|---|---|---|
| Amnezia `vpn://`, файл `.vpn` / QR | AmneziaVPN с поддержкой AWG 3.1 | `CHIMERA · название устройства` из `description` |
| AWG `.conf` / QR | AmneziaVPN с поддержкой AWG 3.1 | Имя назначает приложение; формат `.conf` не стандартизует название |
| VLESS URI / QR | Happ, v2rayNG, v2rayN с REALITY + Vision и `hellosafari_16_0` | `CHIMERA · название устройства` из фрагмента URI |
| Полный sing-box JSON | sing-box 1.14.3 и приложения с полным импортом конфигурации | Имя файла `CHIMERA-sing-box.json`; отображение зависит от приложения |
| iOS | Клиент AWG 3.1 либо REALITY + Vision с полным VPN | Наличие подходящей версии в регионе App Store и импорт не подтверждены |

AmneziaVPN и отдельный AmneziaWG — разные приложения. Версия приложения
и версия протокола также различаются. Обычный WireGuard и старые AWG 1/2
не поддерживают этот профиль 3.1.

## AmneziaVPN

В панели откройте устройство → AmneziaVPN. Скопируйте ключ `vpn://` и добавьте
его в приложение из буфера; также доступны файл `.vpn` и QR. В нативном
контейнере сохраняется имя CHIMERA и все параметры обфускации AWG 3.1.
Старый `.conf` остаётся отдельной вкладкой для совместимости.

Формат нативного импорта сопоставлен с официальным исходным кодом:

- [importController.cpp](https://github.com/amnezia-vpn/amnezia-client/blob/dev/client/core/controllers/selfhosted/importController.cpp)
- [configKeys.h](https://github.com/amnezia-vpn/amnezia-client/blob/dev/client/core/utils/constants/configKeys.h)
- [exportController.cpp](https://github.com/amnezia-vpn/amnezia-client/blob/dev/client/core/controllers/selfhosted/exportController.cpp)

Профиль содержит `HeaderProtectionKey`, S1–S4, H1–H4, RandomTrailers и
ContentPaddingAddition из текущего setup. Клиентские маршруты — `0.0.0.0/0, ::/0`.
IPv6 адрес включён для захвата, интернет-выход IPv6 на шлюзе закрыт.
Если приложение игнорирует IPv6 или kill switch, сервер не может остановить
трафик, отправленный устройством мимо VPN.

## VLESS

Ссылка содержит только endpoint выбранного входа (RU или зарубежного),
пользовательский UUID и публичные параметры REALITY входа. В выдаче закреплён
Safari ClientHello `fp=hellosafari_16_0`, с которым
владелец подтвердил работу Happ и v2rayNG. Не меняйте SNI/ключ/short ID вручную.
Межсерверный профиль этим не меняется.

Включите полный режим VPN/TUN, DNS через VPN, захват или блокировку IPv6
и kill switch в клиенте. DNS шлюза по умолчанию — `10.77.0.1`.
VLESS URI не стандартизует настройки DNS и VPN каждого приложения.

Полный JSON рассчитан на sing-box 1.14.3 и использует поддерживаемый ядром
fingerprint `safari`. Его импортируют целиком, а не в поле VLESS URL или AWG.
Клиентский TUN имеет auto_route/strict_route, DNS направлен в шлюз через proxy,
IPv6 отклоняется. На входном хосте маршрутизация ограничена отдельной policy table.

## Общие действия

У одного устройства есть оба набора credentials. Выбирайте один протокол для
текущего подключения. Автоматическое переключение AWG ↔ VLESS в приложении
не заявляется. Название существующего импортированного подключения автоматически
не обновится: переименуйте его в приложении или импортируйте новый профиль.
Ключи при простом повторном скачивании не меняются.

После замены ключей импортируйте профиль заново. После успешного отзыва
устройство можно удалить из кабинета или бота; действующий профиль сначала
отзывается. Для HTTPS-скачивания может понадобиться отключить VPN: доступ
из пользовательского туннеля к служебным интерфейсам шлюза закрыт.

Официальные страницы:

- https://github.com/amnezia-vpn/amnezia-client/releases
- https://docs.amnezia.org/documentation/amnezia-wg/
- https://github.com/Happ-proxy/happ-android/releases
- https://github.com/2dust/v2rayNG/releases
- https://github.com/2dust/v2rayN/releases
- https://sing-box.sagernet.org/clients/
