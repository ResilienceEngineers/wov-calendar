# Sources — Window of Vulnerability

Sources are tiered by **track record and signal density**, not prestige. A source's tier moves up or down based on calibration findings logged in `backtest-log.md`. The Taleb principle applies: a few sources with strong track records beat many sources with broad coverage.

This file is mirrored to `data/sources.json` for machine consumption.

---

## Tier 1 — Primary, official, verifiable

First-party operational sources. A claim sourced here counts as **Hard** signal.

### Seasonality (agency outlooks + advisories)
- **NOAA NHC** — `nhc.noaa.gov` — Atlantic and East/Central Pacific hurricane bulletins, seasonal outlooks (May / August updates)
- **NOAA CPC** — `cpc.ncep.noaa.gov` — ENSO Alert, monthly + seasonal outlooks (modulates all seasonal bands)
- **NOAA SPC** — `spc.noaa.gov` — tornado/severe weather outlooks (US Midwest/South)
- **JMA RSMC Tokyo** — `jma.go.jp` — NW Pacific typhoon analysis bulletins
- **JTWC** — `metoc.navy.mil/jtwc` — joint cyclone tracking
- **IMD RSMC New Delhi** — `mausam.imd.gov.in` — North Indian Ocean cyclone bulletins, SW + NE monsoon outlooks
- **Météo-France La Réunion** — `meteofrance.re` — SW Indian Ocean cyclone bulletins
- **BoM (Australia)** — `bom.gov.au` — S Pacific cyclone, climate outlooks
- **Fiji RSMC** — `met.gov.fj` — S Pacific cyclone bulletins
- **ECMWF** — `ecmwf.int` — European weather, ERA5 reanalysis, sub-seasonal forecasts
- **DWD / UK Met Office** — `dwd.de` / `metoffice.gov.uk` — European windstorm forecasts
- **Copernicus EFFIS** — `effis.jrc.ec.europa.eu` — European fire danger index, daily
- **Copernicus EFAS / GloFAS** — `efas.eu` / `globalfloods.eu` — European + Global flood awareness
- **NIFC** — `nifc.gov` — US wildfire situation reports
- **NRCan CWFIS** — `cwfis.cfs.nrcan.gc.ca` — Canadian wildfire information
- **FAO Locust Hub / DLIS** — `fao.org/ag/locusts` — desert locust monitoring (Horn of Africa, S Asia)
- **NASA EOSDIS** — `earthdata.nasa.gov` — fire detection, real-time

### Maritime / chokepoints / strikes
- **UKMTO** — `ukmto.org` — maritime incident reports for Gulf and Red Sea
- **MARAD MSCI** — `maritime.dot.gov/msci` — US Maritime Administration security advisories
- **EUNAVFOR Aspides** — Red Sea / Bab el-Mandeb mission reports
- **IMO** — `imo.org` — formal navigation statements
- **IMF PortWatch** — `portwatch.imf.org` — daily port-call disruption index for global chokepoints (Suez, Bab-el-Mandeb, Hormuz, Malacca, Panama)
- **Port-authority bulletins** — Port of Houston, Port of Rotterdam, Singapore MPA, Panama Canal Authority, Suez Canal Authority — official traffic notices

### Geopolitical / sanctions
- **OFAC / US Treasury** — `home.treasury.gov/policy-issues/financial-sanctions` — sanctions designations
- **UK FCDO** — `gov.uk` — sanctions and foreign-policy statements
- **EU EEAS** — `eeas.europa.eu` — High Representative statements, sanctions
- **UN Security Council** — `un.org/securitycouncil` — formal resolutions and sanctions lists

### Upstream trackers (ingested, not scraped)
- **hormuz-tracker** — `resilienceengineers.github.io/hormuz-daily-brief/` — daily snapshot of Hormuz threat level + watchlist
- **fm-tracker** — `resilienceengineers.github.io/fm-tracker/` — force-majeure declarations across global supply chains

---

## Tier 2 — Specialized data and analysis with operational track record

Subscription or open commercial sources with direct measurement capability. Counts as **Hard** signal when data is quantitative and verifiable; otherwise **Medium**.

- **ACLED** — `acleddata.com/api` — geocoded political violence and protest events, weekly refresh (attribution required, open)
- **GDELT 2.0** — `gdeltproject.org` — global event database, CAMEO-coded, 15-min refresh (open)
- **UCDP** — `ucdp.uu.se` — Uppsala conflict data, academic-grade
- **Kpler** — `kpler.com` — vessel-level energy flow data
- **Vortexa** — `vortexa.com` — energy cargo flow analytics
- **Lloyd's List Intelligence** — `lloydslistintelligence.com` — tanker and shipping intel
- **IMB Piracy Reporting Centre** — `icc-ccs.org/icc/imb` — live alerts, open RSS
- **S&P Global Platts** — `spglobal.com/commodityinsights` — energy pricing and flow
- **Argus Media** — `argusmedia.com` — energy markets
- **EM-DAT (CRED)** — `emdat.be` — international disaster database for retrospective calibration
- **Munich Re NatCatSERVICE** — `munichre.com/natcatservice` — cat-event statistics

---

## Tier 3 — Analytical institutions with rigorous track record

Slower than Tier 1–2, deepest analysis. Counts as **Medium** signal; can elevate to **Hard** when citing Tier 1 sources.

- **International Crisis Group (ICG)** — `crisisgroup.org`
- **Institute for the Study of War (ISW)** — `understandingwar.org`
- **IISS** — `iiss.org`
- **Chatham House** — `chathamhouse.org`
- **RUSI** — `rusi.org`
- **CSIS** — `csis.org`
- **Atlantic Council** — `atlanticcouncil.org`
- **Brookings** — `brookings.edu`
- **Carnegie** — `carnegieendowment.org`
- **Oxford Institute for Energy Studies (OIES)** — `oxfordenergy.org`
- **Bourse & Bazaar Foundation** — Iran economy and sanctions
- **Amwaj.media** — Iran-focused, well-sourced

---

## Tier 4 — Commercial analysts and columnists with track record

Individuals and desks with strong calibration history. Counts as **Soft** signal unless citing Tier 1.

- **John Kemp** — independent energy columnist; newsletter
- **Helima Croft** — RBC Capital Markets, Iran/MENA
- **Anas Alhajji** — independent energy economist
- **Eurasia Group** — `eurasiagroup.net`
- **Energy Intelligence** — `energyintel.com`
- **Trafigura / Vitol / Gunvor public commentary** — physical traders with skin in the game

---

## Tier 5 — News organizations and regional press

Wire services and reputable papers, weighted by track record on the beat. Confirming, not first-detecting.

### Wire services
- **Reuters** — `reuters.com`
- **AP** — `apnews.com`
- **AFP** — `afp.com`
- **Bloomberg** — `bloomberg.com`

### Western newspapers
- **Financial Times** — `ft.com`
- **Wall Street Journal** — `wsj.com`
- **The Economist** — `economist.com`
- **The Guardian** — `theguardian.com`

### Regional (with editorial-line caveat)
- **Al Jazeera** — `aljazeera.com` — Qatari editorial line
- **The National (UAE)** — `thenationalnews.com` — Emirati editorial line
- **Iran International** — `iranintl.com` — diaspora opposition editorial line
- **Times of Israel** / **Haaretz** — Israeli mainstream / liberal-left
- **IRNA / Tasnim / Fars / Tehran Times** — Iranian state outlets, read for the official line
- **Asharq Al-Awsat** — pan-Arab, Saudi-owned

---

## Tier 6 — Excluded by default (NOISE unless triangulated)

- Anonymous OSINT accounts on X/Telegram
- Op-eds and speculation pieces
- "Sources say" or "sources told us" without attribution
- Reposts of state media without independent confirmation
- AI-generated summaries
- Influencer commentary
- Forum/Reddit/Discord posts

A Tier-6 lead enters the calendar only after ≥1 Tier 1–3 corroboration.

---

## Source weighting log

When a source produces a high-quality early signal or a costly false alarm, log here with date and adjustment. Mirrored to `data/sources.json.reliability_score`.

| Date | Source | Event | Adjustment |
|------|--------|-------|-----------|
| 2026-05-13 | (initial) | Tracker launch | Tiers as listed |

---

## Conflict-of-interest disclosure

Tier 4 sources have commercial positions in commodity markets. Reported as analytical input, not advocacy. State outlets (Tehran Times etc.) are reported as **positions of the state**, never as factual reporting.
