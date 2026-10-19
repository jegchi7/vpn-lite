# Foreign рядом с существующей Amnezia на Ubuntu 20.04

Этот режим предназначен для foreign с Ubuntu 20.04, Python 3.8+, systemd и уже
работающим Docker Engine 20+. RU по-прежнему требует Ubuntu 24.04/26.04 и обычный
install-ru.sh. Предусмотрены amd64/arm64 официального образа sing-box.

## Что устанавливается

Системный пакет python3-cryptography нужен только для локального создания ключей,
сертификата и зашифрованного пакета сопряжения. pip, новая версия Python,
обновление дистрибутива и панель на foreign не требуются.

Из официального образа sing-box 1.14.3 извлекается самодостаточный бинарник.
OCI index закреплён по SHA256 в release.json; Docker проверяет digest образа,
установщик проверяет версию бинарника, затем сохраняет его SHA256 для запуска.
Временный контейнер имеет network=none, не запускается и удаляется по своему ID.
Сам sing-box работает отдельной systemd-службой от нового пользователя ruvpn-hop
с CAP_NET_RAW (bind к uplink на старом ядре) и CAP_NET_BIND_SERVICE.
Остановка Docker после установки не останавливает этот sing-box.

Управляемые пути:

- /opt/ruvpn-foreign/releases и /opt/ruvpn-foreign/current — код и бинарник;
- /etc/ruvpn-foreign — настройки и ключи;
- ruvpn-foreign.service — только новая служба.

Firewall добавляет собственные цепочки RUVPNF_IN/RUVPNF_OUT в iptables-legacy
и ip6tables-legacy. В INPUT фильтруются только новые TCP/UDP-порты: IPv4 только
с указанного RU, IPv6 закрыт. В OUTPUT ограничения относятся только к UID новой
службы: ответы разрешены, новые обращения к служебным/частным IP и IPv6 закрыты.
Если UID уже использует другой процесс/контейнер, установка останавливается.
Существующие цепочки не очищаются; FORWARD, NAT, Docker, UFW, sysctls, SSH и
маршруты не перенастраиваются. Если есть другой firewall, его запреты всё ещё
могут препятствовать новым подключениям: этот режим не отменяет чужие правила.

В исходном окружении Amnezia использует 30759/UDP, а sing-box — 443/TCP и
443/UDP. Они не пересекаются. Перед изменениями проверяется занятость новых портов.
Сосуществование на реальном VPS ещё не подтверждено эксплуатацией; статус
процесса сам по себе не подтверждает прохождение трафика по обоим путям.

## Установка на foreign

Из каталога проекта, от root, подставьте реальный публичный IPv4 RU:

```bash
chmod +x scripts/*.sh
./scripts/install-foreign-compat.sh --ru RU_IPV4 --foreign 141.98.166.179
```

IP foreign в примере относится к исходному развёртыванию; для другого сервера
подставьте его адрес. Uplink определяется локально. Необязательные параметры:
--uplink ens3, --reality-port 443, --hysteria-port 443, --server-name www.microsoft.com,
--dns 1.1.1.1, --rollback-seconds 600, --output /root/ruvpn-pair.ruvpn.

Установщик предложит пароль пакета длиной от 16 символов. Скачивание образа,
извлечение бинарника и ввод пароля происходят до запуска сетевого таймера.
Пакет совместим с обычным install-ru.sh/pair.sh. Его не нужно распечатывать
или отправлять в чат. Существующий файл пакета не перезаписывается.

После успешной установки откройте ещё одну SSH-сессию, убедитесь, что старое
подключение Amnezia работает, и подтвердите новое состояние в течение 600 секунд:

```bash
/opt/ruvpn-foreign/current/scripts/foreign-compat.sh status
docker ps --format 'table {{.Names}}\t{{.Ports}}'
/opt/ruvpn-foreign/current/scripts/foreign-compat.sh confirm-network
```

Без подтверждения таймер остановит только новую службу и вернёт её прежние
настройки/правила. При первой установке новая служба будет отключена. Если
перезагрузить сервер до подтверждения, guard на старте также выполнит этот откат.
Он не восстанавливает глобальный снимок iptables поверх актуальной сети Docker.

Передайте зашифрованный /root/ruvpn-pair.ruvpn на RU через собственный компьютер:

```bash
scp root@141.98.166.179:/root/ruvpn-pair.ruvpn .
scp ruvpn-pair.ruvpn root@RU_IPV4:/root/
```

На RU создайте обычный setup.toml с теми же адресами, затем:

```bash
./scripts/install-ru.sh --setup /root/setup.toml --pair /root/ruvpn-pair.ruvpn
/opt/ruvpn/current/scripts/configure.sh --confirm-network
```

Если TCP/8443 на RU занят, задайте panel.port = 8444 в setup.toml до установки.
Домен панели должен иметь A-запись на RU; для HTTP-01 доступен TCP/80. Остальные
требования RU, включая проверку существующего firewall, сохраняются.

## Управление foreign compat

Используйте команды именно этого режима; обычные configure.sh/backup.sh на
foreign compat не устанавливаются. На RU остаются обычные команды проекта.

```bash
# Статус без секретов; службы и проверка маршрутов — разные признаки
/opt/ruvpn-foreign/current/scripts/foreign-compat.sh status

# Повторный экспорт тех же межсерверных ключей в новый файл
/opt/ruvpn-foreign/current/scripts/foreign-compat.sh export-pair --output /root/pair-copy.ruvpn

# Изменение адреса RU без смены ключей
/opt/ruvpn-foreign/current/scripts/foreign-compat.sh configure --ru NEW_RU_IPV4
/opt/ruvpn-foreign/current/scripts/foreign-compat.sh confirm-network

# Явная ротация ключей/сертификата: затем импорт нового пакета на RU
/opt/ruvpn-foreign/current/scripts/foreign-compat.sh rotate-pair --output /root/pair-new.ruvpn
/opt/ruvpn-foreign/current/scripts/foreign-compat.sh confirm-network

# Отмена только ожидающего изменения этого режима
/opt/ruvpn-foreign/current/scripts/foreign-compat.sh rollback-network

# Зашифрованная копия ключей/настроек только новой foreign-службы
/opt/ruvpn-foreign/current/scripts/foreign-compat.sh backup --output /root/foreign-backup.ruvpn

# Восстановление на том же foreign/uplink и с тем же RU; затем импорт пакета на RU
/opt/ruvpn-foreign/current/scripts/foreign-compat.sh restore /root/foreign-backup.ruvpn --output /root/pair-restored.ruvpn
/opt/ruvpn-foreign/current/scripts/foreign-compat.sh confirm-network
```

После configure с изменением IP/порта заново экспортируйте пакет и импортируйте
его на RU обычным pair.sh. Ротация прерывает foreign-трафик до импорта нового
пакета на RU; пользовательские профили не меняются. Сертификат действует год.
Повторный install не заменяет ключи: для установленного узла используется configure.
Для обновления кода запустите scripts/foreign-compat.sh configure из нового
checkout этого проекта и подтвердите сеть. Предыдущий код и ключи сохраняются
для ожидающего сетевого отката; отдельной команды отката уже подтверждённой
версии пока нет. Резервная копия не содержит бинарники и старый VPN Amnezia.
Restore возвращает межсерверные ключи на дату копии; его новый пакет нужно
импортировать на RU. Копию и пароль храните раздельно. Для аварийного восстановления
ОС сохраняйте также используемый release в закрытой копии/снимке провайдера.
Зашифрованный пакет сопряжения
содержит клиентские параметры RU, но не заменяет копию приватного ключа foreign.

Ubuntu 20.04 остаётся установленной; её обслуживание и исправления безопасности
остаются отдельной задачей владельца сервера.
