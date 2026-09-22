# Installation på Raspberry Pi OS, Debian og Ubuntu

Denne guide installerer hele kæden på én Linux-maskine:

1. controller-aware RS485-gateway ved `19200 8E1` med HCP4-prioritet;
2. rå TCP-stream til Home Assistant på port `4196`;
3. WebUI på port `8080`;
4. lokal historik og systemdiagnostik;
5. login og en separat allowlistet admin-helper;
6. valgfri DS18B20/OneWire-service;
7. controller-API til Home Assistant med dynamiske Smart Auto-rum.

WebUI-gatewayen åbner serieporten én gang. Home Assistant forbinder via TCP og må ikke åbne samme USB-adapter direkte.

## Krav

- Raspberry Pi OS Bookworm, Debian 12 eller Ubuntu 22.04/24.04;
- systemd og `apt`;
- Python 3.11 eller nyere;
- en Linux-understøttet USB-RS485-adapter;
- Dantherm HCH5 MK1/HAC1. HCP4 kan forblive forbundet og har altid prioritet; Pi'en skriver kun, når HCP4 er stille og bussen er sund.

## Sikker RS485-tilslutning

Sluk ventilation og adapter, før ledninger ændres. PassiveLink tilsluttes som en kort parallel gren. Den eksisterende forbindelse mellem controller/HAC1 og HCH5 skal blive siddende. Pi-controlleren starter i `UNKNOWN`, observerer bussen og sender ingen control-writes, før sikker arbitration har valgt Pi'en som master.

| Eksisterende bus | Typisk adaptermærkning |
| --- | --- |
| A / 485+ / D+ | A / A+ / 485A / D+ |
| B / 485- / D- | B / B- / 485B / D- |
| Signalreference, hvis begge manualer angiver den | GND / SGND |

- A forbindes til A og B til B. Stol ikke på lederfarver alene.
- Kommer der ingen gyldige frames, sluk strømmen og byt kun A/B.
- Forbind aldrig beskyttelsesjord eller en forsyningsleder som signal-GND.
- Tilføj ikke automatisk endnu en 120 Ω terminering. Den eksisterende fungerende bus er normalt allerede termineret.
- Hold den parallelle gren kort og brug et snoet lederpar.
- Brug en galvanisk isoleret adapter ved permanent installation, hvis muligt.
- En M-Bus-adapter må ikke bruges; M-Bus er elektrisk inkompatibel med RS485.

Er terminalfunktionen uklar, skal en autoriseret installatør kontrollere forbindelsen.

## Find den stabile USB-sti

Tilslut adapteren og kør:

```bash
ls -l /dev/serial/by-id/
```

Brug hele stien, eksempelvis:

```text
/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_A1B2C3-if00-port0
```

Brug ikke `/dev/ttyUSB0`; nummeret kan ændre sig efter reboot.

## Én-kommando-installation

Erstat adapterstien i kommandoen:

```bash
curl -fsSL https://raw.githubusercontent.com/MRDonnii/dantherm-hch-passivelink-webui/main/install.sh \
  | sudo bash -s -- \
      --device /dev/serial/by-id/usb-DIN_ADAPTER \
      --enable-onewire
```

Udelad `--enable-onewire`, hvis der ikke bruges DS18B20-følere. Portene kan ændres med `--gateway-port` og `--web-port`.

### Beta 1.1.0

Brug den eksplicitte betakanal; den henter aldrig seneste stable ved en fejl:

```bash
curl -fsSL https://raw.githubusercontent.com/MRDonnii/dantherm-hch-passivelink-webui/test/hcp4-replacement-controller/install.sh \
  | sudo bash -s -- \
      --beta \
      --device /dev/serial/by-id/usb-DIN_ADAPTER
```

Installationsscriptet:

- installerer systempakker og en isoleret Python-venv;
- opretter den uprivilegerede bruger `passivelink-webui`;
- installerer og aktiverer systemd-services;
- genererer et tilfældigt admin-token i root-beskyttede miljøfiler;
- gemmer eksisterende konfiguration, login og controller-state i `/var/backups/dantherm-webui-*` og migrerer indstillinger uden reset;
- starter gateway, WebUI og admin-helper.

## Første login

Åbn den adresse, installeren viser, normalt:

```text
http://RASPBERRY-PI-IP:8080/
```

Første besøg kræver, at ejeren selv opretter brugernavn og adgangskode. Der findes ingen standardadgangskode. Behold login aktiveret. Hvis login slås fra, kan alle på lokalnettet se anlægget og bruge Pi-administrationen.

## Home Assistant

1. Installer [Dantherm HCH PassiveLink-integrationen](https://github.com/MRDonnii/dantherm-hch-passivelink) via HACS.
2. Genstart Home Assistant.
3. Åbn **Indstillinger → Enheder og tjenester → Tilføj integration**.
4. Vælg **Dantherm HCH PassiveLink** og derefter **RS485 over TCP**.
5. Angiv Linux-maskinens IP og port `4196`.

[Åbn repositoryet direkte i HACS](https://my.home-assistant.io/redirect/hacs_repository/?owner=MRDonnii&repository=dantherm-hch-passivelink&category=integration)

Den klassiske PassiveLink TCP-forbindelse er read-only. Controllerfunktionerne bruger separat HTTP API med bearer-token; kun Pi-controlleren oversætter intent til de allerede verificerede RS485-writes. Bypass er fortsat read-only i betaen.

## Kontrol efter installation

### Debugrapport

Under **Diagnostik** kan ejeren hente én tidsstemplet `.txt`-fil, som er klar til at åbne eller sende videre. Rapporten samler den aktuelle PassiveLink-state, status og journaler for gateway, OneWire og admin-helper, Raspberry Pi-helbred, disk/RAM, netværk samt system- og kerneladvarsler.

Indsamlingen bruger kun en fast allowlist af read-only kommandoer. Kendte adgangskoder, tokens, cookies og Authorization-værdier maskeres automatisk, og logmængden er begrænset. Rapporten kan stadig indeholde lokale hostnames, IP-adresser og sensor-id'er, så filen bør gennemgås før deling.

```bash
systemctl status dantherm-webui-gateway.service
systemctl status dantherm-webui-admin.service
ss -ltn | grep -E ':(4196|8080) '
journalctl -u dantherm-webui-gateway.service -n 100 --no-pager
```

I WebUI skal RS485 blive `Ja`, seneste frame være få sekunder gammel, og temperaturer/blæsere begynde at opdatere. Hvis ikke, kontrollér 19200 8E1, A/B, adapterstien og at ingen anden proces ejer serieporten.

## Opdatering

Kør den samme installationskommando igen. Eksisterende gatewaykonfiguration genbruges, og en dateret backup oprettes før udskiftning.

## Firewall

Tillad kun det betroede LAN og Home Assistant. Eksempel med UFW:

```bash
sudo ufw allow from 10.0.0.0/24 to any port 8080 proto tcp
sudo ufw allow from HOME_ASSISTANT_IP to any port 4196 proto tcp
```

Tilpas subnet og adresse. Eksponér ikke portene direkte på internettet; brug HTTPS og en betroet reverse proxy/VPN ved fjernadgang.

## Afinstallation

Kør repositoryets `uninstall.sh`. Det stopper services og fjerner units, men bevarer som udgangspunkt konfiguration, login og historik, så data ikke slettes ved et uheld.
