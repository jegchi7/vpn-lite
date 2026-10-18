# Закреплённые компоненты и источники

Дата фиксации: 18 октября 2026. Точные URL архивов и SHA256 находятся в
release.json. Исходный дистрибутив продукта не содержит бинарники upstream;
scripts/assets.py получает их с официальных источников, проверяет хеши и
собирает AWG. Не используется автоматическая установка latest.

| Компонент | Закрепление | Источник / лицензия |
|---|---|---|
| sing-box | 1.14.3 | https://github.com/SagerNet/sing-box/releases/tag/v1.14.3 · GPL-3.0-or-later |
| Caddy | 2.11.7 | https://github.com/caddyserver/caddy/releases/tag/v2.11.7 · Apache-2.0 |
| AWG Go | b5928efb6ca19f0153958460c3d141f04abc5c2e | https://github.com/amnezia-vpn/amneziawg-go/tree/b5928efb6ca19f0153958460c3d141f04abc5c2e · MIT |
| AWG tools | ee0f0a9aa34ff0a0da4b3433b9512781cfe02843 | https://github.com/amnezia-vpn/amneziawg-tools/tree/ee0f0a9aa34ff0a0da4b3433b9512781cfe02843 · GPL-2.0 |
| Go для сборки AWG | 1.27.2 | https://go.dev/dl/ · BSD-3-Clause |
| Python | 3.12–3.14, из выбранной Ubuntu LTS | 24.04/26.04; точные Python-пакеты в requirements.lock |
| nftables/iproute2 | из Ubuntu LTS, security updates разрешены | Установленные версии сохраняются в /etc/ruvpn/os-packages.txt |

AWG tools из этого commit выводит версию v3.1.20260812. Его make создаёт src/wg,
установщик размещает этот файл как bin/awg. HeaderProtectionKey и RandomTrailers
поддерживаются обеими закреплёнными реализациями. Булевы параметры awg-tools
используют on/off; конфигурация не подменяет их строкой true.

В режиме AWG 3.1 с HeaderProtectionKey и RandomTrailers применяются фиксированные
H1–H4=1/2/3/4 и одинаковые S1–S4=24. Защита message type выполняется HP ключом,
случайным для установки; широкие H-диапазоны здесь не используются.

## Списки

RU-IP: ipverse/country-ip-blocks, commit
90a64519047d06dd1f7419bb8662f209bd17a1cc, файл
country/ru/ipv4-aggregated.txt. 8 663 IPv4 prefix; лицензия CC0-1.0
в data/IPVERSE-LICENSE, hash исходных байтов и metadata в data/sources.json.
Источник использует делегирование всех RIR. Это не база фактического места
размещения каждого сервиса и не основание переопределять известное иностранное имя.

RU-services: собственный базовый набор проекта из 133 suffix, MIT. Он включает
ru/su/рф и отдельные домены сервисов в других зонах. Это редактируемое проектное
решение, а не обещание официальной/исчерпывающей классификации. Более точные
исключения задаёт владелец ручными правилами. domains_url необязателен;
внешний текстовый источник должен иметь указанную владельцем лицензию.

Первый запуск использует эти локальные файлы и не зависит от сетевой загрузки
списков. Последующие версии записывают время и SHA256 скачанного содержимого;
предыдущая версия остаётся доступна для отката.

## Документация реализации

- https://sing-box.sagernet.org/configuration/inbound/tun/
- https://sing-box.sagernet.org/configuration/inbound/vless/
- https://sing-box.sagernet.org/configuration/outbound/vless/
- https://sing-box.sagernet.org/configuration/outbound/hysteria2/
- https://sing-box.sagernet.org/configuration/shared/tls/
- https://sing-box.sagernet.org/configuration/dns/server/fakeip/
- https://sing-box.sagernet.org/configuration/route/rule_action/
- https://sing-box.sagernet.org/configuration/outbound/selector/
- https://sing-box.sagernet.org/configuration/experimental/clash-api/
- https://caddyserver.com/docs/automatic-https

Для спорных полей использован исходный код тега v1.14.3. Например, selector
поддерживает block outbound этого тега, DNS использует типизированные server
и actions, а REALITY client содержит явный uTLS. Наличие новых полей в текущем
сайте документации само по себе не считается поддержкой в закреплённом бинарнике.
