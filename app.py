"""
Real Exchange Rate Explorer (Streamlit)

S(t)    = units of Country 2 currency per 1 unit of Country 1 currency
RER(t)  = S(t) * P1(t) / P2(t)
RER*    = mean of RER(t) over valid months in the selected sample
RealIdx = 100 * RER(t) / RER*

Data: IMF SDMX 3.0 API (https://api.imf.org/external/sdmx/3.0)
  CPI key:           {ISO3}.CPI._T.IX.M
  Exchange-rate key: {ISO3}.XDC_USD.PA_RT.M   (local currency units per USD)
Euro area code: G163
"""

from __future__ import annotations

import re
from typing import Optional

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
from plotly.subplots import make_subplots

BASE_URL = "https://api.imf.org/external/sdmx/3.0"
START_PERIOD = "1976-01"
EURO_AREA = "G163"

ACCEPT_HEADERS = [
    "application/vnd.sdmx.data+json;version=2.0.0",
    "application/vnd.sdmx.data+json",
    "application/json",
]

# Built-in fallback list (ISO3 -> name). Coverage per country/series varies in the IMF data.
COUNTRIES_RAW = """
AFG:Afghanistan,ALB:Albania,DZA:Algeria,AGO:Angola,ATG:Antigua and Barbuda,ARG:Argentina,ARM:Armenia,
ABW:Aruba,AUS:Australia,AUT:Austria,AZE:Azerbaijan,BHS:Bahamas,BHR:Bahrain,BGD:Bangladesh,BRB:Barbados,
BLR:Belarus,BEL:Belgium,BLZ:Belize,BEN:Benin,BTN:Bhutan,BOL:Bolivia,BIH:Bosnia and Herzegovina,
BWA:Botswana,BRA:Brazil,BRN:Brunei Darussalam,BGR:Bulgaria,BFA:Burkina Faso,BDI:Burundi,CPV:Cabo Verde,
KHM:Cambodia,CMR:Cameroon,CAN:Canada,CAF:Central African Republic,TCD:Chad,CHL:Chile,CHN:China (P.R. Mainland),
COL:Colombia,COM:Comoros,COD:Congo (Dem. Rep.),COG:Congo (Rep.),CRI:Costa Rica,CIV:Cote d'Ivoire,HRV:Croatia,
CYP:Cyprus,CZE:Czech Republic,DNK:Denmark,DJI:Djibouti,DMA:Dominica,DOM:Dominican Republic,ECU:Ecuador,
EGY:Egypt,SLV:El Salvador,GNQ:Equatorial Guinea,ERI:Eritrea,EST:Estonia,SWZ:Eswatini,ETH:Ethiopia,FJI:Fiji,
FIN:Finland,FRA:France,GAB:Gabon,GMB:Gambia,GEO:Georgia,DEU:Germany,GHA:Ghana,GRC:Greece,GRD:Grenada,
GTM:Guatemala,GIN:Guinea,GNB:Guinea-Bissau,GUY:Guyana,HTI:Haiti,HND:Honduras,HKG:Hong Kong SAR,HUN:Hungary,
ISL:Iceland,IND:India,IDN:Indonesia,IRN:Iran,IRQ:Iraq,IRL:Ireland,ISR:Israel,ITA:Italy,JAM:Jamaica,JPN:Japan,
JOR:Jordan,KAZ:Kazakhstan,KEN:Kenya,KIR:Kiribati,KOR:Korea (Rep.),KWT:Kuwait,KGZ:Kyrgyz Republic,LAO:Lao P.D.R.,
LVA:Latvia,LBN:Lebanon,LSO:Lesotho,LBR:Liberia,LBY:Libya,LTU:Lithuania,LUX:Luxembourg,MAC:Macao SAR,
MDG:Madagascar,MWI:Malawi,MYS:Malaysia,MDV:Maldives,MLI:Mali,MLT:Malta,MHL:Marshall Islands,MRT:Mauritania,
MUS:Mauritius,MEX:Mexico,FSM:Micronesia,MDA:Moldova,MNG:Mongolia,MNE:Montenegro,MAR:Morocco,MOZ:Mozambique,
MMR:Myanmar,NAM:Namibia,NRU:Nauru,NPL:Nepal,NLD:Netherlands,NZL:New Zealand,NIC:Nicaragua,NER:Niger,NGA:Nigeria,
MKD:North Macedonia,NOR:Norway,OMN:Oman,PAK:Pakistan,PLW:Palau,PAN:Panama,PNG:Papua New Guinea,PRY:Paraguay,
PER:Peru,PHL:Philippines,POL:Poland,PRT:Portugal,QAT:Qatar,ROU:Romania,RUS:Russian Federation,RWA:Rwanda,
WSM:Samoa,SMR:San Marino,STP:Sao Tome and Principe,SAU:Saudi Arabia,SEN:Senegal,SRB:Serbia,SYC:Seychelles,
SLE:Sierra Leone,SGP:Singapore,SVK:Slovak Republic,SVN:Slovenia,SLB:Solomon Islands,SOM:Somalia,ZAF:South Africa,
SSD:South Sudan,ESP:Spain,LKA:Sri Lanka,KNA:St. Kitts and Nevis,LCA:St. Lucia,VCT:St. Vincent and the Grenadines,
SDN:Sudan,SUR:Suriname,SWE:Sweden,CHE:Switzerland,SYR:Syria,TWN:Taiwan Province of China,TJK:Tajikistan,
TZA:Tanzania,THA:Thailand,TLS:Timor-Leste,TGO:Togo,TON:Tonga,TTO:Trinidad and Tobago,TUN:Tunisia,TUR:Turkiye,
TKM:Turkmenistan,TUV:Tuvalu,UGA:Uganda,UKR:Ukraine,ARE:United Arab Emirates,GBR:United Kingdom,USA:United States,
URY:Uruguay,UZB:Uzbekistan,VUT:Vanuatu,VEN:Venezuela,VNM:Vietnam,YEM:Yemen,ZMB:Zambia,ZWE:Zimbabwe,
G163:Euro Area
"""


def builtin_countries() -> dict[str, str]:
    out = {}
    for item in COUNTRIES_RAW.replace("\n", "").split(","):
        item = item.strip()
        if ":" in item:
            code, name = item.split(":", 1)
            out[code.strip()] = name.strip()
    return out


# ----------------------------------------------------------------------------
# IMF data access
# ----------------------------------------------------------------------------
def _parse_period(label: str) -> Optional[pd.Timestamp]:
    """Convert IMF monthly labels such as '1976-M01' or '1976-01' to month-start timestamps."""
    m = re.match(r"^(\d{4})[-]?M?(\d{1,2})$", str(label).strip())
    if not m:
        return None
    year, month = int(m.group(1)), int(m.group(2))
    if not 1 <= month <= 12:
        return None
    return pd.Timestamp(year=year, month=month, day=1)


def _parse_sdmx_json(payload: dict) -> pd.Series:
    """Parse SDMX-JSON (v1 or v2) into a monthly pandas Series. Returns empty Series if none."""
    data = payload.get("data", payload)
    structures = data.get("structures") or ([data["structure"]] if "structure" in data else [])
    datasets = data.get("dataSets", [])
    if not structures or not datasets:
        return pd.Series(dtype=float)

    obs_dims = structures[0]["dimensions"]["observation"]
    time_dim = next((d for d in obs_dims if d.get("id") == "TIME_PERIOD"), obs_dims[0])
    time_values = [v.get("id") or v.get("value") for v in time_dim["values"]]

    series_dict = datasets[0].get("series", {})
    best: dict[str, list] = {}
    for _, s in series_dict.items():
        obs = s.get("observations", {})
        if len(obs) > len(best):
            best = obs
    records = {}
    for idx, val in best.items():
        try:
            ts = _parse_period(time_values[int(idx)])
            v = val[0] if isinstance(val, list) else val
            if ts is not None and v is not None:
                records[ts] = float(v)
        except (ValueError, IndexError, TypeError):
            continue
    return pd.Series(records, dtype=float).sort_index()


@st.cache_data(ttl=60 * 60 * 12, show_spinner=False)
def fetch_series(dataflow: str, key: str) -> tuple[pd.Series, str]:
    """
    Fetch one monthly series from the IMF API.
    Returns (series, message). The series is empty when nothing could be retrieved.
    """
    url = f"{BASE_URL}/data/dataflow/IMF.STA/{dataflow}/+/{key}"
    last_error = ""
    for params in ({"c[TIME_PERIOD]": f"ge:{START_PERIOD}"}, {}):
        for accept in ACCEPT_HEADERS:
            try:
                r = requests.get(url, params=params, headers={"Accept": accept}, timeout=60)
                if r.status_code == 404:
                    return pd.Series(dtype=float), "No data found (404)."
                r.raise_for_status()
                s = _parse_sdmx_json(r.json())
                if not s.empty:
                    return s[s.index >= pd.Timestamp(START_PERIOD + "-01")], "ok"
                last_error = "Empty response."
            except (requests.RequestException, ValueError, KeyError) as e:
                last_error = f"{type(e).__name__}: {e}"
    return pd.Series(dtype=float), last_error or "Unknown error."


@st.cache_data(ttl=60 * 60 * 24, show_spinner=False)
def load_country_list() -> dict[str, str]:
    """Try the IMF country codelist; fall back to the built-in list."""
    countries = builtin_countries()
    try:
        r = requests.get(
            f"{BASE_URL}/structure/codelist/IMF/CL_COUNTRY/+",
            headers={"Accept": "application/json"},
            timeout=30,
        )
        r.raise_for_status()
        js = r.json()
        codelists = js.get("data", {}).get("codelists", [])
        if codelists:
            live = {}
            for c in codelists[0].get("codes", []):
                code = c.get("id", "")
                name = c.get("name") or (c.get("names") or {}).get("en", "")
                if re.fullmatch(r"[A-Z]{3}", code) and name:
                    live[code] = name
            # Only trust live names for codes we already know to be real countries
            for code in countries:
                if code in live:
                    countries[code] = live[code]
    except Exception:
        pass
    return countries


def get_local_per_usd(iso3: str) -> tuple[pd.Series, str]:
    """Local currency units per USD, monthly period average."""
    s, msg = fetch_series("ER", f"{iso3}.XDC_USD.PA_RT.M")
    if s.empty and iso3 == "USA":
        return pd.Series(dtype=float), "US has no XDC_USD series; handled as 1.0."
    return s, msg


# ----------------------------------------------------------------------------
# Calculations
# ----------------------------------------------------------------------------
def build_dataset(c1: str, c2: str) -> tuple[pd.DataFrame, list[str]]:
    """Return merged monthly dataset and list of warnings."""
    warnings: list[str] = []

    p1, m = fetch_series("CPI", f"{c1}.CPI._T.IX.M")
    if p1.empty:
        warnings.append(f"CPI for {c1}: {m}")
    p2, m = fetch_series("CPI", f"{c2}.CPI._T.IX.M")
    if p2.empty:
        warnings.append(f"CPI for {c2}: {m}")

    e1, m = get_local_per_usd(c1)
    if e1.empty and c1 != "USA":
        warnings.append(f"Exchange rate for {c1}: {m}")
    e2, m = get_local_per_usd(c2)
    if e2.empty and c2 != "USA":
        warnings.append(f"Exchange rate for {c2}: {m}")

    idx = pd.date_range(START_PERIOD + "-01", pd.Timestamp.today().to_period("M").to_timestamp(), freq="MS")
    df = pd.DataFrame(index=idx)
    df["P1"] = p1
    df["P2"] = p2
    # USA: local currency per USD is exactly 1.
    df["E1_LC_per_USD"] = 1.0 if c1 == "USA" else e1
    df["E2_LC_per_USD"] = 1.0 if c2 == "USA" else e2

    # S = units of C2 per 1 unit of C1 = (C2 per USD) / (C1 per USD)
    df["S"] = df["E2_LC_per_USD"] / df["E1_LC_per_USD"]
    df["RER"] = df["S"] * df["P1"] / df["P2"]
    df["valid"] = df[["P1", "P2", "S", "RER"]].notna().all(axis=1) & (df["P2"] != 0)
    df.loc[~df["valid"], "RER"] = float("nan")

    df = df.dropna(how="all", subset=["P1", "P2", "E1_LC_per_USD", "E2_LC_per_USD"])
    df.index.name = "date"
    return df, warnings


def apply_sample(df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> tuple[pd.DataFrame, float]:
    """Slice to sample and compute RER* and the Real Index within it."""
    sample = df.loc[(df.index >= start) & (df.index <= end)].copy()
    valid_rer = sample.loc[sample["valid"], "RER"]
    rer_star = float(valid_rer.mean()) if not valid_rer.empty else float("nan")
    sample["RER_star"] = rer_star
    sample["Real_Index"] = 100 * sample["RER"] / rer_star
    return sample, rer_star


# ----------------------------------------------------------------------------
# Plotting
# ----------------------------------------------------------------------------
def make_chart(sample: pd.DataFrame, mode: str, c1_label: str, c2_label: str) -> go.Figure:
    s_title = f"Nominal S(t): {c2_label} per 1 {c1_label}"
    real_title = "Real Index (100 = sample-average RER*)"
    plot_df = sample[sample["valid"]]

    if mode == "Both":
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        fig.add_trace(
            go.Scatter(x=plot_df.index, y=plot_df["Real_Index"], name="Real Index", mode="lines"),
            secondary_y=False,
        )
        fig.add_trace(
            go.Scatter(x=plot_df.index, y=plot_df["S"], name="Nominal S(t)", mode="lines"),
            secondary_y=True,
        )
        fig.update_yaxes(title_text=real_title, secondary_y=False)
        fig.update_yaxes(title_text=s_title, secondary_y=True)
        fig.add_hline(y=100, line_dash="dot", line_color="gray", secondary_y=False)
    else:
        fig = go.Figure()
        if mode == "Real":
            fig.add_trace(go.Scatter(x=plot_df.index, y=plot_df["Real_Index"], name="Real Index", mode="lines"))
            fig.add_hline(y=100, line_dash="dot", line_color="gray")
            fig.update_yaxes(title_text=real_title)
        else:
            # Nominal S(t) is shown for every month where the exchange rates exist,
            # in actual currency units (not normalized).
            nom = sample["S"].dropna()
            fig.add_trace(go.Scatter(x=nom.index, y=nom.values, name="Nominal S(t)", mode="lines"))
            fig.update_yaxes(title_text=s_title)

    fig.update_xaxes(title_text="Month")
    fig.update_layout(
        hovermode="x unified",
        height=520,
        margin=dict(l=20, r=20, t=40, b=20),
        legend=dict(orientation="h", y=1.08),
    )
    return fig


# ----------------------------------------------------------------------------
# UI
# ----------------------------------------------------------------------------
def main() -> None:
    st.set_page_config(page_title="Real Exchange Rate Explorer", layout="wide")
    st.title("Real Exchange Rate Explorer")
    st.caption(
        "Source: IMF (monthly CPI and period-average exchange rates). "
        "S(t) = units of Country 2 currency per 1 unit of Country 1 currency; "
        "RER(t) = S(t) × P1(t) / P2(t)."
    )

    countries = load_country_list()
    names = {code: f"{name} ({code})" for code, name in countries.items()}
    codes = sorted(countries, key=lambda c: countries[c])

    col_a, col_b = st.columns(2)
    with col_a:
        c1 = st.selectbox(
            "Country 1 (base currency)", codes, index=codes.index("USA"), format_func=lambda c: names[c]
        )
    with col_b:
        c2 = st.selectbox(
            "Country 2 (quote currency)", codes, index=codes.index(EURO_AREA), format_func=lambda c: names[c]
        )

    if c1 == c2:
        st.warning("Please choose two different countries.")
        st.stop()

    with st.spinner("Retrieving IMF data..."):
        df, warnings = build_dataset(c1, c2)

    for w in warnings:
        st.warning(w)

    if df.empty or not df["valid"].any():
        st.error(
            "No months have complete data (both CPIs and both exchange rates) for this pair. "
            "Try different countries; IMF coverage varies."
        )
        st.stop()

    valid_months = df.index[df["valid"]]
    months = list(df.index)
    labels = [d.strftime("%Y-%m") for d in months]
    default_start = labels.index(valid_months[0].strftime("%Y-%m"))
    default_end = labels.index(valid_months[-1].strftime("%Y-%m"))

    start_label, end_label = st.select_slider(
        "Sample period (start and end month)",
        options=labels,
        value=(labels[default_start], labels[default_end]),
    )
    start = pd.Timestamp(start_label + "-01")
    end = pd.Timestamp(end_label + "-01")

    sample, rer_star = apply_sample(df, start, end)
    n_valid = int(sample["valid"].sum())
    if n_valid == 0:
        st.error("No valid months in the selected sample. Widen the period.")
        st.stop()

    c1_label, c2_label = countries[c1], countries[c2]
    m1, m2, m3 = st.columns(3)
    m1.metric("RER* (sample average)", f"{rer_star:,.4f}")
    m2.metric("Valid months", f"{n_valid}")
    m3.metric("Months in sample window", f"{len(sample)}")

    mode = st.radio("Display", ["Real", "Nominal", "Both"], horizontal=True)
    st.plotly_chart(make_chart(sample, mode, c1_label, c2_label), use_container_width=True)

    st.subheader("Observations and calculations")
    out = sample.reset_index().rename(
        columns={
            "P1": f"P1_CPI_{c1}",
            "P2": f"P2_CPI_{c2}",
            "E1_LC_per_USD": f"{c1}_local_per_USD",
            "E2_LC_per_USD": f"{c2}_local_per_USD",
            "S": "S_C2_per_C1",
            "RER": "RER",
            "RER_star": "RER_star",
            "Real_Index": "Real_Index",
            "valid": "valid_month",
        }
    )
    out["date"] = out["date"].dt.strftime("%Y-%m")
    st.dataframe(out, use_container_width=True, height=300)
    st.download_button(
        "Download CSV",
        data=out.to_csv(index=False).encode("utf-8"),
        file_name=f"rer_{c1}_{c2}_{start_label}_{end_label}.csv",
        mime="text/csv",
    )

    st.caption(
        "RER* is recomputed from valid months inside the selected sample (months where both CPIs and both "
        "exchange rates are available). Nominal S(t) is plotted in actual currency units."
    )


if __name__ == "__main__":
    main()
