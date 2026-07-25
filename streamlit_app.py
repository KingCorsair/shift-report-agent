"""Production Shift Report Agent — Streamlit port of shift_report_ui.html.

Turns an end-of-shift machine log (CSV) into a one-page shift report with
flagged exceptions, following the rules in AGENT.md.
"""

import io
import statistics
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

REQUIRED = [
    "shift_id",
    "shift_start",
    "line",
    "machine_id",
    "units_produced",
    "defect_count",
    "downtime_minutes",
]
NUMERIC = ["units_produced", "defect_count", "downtime_minutes"]

SAMPLE_PATH = Path(__file__).parent / "data" / "shift_log.csv"


# ---- Parsing & validation ----------------------------------------------------

def load_records(csv_bytes: bytes) -> pd.DataFrame:
    df = pd.read_csv(io.BytesIO(csv_bytes))
    df.columns = [c.strip() for c in df.columns]
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ValueError("Missing column(s): " + ", ".join(missing))
    if df.empty:
        raise ValueError("Log has no data rows.")
    for col in NUMERIC:
        df[col] = pd.to_numeric(df[col], errors="coerce")
        if df[col].isna().any():
            row = int(df[df[col].isna()].index[0]) + 2
            raise ValueError(f'Row {row}: "{col}" is not a number.')
    for col in ["shift_id", "shift_start", "line", "machine_id"]:
        df[col] = df[col].astype(str).str.strip()
    return df


# ---- Aggregation -------------------------------------------------------------

def summarize(recs: pd.DataFrame) -> dict:
    units = int(recs["units_produced"].sum())
    defects = int(recs["defect_count"].sum())
    downtime = int(recs["downtime_minutes"].sum())
    total = units + defects
    return {
        "units": units,
        "defects": defects,
        "downtime": downtime,
        "defect_rate": defects / total if total > 0 else 0.0,
        "machines": len(recs),
        "line_count": recs["line"].nunique(),
        "lines": recs.groupby("line")["defect_count"].sum().to_dict(),
        "by_machine": {r.machine_id: r for r in recs.itertuples()},
    }


# ---- Exception rules (see AGENT.md) ------------------------------------------

def find_exceptions(recs: pd.DataFrame, cur: dict, prior: dict | None) -> list[dict]:
    out = []
    med_def = statistics.median(recs["defect_count"]) if len(recs) else 0

    for r in recs.itertuples():
        p = prior["by_machine"].get(r.machine_id) if prior else None

        # Downtime spike
        if r.downtime_minutes > 60 or (
            p and p.downtime_minutes > 0 and r.downtime_minutes > 3 * p.downtime_minutes
        ):
            crit = r.downtime_minutes > 90
            vs = f" vs {int(p.downtime_minutes)} last shift" if p else ""
            out.append({
                "sev": "critical" if crit else "warning",
                "who": f"{r.machine_id} · {r.line}",
                "kind": "Downtime",
                "msg": f"Stopped **{int(r.downtime_minutes)} min**{vs}. "
                       "Check the machine before the next run.",
                "sort": 0 if crit else 2,
            })

        # Defect spike
        share = r.defect_count / cur["defects"] if cur["defects"] > 0 else 0
        if (med_def > 0 and r.defect_count > 3 * med_def) or (
            p and p.defect_count > 0 and r.defect_count > 3 * p.defect_count
        ):
            crit = share > 0.40
            vs = f" vs {int(p.defect_count)} last shift" if p else ""
            out.append({
                "sev": "critical" if crit else "warning",
                "who": f"{r.machine_id} · {r.line}",
                "kind": "Defects",
                "msg": f"Produced **{int(r.defect_count)} defects**{vs} — "
                       f"**{round(share * 100)}%** of the shift's total. "
                       "Inspect tooling/material.",
                "sort": 0 if crit else 1,
            })

        # Output drop
        if p and p.units_produced > 0:
            drop = (p.units_produced - r.units_produced) / p.units_produced
            if drop > 0.30:
                out.append({
                    "sev": "warning",
                    "who": f"{r.machine_id} · {r.line}",
                    "kind": "Output",
                    "msg": f"Output fell **{round(drop * 100)}%** — "
                           f"**{int(r.units_produced)}** units vs "
                           f"{int(p.units_produced)} last shift.",
                    "sort": 3,
                })

    # Shift-wide defect rate
    if cur["defect_rate"] > 0.03:
        was = f" (was {prior['defect_rate'] * 100:.1f}% last shift)" if prior else ""
        out.append({
            "sev": "warning",
            "who": "Whole shift",
            "kind": "Defect rate",
            "msg": f"Shift defect rate **{cur['defect_rate'] * 100:.1f}%** "
                   f"is above the 3% line{was}.",
            "sort": 2.5,
        })

    return sorted(out, key=lambda e: e["sort"])


# ---- Text helpers ------------------------------------------------------------

def fmt(n: float) -> str:
    return f"{round(n):,}"


def bottom_line(cur: dict, prior: dict | None, exceptions: list[dict]) -> str:
    crit = [e for e in exceptions if e["sev"] == "critical"]
    if crit:
        names = " and ".join(e["who"].split(" · ")[0] for e in crit)
        issue = "critical issues" if len(crit) > 1 else "a critical issue"
        clear = "them" if len(crit) > 1 else "it"
        if prior:
            verb = "slipped" if cur["units"] < prior["units"] else "held"
            tail = f"Overall output {verb} at {fmt(cur['units'])} units."
        else:
            tail = f"Output was {fmt(cur['units'])} units."
        return (f"**Attention needed.** {names} drove {issue} this shift — "
                f"clear {clear} before the next run. {tail}")
    if exceptions:
        s = "s" if len(exceptions) > 1 else ""
        return (f"Shift produced **{fmt(cur['units'])} units** with "
                f"{len(exceptions)} item{s} to watch, but nothing critical. "
                "Review the exceptions above.")
    return (f"Clean shift — **{fmt(cur['units'])} units** at a "
            f"{cur['defect_rate'] * 100:.1f}% defect rate, no exceptions flagged.")


def build_text_report(cur_shift, prior_shift, cur, prior, exceptions,
                      date_str, period) -> str:
    rule = "=" * 58
    L = [rule, "PRODUCTION SHIFT REPORT", f"{period} · {cur_shift['id']}",
         f"{date_str} · {cur['line_count']} lines · {cur['machines']} machines",
         rule, ""]

    def dl(cur_v, prev_v, unit):
        if prev_v is None:
            return "(no prior shift)"
        d = cur_v - prev_v
        pct = (d / prev_v * 100) if prev_v != 0 else 0
        return f"{'up' if d >= 0 else 'down'} {fmt(abs(d))}{unit} ({pct:+.1f}%) vs prior"

    p = prior or {}
    L.append("AT A GLANCE")
    L.append(f"  Units produced   {fmt(cur['units']):>8}   {dl(cur['units'], p.get('units'), '')}")
    L.append(f"  Downtime         {fmt(cur['downtime']) + ' min':>8}   {dl(cur['downtime'], p.get('downtime'), ' min')}")
    L.append(f"  Defects          {fmt(cur['defects']):>8}   {dl(cur['defects'], p.get('defects'), '')}")
    rate_note = f"was {prior['defect_rate'] * 100:.1f}%" if prior else "(no prior shift)"
    rate_val = f"{cur['defect_rate'] * 100:.1f}%"
    L.append(f"  Defect rate      {rate_val:>8}   {rate_note}")
    L.append("")
    L.append("DEFECTS BY LINE")
    for line in sorted(cur["lines"]):
        pv = prior["lines"].get(line) if prior else None
        extra = f"   (prior {fmt(pv)})" if pv is not None else ""
        L.append(f"  {line:<12} {fmt(cur['lines'][line]):>4}{extra}")
    L.append("")
    L.append("EXCEPTIONS")
    if not exceptions:
        L.append("  None — shift ran within normal range.")
    else:
        for e in exceptions:
            L.append(f"  [{e['sev'].upper()}] {e['who']}")
            L.append(f"      {e['msg'].replace('**', '')}")
    L.append("")
    L.append("BOTTOM LINE")
    L.append("  " + bottom_line(cur, prior, exceptions).replace("**", ""))
    L.append("")
    L.append(rule)
    L.append("Generated by Shift Report Agent")
    return "\n".join(L)


# ---- UI ----------------------------------------------------------------------

st.set_page_config(page_title="Shift Report Agent", page_icon="🏭", layout="centered")

st.caption("FABRICATION · END OF SHIFT")
st.title("Production Shift Report Agent")
st.write(
    "Upload a machine-output log and get a one-page shift report — units, "
    "downtime, and defects by line, measured against the prior shift, with "
    "anything abnormal flagged."
)

uploaded = st.file_uploader(
    "Shift log CSV — one row per machine per shift", type=["csv"]
)
use_sample = st.button("Load sample data")

if "csv_bytes" not in st.session_state:
    st.session_state.csv_bytes = None
    st.session_state.csv_name = None

if uploaded is not None:
    st.session_state.csv_bytes = uploaded.getvalue()
    st.session_state.csv_name = uploaded.name
elif use_sample:
    st.session_state.csv_bytes = SAMPLE_PATH.read_bytes()
    st.session_state.csv_name = "shift_log.csv (sample)"

if st.session_state.csv_bytes is None:
    st.info("Upload a CSV or load the sample data to generate a report.")
    st.stop()

st.caption(f"Loaded: `{st.session_state.csv_name}`")

try:
    df = load_records(st.session_state.csv_bytes)
except ValueError as err:
    st.error(str(err))
    st.stop()

# Latest shift (by shift_start) is current; the one before it is prior.
shifts = (
    df.groupby("shift_id")["shift_start"].min().sort_values().index.tolist()
)
cur_id = shifts[-1]
prior_id = shifts[-2] if len(shifts) > 1 else None

cur_recs = df[df["shift_id"] == cur_id]
cur = summarize(cur_recs)
prior = summarize(df[df["shift_id"] == prior_id]) if prior_id else None
exceptions = find_exceptions(cur_recs, cur, prior)

start_raw = cur_recs["shift_start"].iloc[0]
try:
    d = datetime.fromisoformat(start_raw)
    date_str = f"{d:%A}, {d:%B} {d.day}, {d.year}"
except ValueError:
    date_str = start_raw
period = ("Night shift" if "night" in cur_id.lower()
          else "Day shift" if "day" in cur_id.lower() else "Shift")

st.divider()
st.caption(cur_id.upper())
st.header(f"{period} report")
meta = f"{date_str} · {cur['line_count']} lines · {cur['machines']} machines"
if prior_id:
    meta += f" · vs prior shift {prior_id}"
else:
    meta += " · no prior shift in this log"
st.caption(meta)

# At a glance
st.subheader("At a glance")
c1, c2, c3, c4 = st.columns(4)
p = prior or {}
c1.metric("Units produced", fmt(cur["units"]),
          delta=cur["units"] - p["units"] if prior else None)
c2.metric("Downtime", f"{fmt(cur['downtime'])} min",
          delta=f"{cur['downtime'] - p['downtime']} min" if prior else None,
          delta_color="inverse")
c3.metric("Defects", fmt(cur["defects"]),
          delta=cur["defects"] - p["defects"] if prior else None,
          delta_color="inverse")
c4.metric("Defect rate", f"{cur['defect_rate'] * 100:.1f}%",
          delta=f"{(cur['defect_rate'] - p['defect_rate']) * 100:+.1f} pts" if prior else None,
          delta_color="inverse")

# Defects by line
st.subheader("Defects by line")
rows = []
for line in sorted(cur["lines"]):
    pv = prior["lines"].get(line) if prior else None
    rows.append({
        "Line": line,
        "Defects": cur["lines"][line],
        "Prior": pv if pv is not None else "—",
        "Δ": (cur["lines"][line] - pv) if pv is not None else "—",
    })
rows.append({
    "Line": "All lines",
    "Defects": cur["defects"],
    "Prior": prior["defects"] if prior else "—",
    "Δ": (cur["defects"] - prior["defects"]) if prior else "—",
})
st.table(pd.DataFrame(rows).set_index("Line"))

# Exceptions
st.subheader(f"Exceptions{' · ' + str(len(exceptions)) if exceptions else ''}")
if not exceptions:
    st.success("No exceptions — shift ran within normal range.")
else:
    for e in exceptions:
        body = f"**{e['sev'].upper()}** — **{e['who']}** ({e['kind']})\n\n{e['msg']}"
        if e["sev"] == "critical":
            st.error(body, icon="🚨")
        else:
            st.warning(body, icon="⚠️")

# Bottom line
st.subheader("Bottom line")
st.markdown(bottom_line(cur, prior, exceptions))

report_text = build_text_report(
    {"id": cur_id}, {"id": prior_id} if prior_id else None,
    cur, prior, exceptions, date_str, period,
)
st.download_button(
    "Download report (.txt)",
    report_text,
    file_name=f"shift-report-{cur_id}.txt",
    mime="text/plain",
    type="primary",
)
with st.expander("View plain-text report"):
    st.code(report_text, language=None)
