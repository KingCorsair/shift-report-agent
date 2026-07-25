# Lab 1 · Production Shift Report Agent

Turns an end-of-shift machine log (CSV) into a one-page, plain-language shift
report with a flagged exceptions section — units produced, downtime, and defects
by line, compared against the prior shift.

## What's here

```
claude_lab/
├── AGENT.md                 Agent instructions — the prompt you iterate on
├── data/
│   └── shift_log.csv        Practice data: two shifts, with seeded anomalies
├── shift_report_ui.html     Single-screen UI (drop → Generate → report → download)
├── streamlit_app.py         Streamlit port of the same app (for cloud deployment)
├── requirements.txt         Python deps for the Streamlit app
└── README.md
```

## Run the Streamlit app

```
pip install -r requirements.txt
streamlit run streamlit_app.py
```

Or deploy free on [Streamlit Community Cloud](https://share.streamlit.io):
point it at this repo with `streamlit_app.py` as the main file.

## The UI

`shift_report_ui.html` is a self-contained single screen. Drop a shift-log CSV
(or click **Load sample data**), press **Generate report**, read the report, and
**Download** it as a text file. All parsing and computation happen in the page —
no server, no network.

## Two reports from one click

Pressing **Generate report** produces two reports:

1. **Shift report** — totals, defects by line, exceptions, and a bottom line for
   the latest shift.
2. **Comparison report** — a *separate* report, below the first, that compares
   the shift to the immediately prior one: a plain-language summary (output,
   downtime, defects, defect rate, and the biggest line change) and a
   side-by-side table. Each report has its own download button.

The comparison report appears whenever the log has a prior shift; with a
single-shift log it says so instead. Same behaviour in the Streamlit app.

## Log format

One row per machine per shift:

`shift_id, shift_start, line, machine_id, units_produced, defect_count, downtime_minutes`

A log with two or more shifts is compared latest-vs-previous automatically. Any
log in this format works with no code changes.

## Seeded anomalies (practice data)

The night shift in `data/shift_log.csv` hides two planted problems for the
report to catch:

- **M-06 (Line C)** — downtime jumps to **130 min** (from 15) and output nearly
  halves. → machine-down exception.
- **M-07 (Line C)** — **68 defects** (from 5), holding most of the shift's
  defects. → defect-spike exception.

A correct report flags both and shows the night-shift defect rate rising above
the day shift.

## Success criteria

- Accurate report from any valid shift log, no code changes.
- At least one seeded anomaly flagged. (This one flags both.)
