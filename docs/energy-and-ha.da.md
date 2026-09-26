# Home Assistant, sensorer og energi

## Installer og opdater

1. Installer [HCH PassiveLink-integrationen i HACS](https://my.home-assistant.io/redirect/hacs_repository/?owner=MRDonnii&repository=dantherm-hch-passivelink&category=integration). Genstart HA efter installation eller opdatering.
2. Tilføj **Dantherm HCH PassiveLink** under **Indstillinger → Enheder og tjenester**. Vælg RS485 over TCP, og angiv Pi'ens lokale adresse og port **4196**.
3. Installer [Smart Home Cards i HACS](https://my.home-assistant.io/redirect/hacs_repository/?owner=MRDonnii&repository=ha-smart-home-cards&category=plugin). Tilføj HCH5 Live Card på dit dashboard. En hård browseropdatering kan være nødvendig efter kortopdatering.
4. Hvis controllerfunktioner ønskes, skal integrationen desuden have Pi'ens HTTP-adresse og særskilte controller-token. Det bruges kun til controller-API'en; rå TCP-forbindelse er fortsat en separat datakilde. Tokenet vises på Pi'en med `sudo sed -n 's/^DANTHERM_CONTROLLER_TOKEN=//p' /etc/dantherm-passivelink-webui/gateway.env`. Opbevar det kun i HA, ikke i dashboard-YAML eller Git.
5. WebUI-siden **Opdateringer** har genveje til begge HACS-repositories. Pi-opdateringsknappen opdaterer kun WebUI/controlleren; HA-integration og kort opdateres i HACS.

## HA-sensorer til Pi

Under integrationens controllerindstillinger (**Indstillinger → Enheder og tjenester → Dantherm HCH PassiveLink → Konfigurér**, trinnet *Raspberry Pi-controller og Smart Auto*) kan du vælge fire valgfrie sensorer, som Pi'en kun viser i WebUI:

| Felt i integrationen | Vælg | Bruges i WebUI til |
| --- | --- | --- |
| Effektmåler på anlægget | Aktuel effekt i W/kW, fx en Shelly på anlæggets forsyning | Effekt, SFP og filtertjek via strømforbrug |
| Dantherms elforbrug i dag | Daglig kWh, fx en Utility Meter (se nedenfor) | **Strøm i dag · målt** i stedet for Pi'ens anslag |
| Elpris | Aktuel elpris i kr/kWh (øre/kWh og DKK/MWh omregnes) | Ca. kr for dagens strøm |
| Varmepris | Aktuel fjernvarme-/varmepris i kr/kWh | Ca. kr for eftervarme og teoretisk værdi af genvundet varme |

Værdierne sendes til Pi'en ved opstart og derefter hvert minut som tidsbegrænsede, læsbare signaler (gyldige i fem minutter). Stopper HA, forsvinder de fra WebUI af sig selv. Ingen af dem ændrer ventilationsstyringen. Rumkilder kan tilføjes med temperatur, fugt og CO₂; for hver kilde vælges, om den må styre Smart Auto (`control: true`) eller kun vises (`control: false`). Brug kun styring for rum, der faktisk skal påvirke ventilationsniveauet. Pi'en udløber gamle HA-data og fortsætter lokal drift, når HA ikke svarer.

Udendørs vejr og luftkvalitet i WebUI kommer fra Open-Meteo i browseren og kræver ikke HA. Google Air Quality i HA kan vises i HA-kortets udendørs luftkvalitetsfelt; det er ikke en vejrudsigt og styrer ikke automatisk ventilatoren.

## Dagens strøm

Den bedste kilde er en fysisk elmålers **akkumulerede kWh-sensor** for Dantherm alene. Opret HA-hjælperen **Forbrugsmåler (Utility Meter)** med denne sensor som kilde og cyklus **Daglig**. Det giver et målt dagsforbrug, som nulstilles ved lokal midnat. Peg `entities.measured_energy_today` i HCH5-kortet på hjælperens nye sensor. `entities.electricity_price` kan pege på en sensor i **kr/kWh**.

Uden en fysisk kWh-måler bruger Pi'en integreret effekt (W) som et anslag. Pi-tælleren dækker kun perioder, hvor effektdata og controlleren har været online; den må ikke forveksles med elmålerens fulde døgn. Ved oprettelse midt på dagen starter en ny Utility Meter normalt på 0; brug dens **Kalibrer**-handling med forskellen mellem elmålerens nuværende værdi og dens værdi ved midnat, hvis HA-historikken er pålidelig.

## Eftervarme og varmegenvinding

Pi'en anslår varme til luften som luftmængde × luftens varmekapacitet × temperaturstigning over eftervarmefladen. Genvundet varme anslås tilsvarende over varmeveksleren. Værdierne vises hver for sig i kWh. Varmeprisen kan tilføjes som `entities.heat_price` i HA-kortet, i **kr/kWh**. `entities.afterheat_today` og `entities.recovered_today` peger på Pi-integrationens energisensorer.

Disse tal er **ikke** målt vandbåret varmeforbrug: fremløbs- og returtemperatur uden målt vandflow kan ikke give et faktisk fjernvarmeforbrug. Visningen af eftervarme i kr er derfor et anslag for varme leveret til luften. Genvundet kWh × varmepris er en **teoretisk værdi af genbrugt varme**, ikke en registreret besparelse på fakturaen. Den reelle besparelse afhænger også af husets varmebehov, virkningsgrad, driftstid og alternativ opvarmning.

Hvis prissensorerne er tomme eller utilgængelige, vises `—` i stedet for et opdigtet kronebeløb. Når en aktuel elpris bruges for hele dagens kWh, mærkes beløbet **ca.**; for en præcis daglig elregning kræves timeopdelt pris ganget med forbrug i samme timer.

## Valgfri energidata fra HA til WebUI uden integrationen

Bruger du integrationens felter ovenfor, er dette afsnit ikke nødvendigt. Andre systemer kan sende de samme værdier direkte: WebUI/controller-API'en kan modtage disse ekstra, tidsbegrænsede værdier i `POST /api/controller/signals`:

```json
{
  "unit_energy_measured_today_kwh": 1.42,
  "electricity_price_dkk_kwh": 2.10,
  "heat_price_dkk_kwh": 0.60,
  "valid_for_s": 300
}
```

Kaldet kræver samme bearer-token som controller-API'en. Send højst én gang pr. minut og forny inden fem minutter; efter udløb skjules de eksterne værdier automatisk. Hver værdi kan udelades. Tilføj ikke rå HA-token eller Pi-token i et offentligt dashboard eller repository. HCH5-kortet kan bruge HA-sensorerne direkte, også uden dette valgfrie push til WebUI.

## Kortfelter

| Felt | Datakilde |
| --- | --- |
| `measured_energy_today` | Daglig Utility Meter fra fysisk Dantherm-elmåler |
| `electricity_price` | Aktuel elpris i kr/kWh |
| `afterheat_today` | Pi-estimat for varme til indblæsningsluften |
| `recovered_today` | Pi-estimat for varme genvundet i veksleren |
| `heat_price` | Aktuel varmepris i kr/kWh |

Kontrollér sensorernes enheder, navnlig at priserne er **kr/kWh** og ikke øre/kWh. Ingen af felterne ændrer controllerens styring.

### Eksempel: send dagstal og priser én gang i minuttet

Kun nødvendigt, hvis du ikke bruger integrationens felter; HA-kortet læser allerede HA-sensorerne direkte. Brug dine egne entity-id'er og Pi-adresse. Gem hele `Bearer <token>` som `hch5_controller_authorization` i HA's private `secrets.yaml`.

```yaml
# configuration.yaml eller en HA-package
rest_command:
  hch5_energy_signals:
    url: "http://HCH5_PI_IP:8080/api/controller/signals"
    method: POST
    headers:
      Authorization: !secret hch5_controller_authorization
    content_type: application/json
    payload: >-
      {"unit_energy_measured_today_kwh": {{ energy | float }},
       "electricity_price_dkk_kwh": {{ electricity_price | float }},
       "heat_price_dkk_kwh": {{ heat_price | float }},
       "valid_for_s": 180}

automation:
  - id: hch5_energy_signals_to_pi
    alias: HCH5 energi og priser til Pi
    triggers:
      - trigger: time_pattern
        minutes: "/1"
    conditions:
      - condition: template
        value_template: >-
          {{ is_number(states('sensor.YOUR_DAILY_ENERGY'))
             and is_number(states('sensor.YOUR_ELECTRICITY_PRICE'))
             and is_number(states('sensor.YOUR_HEAT_PRICE')) }}
    actions:
      - action: rest_command.hch5_energy_signals
        data:
          energy: "{{ states('sensor.YOUR_DAILY_ENERGY') }}"
          electricity_price: "{{ states('sensor.YOUR_ELECTRICITY_PRICE') }}"
          heat_price: "{{ states('sensor.YOUR_HEAT_PRICE') }}"
    mode: single
```

Kontrollér YAML-konfigurationen før genstart. HA skal genstartes efter en ny `rest_command` i YAML; automationen kan derefter administreres i HA. Dette HTTP-kald sender kun tal til visning og udløser ingen RS485-skrivning.
