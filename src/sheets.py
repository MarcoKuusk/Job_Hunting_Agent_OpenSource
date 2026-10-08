"""Logs matched jobs to your Google Sheet and keeps that sheet looking like a
dashboard rather than a wall of text.

Two worksheets are maintained:

  * the job log (the spreadsheet's first tab) - one row per matched job, with
    a frozen header, a colour scale on the fit score, and a Status dropdown;
  * "Dashboard" - a formula-driven summary tab (counters, top matches still to
    review, breakdown by source and by stage, plus two charts). Everything on
    it is a live formula, so it updates by itself as rows are added; we only
    ever have to build it once.

gspread/google-auth are imported lazily so the rest of the program loads
without them.
"""

from __future__ import annotations

from typing import Any

from .models import Job

# The job log's columns. New columns are only ever APPENDED, so an existing
# sheet keeps working: _ensure_header extends row 1 instead of rewriting it.
HEADERS = [
    "Date found", "Source", "Title", "Company", "Location",
    "Score", "Recommendation", "Reasons", "URL", "Status",
    "Applied on", "Notes",
]

DASHBOARD_TITLE = "Dashboard"

# The stages a job moves through. These drive the Status dropdown and the
# pipeline chart, so the two can never disagree.
STATUSES = [
    "New", "Interested", "Applied", "Interviewing", "Offer", "Rejected",
    "Not a fit",
]

# Every source the searcher can log from (see config/search.yaml).
SOURCE_NAMES = [
    "remoteok", "arbeitnow", "remotive", "weworkremotely", "linkedin", "upwork",
]


def _rgb(hex_colour: str) -> dict[str, float]:
    h = hex_colour.lstrip("#")
    return {
        "red": int(h[0:2], 16) / 255,
        "green": int(h[2:4], 16) / 255,
        "blue": int(h[4:6], 16) / 255,
    }


INK = _rgb("1f2937")       # near-black text
PAPER = _rgb("ffffff")
HEADER_BG = _rgb("1f3864")  # deep blue header band
ACCENT = _rgb("2f5597")
MUTED = _rgb("6b7280")
TILE_BG = _rgb("eef2fb")
GOOD = _rgb("b7e1cd")
OKAY = _rgb("fce8b2")
POOR = _rgb("f4c7c3")


# --------------------------------------------------------------------------
# Opening the spreadsheet
# --------------------------------------------------------------------------
def open_spreadsheet(config):
    """Open the configured Google Sheet (the whole document)."""
    import gspread

    sa_path = config.google_service_account_path
    if not sa_path.exists():
        raise FileNotFoundError(
            f"Google service-account file not found at {sa_path}. "
            f"Download it from Google Cloud and put it in credentials/."
        )
    sheet_id = config.google_sheet_id
    if not sheet_id:
        raise RuntimeError("GOOGLE_SHEET_ID is not set in .env.")

    gc = gspread.service_account(filename=str(sa_path))
    return gc.open_by_key(sheet_id)


def open_worksheet(config):
    """Open the worksheet holding the job log (the first tab)."""
    spreadsheet = open_spreadsheet(config)
    return _jobs_worksheet(spreadsheet)


def _jobs_worksheet(spreadsheet):
    """The job log is the first tab that isn't the Dashboard."""
    for ws in spreadsheet.worksheets():
        if ws.title != DASHBOARD_TITLE:
            return ws
    return spreadsheet.sheet1


def sheet_url(config, gid: int | None = None) -> str:
    """A link the UI can open. No API call, just string building."""
    sheet_id = config.google_sheet_id
    if not sheet_id:
        return ""
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit"
    return f"{url}#gid={gid}" if gid is not None else url


# --------------------------------------------------------------------------
# Writing jobs
# --------------------------------------------------------------------------
def _ensure_header(ws) -> None:
    """Make row 1 the header row, and grow it if we've added columns since
    this sheet was created (old rows stay valid because columns are only ever
    appended on the right)."""
    existing = ws.row_values(1)
    if existing[: len(HEADERS)] == HEADERS:
        return
    if not existing:
        ws.append_row(HEADERS)
        return
    if HEADERS[: len(existing)] == existing:
        # Same columns, just fewer of them: extend the header in place.
        ws.update(values=[HEADERS], range_name="A1")
        return
    # Something unexpected is in row 1 - keep it, put ours above it.
    ws.insert_row(HEADERS, index=1)


def existing_urls(ws) -> set[str]:
    """URLs already logged, so we never write the same job twice."""
    try:
        url_col_index = HEADERS.index("URL") + 1  # gspread is 1-based
        values = ws.col_values(url_col_index)
    except Exception:
        return set()
    # Drop the header cell and normalise.
    return {v.strip().lower() for v in values[1:] if v.strip()}


def _job_to_row(job: Job, date_found: str) -> list[Any]:
    return [
        date_found,
        job.source,
        job.title,
        job.company,
        job.location,
        job.score if job.score is not None else "",
        job.recommendation,
        job.reasons,
        job.url,
        "New",
        "",   # Applied on - filled in when the status is set to Applied
        "",   # Notes - yours to write in
    ]


def append_jobs(config, jobs: list[Job], date_found: str) -> int:
    """Append jobs not already present (by URL). Returns the number written."""
    spreadsheet = open_spreadsheet(config)
    ws = _jobs_worksheet(spreadsheet)
    _ensure_header(ws)
    seen = existing_urls(ws)

    rows: list[list[Any]] = []
    for job in jobs:
        key = (job.url or "").strip().lower()
        if key and key in seen:
            continue
        rows.append(_job_to_row(job, date_found))
        if key:
            seen.add(key)

    if rows:
        ws.append_rows(rows, value_input_option="USER_ENTERED")
    return len(rows)


def read_logged_jobs(config) -> list[dict[str, Any]]:
    """Read all logged rows back as a list of dicts (used by the apply
    assistant and the web UI to let you pick a job).

    Every cell comes back as text (`numericise_ignore=["all"]`). gspread
    otherwise converts anything that parses as a number, and `float()` accepts
    "Infinity" and "NaN": a company called Infinity turned into a non-finite
    float that made the whole JSON response unreadable to the browser. Callers
    that want the score as a number convert it themselves.
    """
    ws = open_worksheet(config)
    _ensure_header(ws)
    return ws.get_all_records(expected_headers=HEADERS,
                              numericise_ignore=["all"])


def update_status(config, url: str, status: str) -> bool:
    """Set the Status cell for the row whose URL matches, stamping today's date
    in "Applied on" when the new status is Applied. Returns True if a row was
    updated. Only called after the user explicitly confirms - this never marks
    anything 'applied' on its own."""
    from datetime import datetime

    ws = open_worksheet(config)
    url_col = HEADERS.index("URL") + 1
    status_col = HEADERS.index("Status") + 1
    applied_col = HEADERS.index("Applied on") + 1
    cells = ws.col_values(url_col)
    target = (url or "").strip().lower()
    for row_index, value in enumerate(cells[1:], start=2):  # skip header
        if value.strip().lower() == target:
            ws.update_cell(row_index, status_col, status)
            if status.strip().lower() == "applied":
                ws.update_cell(row_index, applied_col,
                               datetime.now().strftime("%Y-%m-%d"))
            return True
    return False


# --------------------------------------------------------------------------
# Making it look like a dashboard
# --------------------------------------------------------------------------
def _clear_conditional_formats(spreadsheet, sheet_id: int) -> list[dict]:
    """Requests that remove every existing rule on a sheet, so re-running the
    formatting doesn't stack duplicate rules."""
    meta = spreadsheet.fetch_sheet_metadata()
    count = 0
    for sheet in meta.get("sheets", []):
        if sheet.get("properties", {}).get("sheetId") == sheet_id:
            count = len(sheet.get("conditionalFormats", []) or [])
            break
    return [
        {"deleteConditionalFormatRule": {"sheetId": sheet_id, "index": i}}
        for i in reversed(range(count))
    ]


def format_jobs_sheet(spreadsheet, ws) -> None:
    """Frozen bold header, sensible column widths, a green-to-red colour scale
    on the fit score, a Status dropdown, and a filter on the header row."""
    sid = ws.id
    last_col = len(HEADERS)
    score_col = HEADERS.index("Score")
    status_col = HEADERS.index("Status")

    widths = {0: 95, 1: 105, 2: 300, 3: 180, 4: 160, 5: 60, 6: 125, 7: 420,
              8: 240, 9: 125, 10: 100, 11: 260}

    requests: list[dict] = [
        {"updateSheetProperties": {
            "properties": {"sheetId": sid,
                           "gridProperties": {"frozenRowCount": 1}},
            "fields": "gridProperties.frozenRowCount",
        }},
        {"repeatCell": {
            "range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 1,
                      "startColumnIndex": 0, "endColumnIndex": last_col},
            "cell": {"userEnteredFormat": {
                "backgroundColor": HEADER_BG,
                "horizontalAlignment": "LEFT",
                "verticalAlignment": "MIDDLE",
                "textFormat": {"bold": True, "fontSize": 11,
                               "foregroundColor": PAPER},
            }},
            "fields": "userEnteredFormat(backgroundColor,horizontalAlignment,"
                      "verticalAlignment,textFormat)",
        }},
        {"updateDimensionProperties": {
            "range": {"sheetId": sid, "dimension": "ROWS",
                      "startIndex": 0, "endIndex": 1},
            "properties": {"pixelSize": 34},
            "fields": "pixelSize",
        }},
        # Keep long descriptions on one line so the table stays scannable.
        {"repeatCell": {
            "range": {"sheetId": sid, "startRowIndex": 1,
                      "startColumnIndex": 0, "endColumnIndex": last_col},
            "cell": {"userEnteredFormat": {"wrapStrategy": "CLIP",
                                           "verticalAlignment": "MIDDLE"}},
            "fields": "userEnteredFormat(wrapStrategy,verticalAlignment)",
        }},
        {"repeatCell": {
            "range": {"sheetId": sid, "startRowIndex": 1,
                      "startColumnIndex": score_col,
                      "endColumnIndex": score_col + 1},
            "cell": {"userEnteredFormat": {
                "horizontalAlignment": "CENTER",
                "textFormat": {"bold": True},
            }},
            "fields": "userEnteredFormat(horizontalAlignment,textFormat)",
        }},
    ]
    for index, pixels in widths.items():
        requests.append({"updateDimensionProperties": {
            "range": {"sheetId": sid, "dimension": "COLUMNS",
                      "startIndex": index, "endIndex": index + 1},
            "properties": {"pixelSize": pixels},
            "fields": "pixelSize",
        }})

    requests += _clear_conditional_formats(spreadsheet, sid)

    # Colour scale on the score: red at 40, amber at 65, green at 90.
    requests.append({"addConditionalFormatRule": {
        "index": 0,
        "rule": {
            "ranges": [{"sheetId": sid, "startRowIndex": 1,
                        "startColumnIndex": score_col,
                        "endColumnIndex": score_col + 1}],
            "gradientRule": {
                "minpoint": {"color": POOR, "type": "NUMBER", "value": "40"},
                "midpoint": {"color": OKAY, "type": "NUMBER", "value": "65"},
                "maxpoint": {"color": GOOD, "type": "NUMBER", "value": "90"},
            },
        },
    }})
    # Fade out rows you've closed out, highlight the ones in play.
    row_range = {"sheetId": sid, "startRowIndex": 1,
                 "startColumnIndex": 0, "endColumnIndex": last_col}
    for formula, fmt in (
        ('=$J2="Applied"', {"backgroundColor": _rgb("e8f0fe")}),
        ('=$J2="Interviewing"', {"backgroundColor": _rgb("d9ead3"),
                                 "textFormat": {"bold": True}}),
        ('=OR($J2="Rejected",$J2="Not a fit")',
         {"textFormat": {"foregroundColor": MUTED, "italic": True}}),
    ):
        requests.append({"addConditionalFormatRule": {
            "index": 0,
            "rule": {"ranges": [row_range],
                     "booleanRule": {
                         "condition": {"type": "CUSTOM_FORMULA",
                                       "values": [{"userEnteredValue": formula}]},
                         "format": fmt}},
        }})

    # Status dropdown, so the stage is picked from a list and never mistyped.
    requests.append({"setDataValidation": {
        "range": {"sheetId": sid, "startRowIndex": 1,
                  "startColumnIndex": status_col,
                  "endColumnIndex": status_col + 1},
        "rule": {
            "condition": {"type": "ONE_OF_LIST",
                          "values": [{"userEnteredValue": s} for s in STATUSES]},
            "strict": False,
            "showCustomUi": True,
        },
    }})
    requests.append({"setBasicFilter": {
        "filter": {"range": {"sheetId": sid, "startRowIndex": 0,
                             "startColumnIndex": 0, "endColumnIndex": last_col}}
    }})

    spreadsheet.batch_update({"requests": requests})


# --------------------------------------------------------------------------
# The Dashboard tab
# --------------------------------------------------------------------------
def _dashboard_blocks(jobs_title: str, min_score: int = 0) -> list[dict[str, Any]]:
    """The Dashboard's cell contents, as ranges for one batched write.

    Everything that counts anything is a formula against the job log, so the
    tab keeps itself up to date and only has to be built once.

    The three blocks exist so that nothing is ever written into A9:D18: that
    is where the "best matches" QUERY spills its results, and a cell written
    there (even a blank one) can break the spill.

    The job log holds every job we scored, not just the good ones, so anything
    that measures how the search is GOING has to say ">= min_score" explicitly.
    Without that, "Average fit" is dragged down by long shots and "Good matches
    waiting" counts the whole sheet (every appended row starts as "New").
    """
    j = f"'{jobs_title}'"
    status_col = f"{j}!$J$2:$J"
    score_col = f"{j}!$F$2:$F"
    source_col = f"{j}!$B$2:$B"
    date_col = f"{j}!$A$2:$A"

    good = f'{score_col},">="&{int(min_score)}'

    def pad(row: list[Any]) -> list[Any]:
        return row + [""] * (6 - len(row))

    top = [
        ["Your job search at a glance"],
        ["Every number here updates by itself. Change a job's Status on the "
         "job list tab and this tab follows."],
        [],
        ["Jobs found", "Good matches waiting", "Applied", "Interviewing",
         "Average fit (good matches)", "Found this week"],
        [
            f"=COUNTA({j}!$I$2:$I)",
            f'=COUNTIFS({status_col},"New",{good})'
            f'+COUNTIFS({status_col},"Interested",{good})',
            f'=COUNTIF({status_col},"Applied")',
            f'=COUNTIF({status_col},"Interviewing")',
            f"=IFERROR(ROUND(AVERAGEIF({good})),0)",
            f'=COUNTIF({date_col},">="&TEXT(TODAY()-7,"yyyy-mm-dd"))',
        ],
        [],
        ["Best matches still waiting for you"],
        ["Fit", "Job title", "Company", "Open the posting"],
    ]

    matches_query = (
        f'=IFERROR(QUERY({j}!$A$2:$L,"select F, C, D, I where J = \'New\' '
        f'and F >= {int(min_score)} order by F desc limit 10",0),'
        f'"Nothing new to review yet. Run a search to find more.")'
    )

    bottom = [
        ["Where your jobs come from"],
        ["Job board", "Jobs found"],
    ]
    bottom += [[name, f'=COUNTIF({source_col},"{name}")']
               for name in SOURCE_NAMES]
    bottom += [[], []]
    bottom += [
        ["Your pipeline"],
        ["Stage", "Jobs"],
    ]
    bottom += [[status, f'=COUNTIF({status_col},"{status}")']
               for status in STATUSES]

    last_row = 20 + len(bottom) - 1
    return [
        {"range": "A1:F8", "values": [pad(r) for r in top]},
        {"range": "A9", "values": [[matches_query]]},
        {"range": f"A20:F{last_row}", "values": [pad(r) for r in bottom]},
    ]


def _chart_requests(dash_id: int) -> list[dict]:
    """A column chart of job boards and a pie chart of the pipeline."""
    sources_end = 21 + len(SOURCE_NAMES)     # exclusive row index
    pipeline_end = 31 + len(STATUSES)

    def col(start_row, end_row, start_col, end_col):
        return {"sheetId": dash_id, "startRowIndex": start_row,
                "endRowIndex": end_row, "startColumnIndex": start_col,
                "endColumnIndex": end_col}

    return [
        {"addChart": {"chart": {
            "spec": {
                "title": "Jobs found per board",
                "basicChart": {
                    "chartType": "COLUMN",
                    "legendPosition": "NO_LEGEND",
                    "axis": [{"position": "BOTTOM_AXIS"},
                             {"position": "LEFT_AXIS"}],
                    "domains": [{"domain": {"sourceRange": {"sources": [
                        col(20, sources_end, 0, 1)]}}}],
                    "series": [{"series": {"sourceRange": {"sources": [
                        col(20, sources_end, 1, 2)]}},
                        "targetAxis": "LEFT_AXIS",
                        "color": ACCENT}],
                    "headerCount": 1,
                },
            },
            "position": {"overlayPosition": {
                "anchorCell": {"sheetId": dash_id, "rowIndex": 19,
                               "columnIndex": 4},
                "widthPixels": 460, "heightPixels": 260}},
        }}},
        {"addChart": {"chart": {
            "spec": {
                "title": "Where your applications stand",
                "pieChart": {
                    "legendPosition": "RIGHT_LEGEND",
                    "domain": {"sourceRange": {"sources": [
                        col(30, pipeline_end, 0, 1)]}},
                    "series": {"sourceRange": {"sources": [
                        col(30, pipeline_end, 1, 2)]}},
                },
            },
            "position": {"overlayPosition": {
                "anchorCell": {"sheetId": dash_id, "rowIndex": 29,
                               "columnIndex": 4},
                "widthPixels": 460, "heightPixels": 280}},
        }}},
    ]


def _existing_chart_ids(spreadsheet, sheet_id: int) -> list[int]:
    meta = spreadsheet.fetch_sheet_metadata()
    for sheet in meta.get("sheets", []):
        if sheet.get("properties", {}).get("sheetId") == sheet_id:
            return [c["chartId"] for c in sheet.get("charts", []) or []
                    if "chartId" in c]
    return []


def _dashboard_format_requests(dash_id: int) -> list[dict]:
    def rng(r0, r1, c0, c1):
        return {"sheetId": dash_id, "startRowIndex": r0, "endRowIndex": r1,
                "startColumnIndex": c0, "endColumnIndex": c1}

    def section(row):
        """Style for a section heading row."""
        return {"repeatCell": {
            "range": rng(row, row + 1, 0, 6),
            "cell": {"userEnteredFormat": {
                "textFormat": {"bold": True, "fontSize": 13,
                               "foregroundColor": HEADER_BG}}},
            "fields": "userEnteredFormat.textFormat",
        }}

    def table_header(row):
        return {"repeatCell": {
            "range": rng(row, row + 1, 0, 4),
            "cell": {"userEnteredFormat": {
                "backgroundColor": HEADER_BG,
                "textFormat": {"bold": True, "foregroundColor": PAPER}}},
            "fields": "userEnteredFormat(backgroundColor,textFormat)",
        }}

    requests: list[dict] = [
        {"updateSheetProperties": {
            "properties": {"sheetId": dash_id, "index": 0,
                           "gridProperties": {"hideGridlines": True}},
            "fields": "index,gridProperties.hideGridlines",
        }},
        # Title + subtitle
        {"repeatCell": {
            "range": rng(0, 1, 0, 6),
            "cell": {"userEnteredFormat": {
                "textFormat": {"bold": True, "fontSize": 20,
                               "foregroundColor": HEADER_BG}}},
            "fields": "userEnteredFormat.textFormat",
        }},
        {"repeatCell": {
            "range": rng(1, 2, 0, 6),
            "cell": {"userEnteredFormat": {
                "textFormat": {"fontSize": 10, "foregroundColor": MUTED}}},
            "fields": "userEnteredFormat.textFormat",
        }},
        # The six counter tiles: small grey label above a big number.
        {"repeatCell": {
            "range": rng(3, 4, 0, 6),
            "cell": {"userEnteredFormat": {
                "backgroundColor": TILE_BG,
                "horizontalAlignment": "CENTER",
                "textFormat": {"bold": True, "fontSize": 10,
                               "foregroundColor": MUTED}}},
            "fields": "userEnteredFormat(backgroundColor,horizontalAlignment,"
                      "textFormat)",
        }},
        {"repeatCell": {
            "range": rng(4, 5, 0, 6),
            "cell": {"userEnteredFormat": {
                "backgroundColor": TILE_BG,
                "horizontalAlignment": "CENTER",
                "verticalAlignment": "MIDDLE",
                "textFormat": {"bold": True, "fontSize": 26,
                               "foregroundColor": HEADER_BG}}},
            "fields": "userEnteredFormat(backgroundColor,horizontalAlignment,"
                      "verticalAlignment,textFormat)",
        }},
        {"updateDimensionProperties": {
            "range": {"sheetId": dash_id, "dimension": "ROWS",
                      "startIndex": 4, "endIndex": 5},
            "properties": {"pixelSize": 52},
            "fields": "pixelSize",
        }},
        section(0),
        section(6),
        section(19),
        section(29),
        table_header(7),
        table_header(20),
        table_header(30),
        # Centre the fit score in the "best matches" table.
        {"repeatCell": {
            "range": rng(8, 18, 0, 1),
            "cell": {"userEnteredFormat": {
                "horizontalAlignment": "CENTER",
                "textFormat": {"bold": True}}},
            "fields": "userEnteredFormat(horizontalAlignment,textFormat)",
        }},
    ]
    for index, pixels in {0: 190, 1: 330, 2: 200, 3: 260, 4: 60, 5: 130}.items():
        requests.append({"updateDimensionProperties": {
            "range": {"sheetId": dash_id, "dimension": "COLUMNS",
                      "startIndex": index, "endIndex": index + 1},
            "properties": {"pixelSize": pixels},
            "fields": "pixelSize",
        }})

    # Same green-to-red scale as the job log, on the top-matches score column.
    requests.append({"addConditionalFormatRule": {
        "index": 0,
        "rule": {
            "ranges": [rng(8, 18, 0, 1)],
            "gradientRule": {
                "minpoint": {"color": POOR, "type": "NUMBER", "value": "40"},
                "midpoint": {"color": OKAY, "type": "NUMBER", "value": "65"},
                "maxpoint": {"color": GOOD, "type": "NUMBER", "value": "90"},
            },
        },
    }})
    return requests


def build_dashboard(config) -> str:
    """Create (or refresh) the Dashboard tab and tidy up the job log.

    Safe to call on every run: it rewrites the same cells, replaces its own
    charts rather than piling up new ones, and never touches logged rows.
    Returns a link straight to the Dashboard tab.
    """
    spreadsheet = open_spreadsheet(config)
    jobs_ws = _jobs_worksheet(spreadsheet)
    _ensure_header(jobs_ws)
    format_jobs_sheet(spreadsheet, jobs_ws)

    try:
        dash = spreadsheet.worksheet(DASHBOARD_TITLE)
    except Exception:  # gspread.WorksheetNotFound, imported lazily
        dash = spreadsheet.add_worksheet(title=DASHBOARD_TITLE, rows=60, cols=12)

    dash.clear()
    dash.batch_update(_dashboard_blocks(jobs_ws.title, config.min_score()),
                      value_input_option="USER_ENTERED")

    requests = _clear_conditional_formats(spreadsheet, dash.id)
    requests += [{"deleteEmbeddedObject": {"objectId": cid}}
                 for cid in _existing_chart_ids(spreadsheet, dash.id)]
    requests += _dashboard_format_requests(dash.id)
    requests += _chart_requests(dash.id)
    spreadsheet.batch_update({"requests": requests})

    return sheet_url(config, gid=dash.id)
