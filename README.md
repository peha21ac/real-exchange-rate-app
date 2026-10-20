# Real Exchange Rate Explorer

A Streamlit app that pulls monthly CPI and exchange-rate data from the IMF SDMX 3.0 API and computes a real exchange rate (RER) index for any two IMF countries or the Euro area.

## Definitions

- `S(t)`: units of Country 2 currency per 1 unit of Country 1 currency.
- `P1(t)`, `P2(t)`: monthly CPI (all items) of Country 1 and Country 2.
- `RER(t) = S(t) × P1(t) / P2(t)`
- `RER*`: average of `RER(t)` over valid months in the selected start/end window (recomputed whenever the dates change).
- `Real Index(t) = 100 × RER(t) / RER*`
- Nominal `S(t)` is plotted in actual currency units (not normalized).

The IMF reports exchange rates as local currency units per USD (`XDC_USD`). The app converts them:

```
S(t) = (Country 2 per USD) / (Country 1 per USD)
```

For the United States the local-per-USD rate is set to 1.

## IMF series used

| Data | Dataflow | Key |
|------|----------|-----|
| CPI (monthly index) | `IMF.STA/CPI` | `{ISO3}.CPI._T.IX.M` |
| Exchange rate (period average) | `IMF.STA/ER` | `{ISO3}.XDC_USD.PA_RT.M` |

Base URL: `https://api.imf.org/external/sdmx/3.0`. The Euro area code is `G163`. Data are requested from January 1976 where available.

## Features

- Choose Country 1 and Country 2 (IMF countries plus Euro area).
- Select start and end month; `RER*` updates automatically.
- Chart mode: **Real**, **Nominal**, or **Both** (Both uses separate y-axes).
- CSV download of every observation and calculation in the selected sample (CPIs, local-per-USD rates, S, RER, RER*, Real Index, valid-month flag).

## Run locally (Python 3.12)

```bash
python3.12 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

## Deploy from GitHub

1. Push `app.py`, `requirements.txt`, and `README.md` to a GitHub repository.
2. Go to [Streamlit Community Cloud](https://share.streamlit.io), click **New app**, and select the repository, branch, and `app.py`.
3. Under **Advanced settings**, choose Python 3.12, then deploy.

## Data caveats

- IMF coverage varies by country and period; some series start later than 1976 or have gaps.
- A month is "valid" only if both CPIs and both exchange rates exist. Only valid months enter `RER*` and the Real Index. Nominal `S(t)` is shown wherever both exchange rates exist.
- Euro-area exchange-rate and CPI history depends on what the IMF publishes for `G163`.
- Index levels are rebased arbitrarily in each country's CPI, so only changes in the Real Index are meaningful, not its absolute level relative to other pairs.
- Responses are cached for 12 hours.

## Troubleshooting

If a series fails to load, the app shows a warning with the reason. The API's response format and dataflow versions can change; the data-access code is isolated in `fetch_series()` and `_parse_sdmx_json()` in `app.py`, so adjust the dataflow ID, `Accept` header, or parser there if the IMF updates its API.
