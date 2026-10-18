#!/usr/bin/env python3
"""Foreign only: Python 3.8+, distro cryptography, an existing Docker daemon.

Owns one systemd unit and four iptables-legacy user chains. Extracts a static
binary from a digest-pinned image without running that image or its daemon.
Never changes Docker, FORWARD, NAT, sysctls, SSH or the host routing table.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import fcntl
import getpass
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import pwd
import re
import secrets
import shutil
import subprocess
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, x25519
from cryptography.x509.oid import NameOID
from gateway import compiler, crypto
from gateway.config import atomic, domain, read_json, write_json

SOURCE = Path(__file__).resolve().parent.parent
BASE = Path('/opt/ruvpn-foreign')
ETC = Path('/etc/ruvpn-foreign')
META, TX = ETC / 'meta.json', ETC / 'transaction.json'
UNIT = Path('/etc/systemd/system/ruvpn-foreign.service')
NAME = 'ruvpn-foreign'
CHAINS = ('RUVPNF_IN', 'RUVPNF_OUT')
FILES = ('meta.json', 'secrets.json', 'config/sing-box.json', 'config/hop.crt', 'config/hop.key')
FIREWALLS = ('/usr/sbin/iptables-legacy', '/usr/sbin/ip6tables-legacy')
ENV = {'PATH': '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C.UTF-8'}


def run(argv, check=True, timeout=45):
    p = subprocess.run([str(x) for x in argv], capture_output=True, text=True, timeout=timeout, env=ENV)
    if check and p.returncode:
        # Tool stderr can contain a line of a credential-bearing config.
        raise ValueError('Команда %s не выполнена (код %s)' % (Path(str(argv[0])).name, p.returncode))
    return p


def ipt(binary, *args, **kwargs):
    return run([binary, '-w', '5'] + list(args), **kwargs)


def current_pid():
    text = run(['systemctl', 'show', '--property=MainPID', '--value', NAME], check=False).stdout.strip()
    return int(text) if text.isdecimal() else 0


def input_anchor():
    return ['-m', 'comment', '--comment', NAME, '-j', CHAINS[0]]


def output_anchor(uid):
    return ['-m', 'owner', '--uid-owner', str(uid), '-m', 'comment', '--comment', NAME, '-j', CHAINS[1]]


def remove_firewall(meta):
    for binary in FIREWALLS:
        for parent, chain, anchor in [('INPUT', CHAINS[0], input_anchor()), ('OUTPUT', CHAINS[1], output_anchor(meta['uid']))]:
            while ipt(binary, '-C', parent, *anchor, check=False).returncode == 0:
                ipt(binary, '-D', parent, *anchor)
            if ipt(binary, '-S', chain, check=False).returncode == 0:
                ipt(binary, '-F', chain)
                ipt(binary, '-X', chain)


def firewall(meta):
    c, uid = meta['config'], meta['uid']
    f = c['foreign']
    for index, binary in enumerate(FIREWALLS):
        for chain in CHAINS:
            if ipt(binary, '-S', chain, check=False).returncode:
                ipt(binary, '-N', chain)
            ipt(binary, '-F', chain)
        for proto, port in [('tcp', f['reality_port']), ('udp', f['hysteria_port'])]:
            rule = ['-p', proto, '--dport', str(port)]
            if index == 0:
                ipt(binary, '-A', CHAINS[0], *rule, '-s', c['network']['ru_ipv4'], '-j', 'ACCEPT')
            ipt(binary, '-A', CHAINS[0], *rule, '-j', 'DROP')
        ipt(binary, '-A', CHAINS[0], '-j', 'RETURN')
        if index == 0:
            ipt(binary, '-A', CHAINS[1], '-m', 'conntrack', '--ctstate', 'ESTABLISHED,RELATED', '-j', 'RETURN')
            addresses = json.loads(run(['ip', '-j', '-4', 'addr', 'show']).stdout)
            local = [a['local'] + '/32' for dev in addresses for a in dev.get('addr_info', []) if a.get('family') == 'inet']
            denied = compiler.PRIVATE + ['198.18.0.0/15', f['ipv4'] + '/32', c['network']['ru_ipv4'] + '/32'] + local
            for cidr in sorted(set(denied)):
                ipt(binary, '-A', CHAINS[1], '-d', cidr, '-j', 'REJECT')
            ipt(binary, '-A', CHAINS[1], '-j', 'RETURN')
        else:
            ipt(binary, '-A', CHAINS[1], '-j', 'REJECT')
        for parent, anchor in [('INPUT', input_anchor()), ('OUTPUT', output_anchor(uid))]:
            if ipt(binary, '-C', parent, *anchor, check=False).returncode:
                ipt(binary, '-I', parent, '1', *anchor)


def make_secrets():
    key = x25519.X25519PrivateKey.generate()
    encode = lambda data: base64.urlsafe_b64encode(data).decode().rstrip('=')
    return {'hop_reality_private': encode(key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())),
            'hop_reality_public': encode(key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)),
            'hop_short_id': secrets.token_hex(8), 'hop_uuid': str(uuid.uuid4()),
            'hop_password': secrets.token_urlsafe(32), 'obfs_password': secrets.token_urlsafe(32)}


def make_certificate(c):
    key = ec.generate_private_key(ec.SECP256R1(), default_backend())
    now = dt.datetime.now(dt.timezone.utc)
    name = c['foreign']['tls_server_name']
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(minutes=5))
            .not_valid_after(now + dt.timedelta(days=365))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(name)]), critical=False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .sign(key, hashes.SHA256(), default_backend()))
    return cert.public_bytes(serialization.Encoding.PEM), key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())


def pair_data(c, s, cert):
    f = c['foreign']
    return {'schema': 1, 'ipv4': f['ipv4'], 'reality_port': f['reality_port'], 'hysteria_port': f['hysteria_port'],
            'server_name': f['server_name'], 'tls_server_name': f['tls_server_name'], 'uuid': s['hop_uuid'],
            'public_key': s['hop_reality_public'], 'short_id': s['hop_short_id'], 'password': s['hop_password'],
            'obfs_password': s['obfs_password'], 'certificate': cert.decode()}


def new_password():
    password = getpass.getpass('Новый пароль пакета (16+ символов): ')
    if len(password) < 16 or password != getpass.getpass('Повторите пароль: '):
        raise ValueError('Нужны совпадающие пароли длиной от 16 символов')
    return password


def encrypted_output(path, data):
    path = Path(path).absolute()
    if path.exists() or path.is_symlink():
        raise ValueError('Файл уже существует; задайте другой --output')
    blob = crypto.encrypt(json.dumps(data).encode(), new_password())
    # Refuse overwrite even if another process creates the file during a prompt.
    fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as target:
        target.write(blob)
        target.flush()
        os.fsync(target.fileno())
    return path


def config_from_args(args, previous=None):
    c = json.loads(json.dumps(previous)) if previous else {
        'network': {'uplink': 'auto'}, 'dns': {'foreign': '1.1.1.1'},
        'foreign': {'reality_port': 443, 'hysteria_port': 443, 'server_name': 'www.microsoft.com', 'tls_server_name': 'hop.ruvpn.internal'}}
    for argument, section, field in [('ru', 'network', 'ru_ipv4'), ('foreign', 'foreign', 'ipv4'),
            ('uplink', 'network', 'uplink'), ('dns', 'dns', 'foreign'), ('server_name', 'foreign', 'server_name'),
            ('reality_port', 'foreign', 'reality_port'), ('hysteria_port', 'foreign', 'hysteria_port')]:
        value = getattr(args, argument, None)
        if value is not None:
            c[section][field] = value
    for value in [c['network'].get('ru_ipv4', ''), c['foreign'].get('ipv4', '')]:
        if not ipaddress.IPv4Address(value).is_global:
            raise ValueError('Укажите --ru и --foreign: два публичных IPv4')
    if c['network']['ru_ipv4'] == c['foreign']['ipv4']:
        raise ValueError('RU и foreign должны иметь разные IPv4')
    if c['network']['uplink'] == 'auto':
        c['network']['uplink'] = json.loads(run(['ip', '-j', 'route', 'get', '1.1.1.1']).stdout)[0]['dev']
    if not re.fullmatch(r'[a-zA-Z0-9_.:-]{1,15}', c['network']['uplink']):
        raise ValueError('Некорректный uplink')
    run(['ip', 'link', 'show', 'dev', c['network']['uplink']])
    ipaddress.IPv4Address(c['dns']['foreign'])
    for field in ['server_name', 'tls_server_name']:
        c['foreign'][field] = domain(c['foreign'][field])
    for field in ['reality_port', 'hysteria_port']:
        if not isinstance(c['foreign'][field], int) or not 1 <= c['foreign'][field] <= 65535:
            raise ValueError('Некорректный порт')
    return c


def preflight(c):
    if TX.exists():
        raise ValueError('Сначала confirm-network или rollback-network ожидающего изменения')
    if Path('/etc/ruvpn/role').exists():
        raise ValueError('Нативная роль RU/foreign уже установлена; смешивать режимы нельзя')
    version = run(['docker', 'version', '--format', '{{.Server.Version}}']).stdout.strip()
    if int(version.split('.')[0]) < 20:
        raise ValueError('Нужен Docker Engine 20 или новее')
    run(['systemctl', 'is-active', 'docker'])
    fragment = run(['systemctl', 'show', '--property=FragmentPath', '--value', NAME], check=False).stdout.strip()
    if not META.exists() and (UNIT.exists() or fragment):
        raise ValueError('Имя systemd-службы ruvpn-foreign уже занято')
    if not META.exists():
        for binary in FIREWALLS:
            for chain in CHAINS:
                if ipt(binary, '-S', chain, check=False).returncode == 0:
                    raise ValueError('Имя firewall-цепочки уже занято; чужие правила не изменены')
    pid = current_pid()
    for protocol, port in [('t', c['foreign']['reality_port']), ('u', c['foreign']['hysteria_port'])]:
        lines = run(['ss', '-H', '-ln' + protocol + 'p', 'sport', '=', str(port)]).stdout.splitlines()
        if any(not pid or ('pid=%d,' % pid) not in line for line in lines):
            raise ValueError('Новый порт занят другим процессом; он не остановлен')


def account():
    try:
        entry = pwd.getpwnam('ruvpn-hop')
        if entry.pw_shell != '/usr/sbin/nologin' or entry.pw_uid == 0:
            raise ValueError('Имя ruvpn-hop занято неподходящей учётной записью')
    except KeyError:
        run(['useradd', '--system', '--user-group', '--no-create-home', '--home-dir', '/nonexistent', '--shell', '/usr/sbin/nologin', 'ruvpn-hop'])
        entry = pwd.getpwnam('ruvpn-hop')
    # A numeric UID may also be used by an unrelated container. Refuse to filter it.
    own_pid = current_pid()
    for line in run(['ps', '-e', '-o', 'uid=,pid=']).stdout.splitlines():
        uid, pid = map(int, line.split())
        if uid == entry.pw_uid and pid != own_pid:
            raise ValueError('UID ruvpn-hop уже используется другим процессом; его сеть не изменена')
    return entry.pw_uid, entry.pw_gid


def extract_binary(image, target, version):
    # network=none, no ports, never started; only this freshly-created ID is removed.
    cid = run(['docker', 'create', '--network', 'none', image, 'version']).stdout.strip()
    if not re.fullmatch(r'[a-f0-9]{64}', cid):
        raise ValueError('Docker не вернул ID временного контейнера')
    try:
        run(['docker', 'cp', cid + ':/usr/local/bin/sing-box', str(target)])
    finally:
        run(['docker', 'rm', cid], check=False)
    target.chmod(0o755)
    text = run([target, 'version']).stdout
    if not text.startswith('sing-box version ' + version + '\n'):
        raise ValueError('Версия извлечённого бинарника не совпадает с release.json')
    return hashlib.sha256(target.read_bytes()).hexdigest()


def install_code(image):
    version = read_json(SOURCE / 'release.json')['version']
    release = BASE / 'releases' / (version + '-' + dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%f'))
    release.mkdir(parents=True, mode=0o755)
    for path in [BASE, BASE / 'releases', release]:
        path.chmod(0o755)
    files = ['release.json', 'gateway/__init__.py', 'gateway/config.py', 'gateway/compiler.py', 'gateway/crypto.py',
             'scripts/foreign-compat.py', 'scripts/foreign-compat.sh']
    for name in files:
        target = release / name
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
        target.parent.chmod(0o755)
        shutil.copyfile(str(SOURCE / name), str(target))
        target.chmod(0o755 if name.endswith('.sh') else 0o644)
    (release / 'bin').mkdir(mode=0o755)
    (release / 'bin').chmod(0o755)
    digest = extract_binary(image, release / 'bin/sing-box', read_json(SOURCE / 'release.json')['sing_box'])
    return str(release), digest


def activate_code(release):
    temporary = BASE / 'current.new'
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(release)
    os.replace(str(temporary), str(BASE / 'current'))


def write_material(meta, s, cert, key):
    ETC.chmod(0o750)
    os.chown(str(ETC), 0, meta['gid'])
    write_json(META, meta)
    write_json(ETC / 'secrets.json', s)
    folder = ETC / 'config'
    folder.mkdir(exist_ok=True, mode=0o750)
    folder.chmod(0o750)
    os.chown(str(folder), 0, meta['gid'])
    for name, data in [('hop.crt', cert), ('hop.key', key), ('sing-box.json', json.dumps(compiler.foreign_config(meta['config'], s, folder), indent=2))]:
        path = folder / name
        atomic(path, data, 0o640)
        os.chown(str(path), 0, meta['gid'])


def unit_text():
    return '''[Unit]
Description=RU / Foreign egress (preserves existing Docker VPN)
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=60
StartLimitBurst=5

[Service]
Type=simple
WorkingDirectory=/opt/ruvpn-foreign/current
User=ruvpn-hop
Group=ruvpn-hop
ExecStartPre=+/usr/bin/python3 /opt/ruvpn-foreign/current/scripts/foreign-compat.py guard
ExecStart=/opt/ruvpn-foreign/current/bin/sing-box run -c /etc/ruvpn-foreign/config/sing-box.json
Restart=on-failure
RestartSec=5
TimeoutStopSec=30
LimitNOFILE=65536
StandardOutput=null
StandardError=null
AmbientCapabilities=CAP_NET_RAW CAP_NET_BIND_SERVICE
CapabilityBoundingSet=CAP_NET_RAW CAP_NET_BIND_SERVICE
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX AF_NETLINK
UMask=0077

[Install]
WantedBy=multi-user.target
'''


def stage(uid, seconds, release, output=None):
    old_current = str((BASE / 'current').resolve()) if (BASE / 'current').is_symlink() else None
    tx = {'files': {name: base64.b64encode((ETC / name).read_bytes()).decode() if (ETC / name).exists() else None for name in FILES},
          'unit': base64.b64encode(UNIT.read_bytes()).decode() if UNIT.exists() else None,
          'old_current': old_current, 'old_enabled': run(['systemctl', 'is-enabled', NAME], check=False).returncode == 0,
          'old_running': run(['systemctl', 'is-active', NAME], check=False).returncode == 0,
          'pair': {'path': str(output), 'sha256': hashlib.sha256(output.read_bytes()).hexdigest()} if output else None,
          'uid': uid, 'created': int(time.time()), 'deadline': int(time.time()) + seconds,
          'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip()}
    write_json(TX, tx)
    try:
        run(['systemd-run', '--quiet', '--collect', '--unit=ruvpn-foreign-rollback', '--on-active=%ss' % seconds,
             '/usr/bin/python3', str(Path(release) / 'scripts/foreign-compat.py'), 'rollback-network'])
    except BaseException:
        TX.unlink()
        raise


def rollback(runtime=True):
    if not TX.exists():
        return
    tx = read_json(TX)
    if runtime:
        run(['systemctl', 'stop', NAME], check=False, timeout=45)
    remove_firewall({'uid': tx['uid']})
    for name in FILES:
        data = tx['files'][name]
        if data is None:
            (ETC / name).unlink(missing_ok=True)
        else:
            atomic(ETC / name, base64.b64decode(data))
    if tx['unit'] is None:
        run(['systemctl', 'disable', NAME], check=False)
        UNIT.unlink(missing_ok=True)
    else:
        atomic(UNIT, base64.b64decode(tx['unit']), 0o644)
    link = BASE / 'current'
    if tx['old_current']:
        link.unlink(missing_ok=True)
        link.symlink_to(tx['old_current'])
    else:
        link.unlink(missing_ok=True)
    if META.exists():
        meta = read_json(META)
        write_material(meta, read_json(ETC / 'secrets.json'), (ETC / 'config/hop.crt').read_bytes(), (ETC / 'config/hop.key').read_bytes())
        firewall(meta)
    run(['systemctl', 'daemon-reload'])
    if tx['unit'] is not None:
        run(['systemctl', 'enable' if tx['old_enabled'] else 'disable', NAME])
    TX.unlink()
    run(['systemctl', 'stop', 'ruvpn-foreign-rollback.timer'], check=False)
    if runtime and tx['old_running'] and META.exists():
        run(['systemctl', 'start', NAME], timeout=45)
    if tx.get('pair'):
        path = Path(tx['pair']['path'])
        if path.is_file() and not path.is_symlink() and hashlib.sha256(path.read_bytes()).hexdigest() == tx['pair']['sha256']:
            path.unlink()
    print('Предыдущее состояние foreign восстановлено; правила Docker и старый VPN не изменялись.')


def apply(args, rotate=False, restored=None):
    previous = read_json(META) if META.exists() else None
    if args.command == 'install' and previous:
        raise ValueError('Уже установлен: используйте configure; ключи сохранятся')
    if args.command != 'install' and not previous:
        raise ValueError('Сначала установите foreign')
    c = config_from_args(args, restored['config'] if restored else previous['config'] if previous else None)
    if restored and any(c[section][field] != previous['config'][section][field] for section, field in [('network', 'ru_ipv4'), ('network', 'uplink'), ('foreign', 'ipv4')]):
        raise ValueError('Восстановление допускается только на том же адресе foreign, uplink и с тем же RU')
    preflight(c)
    uid, gid = account()
    if previous and (uid, gid) != (previous['uid'], previous['gid']):
        raise ValueError('UID/GID ruvpn-hop изменены; нужна ручная адаптация')
    manifest = read_json(SOURCE / 'release.json')
    image = manifest['foreign_compat']['image']
    if not re.fullmatch(r'ghcr.io/sagernet/sing-box@sha256:[a-f0-9]{64}', image):
        raise ValueError('Образ должен быть закреплён по SHA256 в release.json')
    # Slow work and password prompts happen before the network rollback timer.
    print('Загрузка закреплённого образа sing-box %s…' % manifest['sing_box'], flush=True)
    if run(['docker', 'image', 'inspect', image], check=False).returncode:
        run(['docker', 'pull', image], timeout=900)
    release, digest = install_code(image)
    if restored:
        s, cert, key = restored['secrets'], base64.b64decode(restored['certificate']), base64.b64decode(restored['key'])
        validate_material(c, s, cert, key)
    else:
        s = make_secrets() if rotate or not previous else read_json(ETC / 'secrets.json')
        cert, key = make_certificate(c) if rotate or not previous else ((ETC / 'config/hop.crt').read_bytes(), (ETC / 'config/hop.key').read_bytes())
    output = None
    if rotate or not previous or restored:
        output = encrypted_output(args.output, pair_data(c, s, cert))
    try:
        stage(uid, args.rollback_seconds, release, output)
        run(['systemctl', 'stop', NAME], check=False, timeout=45)
        activate_code(release)
        meta = {'config': c, 'uid': uid, 'gid': gid, 'image': image, 'release': release, 'binary_sha256': digest}
        write_material(meta, s, cert, key)
        run([Path(release) / 'bin/sing-box', 'check', '-c', ETC / 'config/sing-box.json'], timeout=60)
        firewall(meta)
        atomic(UNIT, unit_text(), 0o644)
        run(['systemctl', 'daemon-reload'])
        run(['systemctl', 'enable', '--now', NAME], timeout=60)
        for attempt in range(20):
            if current_pid() and run(['systemctl', 'is-active', NAME], check=False).returncode == 0:
                break
            time.sleep(0.25)
        else:
            raise ValueError('Новая служба не запущена')
        if not TX.exists() or read_json(META)['release'] != release:
            raise ValueError('Изменение уже отменено guard; повторите установку/настройку')
        if output:
            print('Зашифрованный пакет: %s' % output)
        print('Ожидается подтверждение сети: %s секунд.' % args.rollback_seconds)
        print('/opt/ruvpn-foreign/current/scripts/foreign-compat.sh confirm-network')
    except BaseException:
        rollback()
        if output:
            output.unlink(missing_ok=True)
        raise


def validate_material(c, s, cert, key):
    expected = {'hop_reality_private', 'hop_reality_public', 'hop_short_id', 'hop_uuid', 'hop_password', 'obfs_password'}
    if not isinstance(s, dict) or set(s) != expected:
        raise ValueError('Неизвестные поля межсерверных ключей')
    private = x25519.X25519PrivateKey.from_private_bytes(base64.urlsafe_b64decode(s['hop_reality_private'] + '='))
    public = base64.urlsafe_b64encode(private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode().rstrip('=')
    if public != s['hop_reality_public'] or not re.fullmatch(r'[a-f0-9]{16}', s['hop_short_id']):
        raise ValueError('Некорректная пара ключей REALITY')
    uuid.UUID(s['hop_uuid'])
    if any(not isinstance(s[name], str) or not 20 <= len(s[name]) <= 256 for name in ['hop_password', 'obfs_password']):
        raise ValueError('Некорректный секрет транспорта')
    crt = x509.load_pem_x509_certificate(cert, default_backend())
    private_key = serialization.load_pem_private_key(key, password=None, backend=default_backend())
    encoding, form = serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    if crt.public_key().public_bytes(encoding, form) != private_key.public_key().public_bytes(encoding, form):
        raise ValueError('Сертификат и приватный ключ не совпадают')
    names = crt.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.DNSName)
    expiry = crt.not_valid_after_utc if hasattr(crt, 'not_valid_after_utc') else crt.not_valid_after.replace(tzinfo=dt.timezone.utc)
    if c['foreign']['tls_server_name'] not in names or expiry <= dt.datetime.now(dt.timezone.utc):
        raise ValueError('Сертификат истёк или выпущен для другого имени')


def backup(output):
    if TX.exists():
        raise ValueError('Сначала подтвердите или откатите изменение сети')
    data = {'mode': 'foreign-compat', 'schema': 1, 'config': read_json(META)['config'], 'secrets': read_json(ETC / 'secrets.json'),
            'certificate': base64.b64encode((ETC / 'config/hop.crt').read_bytes()).decode(),
            'key': base64.b64encode((ETC / 'config/hop.key').read_bytes()).decode()}
    print('Зашифрованная копия: %s' % encrypted_output(output, data))


def restore(args):
    path = Path(args.file)
    if path.stat().st_size > 1024 * 1024:
        raise ValueError('Файл восстановления слишком большой')
    password = getpass.getpass('Пароль резервной копии: ')
    data = json.loads(crypto.decrypt(path.read_bytes(), password))
    if not isinstance(data, dict) or set(data) != {'mode', 'schema', 'config', 'secrets', 'certificate', 'key'} or data['mode'] != 'foreign-compat' or data['schema'] != 1:
        raise ValueError('Неизвестная схема резервной копии')
    apply(args, restored=data)


def guard():
    if TX.exists():
        tx = read_json(TX)
        boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        if tx['boot_id'] != boot or int(time.time()) >= tx['deadline']:
            rollback(runtime=False)
    if not META.exists():
        raise ValueError('Подтверждённого foreign нет; после отката повторите установку')
    meta = read_json(META)
    binary = Path(meta['release']) / 'bin/sing-box'
    if hashlib.sha256(binary.read_bytes()).hexdigest() != meta['binary_sha256']:
        raise ValueError('Бинарник foreign изменён; запуск остановлен')
    firewall(meta)


def status():
    print('Роль: foreign compat; PID: %s' % current_pid())
    print('Служба: ' + run(['systemctl', 'is-active', NAME], check=False).stdout.strip())
    if TX.exists():
        print('Ожидается подтверждение; до отката: %s сек.' % max(0, read_json(TX)['deadline'] - int(time.time())))
    if META.exists():
        c = read_json(META)['config']
        print('Разрешён RU: %s; TCP/%s, UDP/%s' % (c['network']['ru_ipv4'], c['foreign']['reality_port'], c['foreign']['hysteria_port']))
        cert = x509.load_pem_x509_certificate((ETC / 'config/hop.crt').read_bytes(), default_backend())
        expiry = cert.not_valid_after_utc if hasattr(cert, 'not_valid_after_utc') else cert.not_valid_after.replace(tzinfo=dt.timezone.utc)
        print('Hysteria TLS до: ' + expiry.isoformat())
    print('Статус процесса не подтверждает прохождение трафика с RU.')


def main():
    os.umask(0o077)
    if os.geteuid() != 0:
        raise ValueError('Запустите от root')
    parser = argparse.ArgumentParser(description='Foreign рядом с существующим Docker VPN, без обновления Ubuntu 20.04')
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ['install', 'configure', 'rotate-pair']:
        p = sub.add_parser(name)
        p.add_argument('--ru')
        p.add_argument('--foreign')
        p.add_argument('--uplink')
        p.add_argument('--dns')
        p.add_argument('--server-name')
        p.add_argument('--reality-port', type=int)
        p.add_argument('--hysteria-port', type=int)
        p.add_argument('--rollback-seconds', type=int, default=600, choices=range(60, 601), metavar='60..600')
        p.add_argument('--output', default='/root/ruvpn-pair.ruvpn')
    for name in ['confirm-network', 'rollback-network', 'status', 'guard']:
        sub.add_parser(name)
    p = sub.add_parser('export-pair')
    p.add_argument('--output', default='/root/ruvpn-pair.ruvpn')
    p = sub.add_parser('backup')
    p.add_argument('--output', default='/root/ruvpn-foreign-backup.ruvpn')
    p = sub.add_parser('restore')
    p.add_argument('file')
    p.add_argument('--output', default='/root/ruvpn-pair-restored.ruvpn')
    p.add_argument('--rollback-seconds', type=int, default=600, choices=range(60, 601), metavar='60..600')
    args = parser.parse_args()
    ETC.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Preserve daemon traversal permissions after the first successful apply.
    # guard runs in ExecStartPre while apply holds the operations lock.
    lock = None
    if args.command != 'guard':
        lock = (ETC / 'operations.lock').open('a')
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX if args.command == 'rollback-network' else fcntl.LOCK_EX | fcntl.LOCK_NB)
    if args.command in ['install', 'configure', 'rotate-pair']:
        apply(args, rotate=args.command == 'rotate-pair')
    elif args.command == 'confirm-network':
        if not TX.exists():
            raise ValueError('Нет ожидающего изменения сети')
        tx = read_json(TX)
        if int(time.time()) >= tx['deadline'] or tx['boot_id'] != Path('/proc/sys/kernel/random/boot_id').read_text().strip():
            rollback()
            raise ValueError('Срок подтверждения истёк; изменение отменено')
        run(['systemctl', 'is-active', NAME])
        if not current_pid():
            raise ValueError('Новая служба не работает; подтверждение отклонено')
        run(['systemctl', 'stop', 'ruvpn-foreign-rollback.timer'], check=False)
        TX.unlink()
        print('Сеть foreign подтверждена.')
    elif args.command == 'rollback-network':
        rollback()
    elif args.command == 'guard':
        guard()
    elif args.command == 'status':
        status()
    elif args.command == 'export-pair':
        c = read_json(META)['config']
        path = encrypted_output(args.output, pair_data(c, read_json(ETC / 'secrets.json'), (ETC / 'config/hop.crt').read_bytes()))
        print('Зашифрованный пакет: %s' % path)
    elif args.command == 'backup':
        backup(args.output)
    elif args.command == 'restore':
        restore(args)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('Операция прервана. Ожидающее изменение сети отменит таймер.', file=sys.stderr)
        sys.exit(130)
    except Exception as error:
        if isinstance(error, ValueError):
            print(str(error), file=sys.stderr)
        else:
            print('Операция не завершена (%s). Секреты не выводятся.' % type(error).__name__, file=sys.stderr)
        sys.exit(1)
