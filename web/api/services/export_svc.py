"""Export (GET /api/export/workbook.xlsx): your own data in one Excel workbook, one sheet each, for your CA or your
own analysis: holdings and tax lots, the trade journal (with your notes), practice-account trades, the practice
bot's orders, portfolio risk, alerts and watchlists.

The .xlsx is written here without extra libraries (an Excel file is a zip of XML parts): strings, numbers and
booleans only, a bold header row, frozen under it. Every sheet comes from a service the pages already use; a sheet
whose source fails says so in its first cell instead of breaking the workbook.
"""
from __future__ import annotations

import io
import math
import zipfile
from datetime import datetime
from xml.sax.saxutils import escape

from ..util import now_ist


def _col(n: int) -> str:
    s = ""
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _cell(ref: str, v, style: int = 0) -> str:
    st = f' s="{style}"' if style else ""
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return ""
    if isinstance(v, bool):
        return f'<c r="{ref}" t="b"{st}><v>{int(v)}</v></c>'
    if isinstance(v, (int, float)):
        return f'<c r="{ref}"{st}><v>{v}</v></c>'
    text = escape(str(v) if not isinstance(v, (list, dict)) else ", ".join(map(str, v)) if isinstance(v, list) else str(v))
    return f'<c r="{ref}" t="inlineStr"{st}><is><t xml:space="preserve">{text[:32000]}</t></is></c>'


def _sheet(rows: list[dict]) -> str:
    heads = list(dict.fromkeys(k for r in rows for k in r)) if rows else ["(empty)"]
    out = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
           '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
           '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
           '</sheetView></sheetViews>',
           '<cols>' + "".join(f'<col min="{i + 1}" max="{i + 1}" width="{min(max(len(h) + 2, 10), 40)}" customWidth="1"/>'
                              for i, h in enumerate(heads)) + '</cols>', "<sheetData>"]
    out.append('<row r="1">' + "".join(_cell(f"{_col(i)}1", h, 1) for i, h in enumerate(heads)) + "</row>")
    for j, r in enumerate(rows, start=2):
        out.append(f'<row r="{j}">' + "".join(_cell(f"{_col(i)}{j}", r.get(h)) for i, h in enumerate(heads)) + "</row>")
    out.append("</sheetData></worksheet>")
    return "".join(out)


def xlsx(sheets: dict[str, list[dict]]) -> bytes:
    """A workbook with one sheet per entry (names cut to Excel's 31 characters)."""
    names = []
    for n in sheets:
        clean = "".join(ch for ch in n if ch not in '[]:*?/\\')[:31] or "Sheet"
        while clean in names:
            clean = clean[:28] + f"_{len(names)}"
        names.append(clean)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                   '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
                   + "".join(f'<Override PartName="/xl/worksheets/sheet{i + 1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                             for i in range(len(names))) + "</Types>")
        z.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr("xl/workbook.xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                   + "".join(f'<sheet name="{escape(n)}" sheetId="{i + 1}" r:id="rId{i + 1}"/>' for i, n in enumerate(names)) + "</sheets></workbook>")
        z.writestr("xl/_rels/workbook.xml.rels", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   + "".join(f'<Relationship Id="rId{i + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i + 1}.xml"/>'
                             for i in range(len(names)))
                   + f'<Relationship Id="rId{len(names) + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
        z.writestr("xl/styles.xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                   '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
                   '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
                   '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
                   '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
                   '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
                   '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs>'
                   '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>')
        for i, rows in enumerate(sheets.values()):
            z.writestr(f"xl/worksheets/sheet{i + 1}.xml", _sheet(rows))
    return buf.getvalue()


def _try(fn) -> list[dict]:
    try:
        return fn()
    except Exception as e:                                # one failing source never breaks the workbook
        return [{"note": f"Not available: {type(e).__name__}: {e}"}]


def workbook() -> tuple[bytes, str]:
    from scanner import watch
    from . import bot_svc, journal_svc, risk_svc, sim_svc, tax_svc

    def lots():
        return [{k: v for k, v in x.items() if k != "id"} for x in tax_svc.view()["lots"]]

    def journal():
        return [{k: (", ".join(v) if isinstance(v, list) else v) for k, v in t.items() if k not in ("has_image",)}
                for t in journal_svc.view()["trades"]]

    def practice():
        st = sim_svc._load() if sim_svc._path().exists() else {"trades": []}
        return list(st.get("trades") or [])

    def bot():
        return list(bot_svc._load().get("log") or [])

    def risk():
        v = risk_svc.view()
        return [{k: v2 for k, v2 in p.items()} for p in v.get("positions") or []]

    def alerts():
        return [{k: v for k, v in a.items() if k not in ("a", "b", "seen")} for a in watch.alerts()]

    def lists():
        return [{"list": lst["name"], "symbol": s, "smart_scan": lst.get("scan_id")} for lst in watch.watchlists()["lists"]
                for s in lst["symbols"]]

    sheets = {"Holdings and tax lots": _try(lots), "Trade journal": _try(journal), "Practice trades": _try(practice),
              "Practice bot orders": _try(bot), "Portfolio risk": _try(risk), "Alerts": _try(alerts),
              "Watchlists": _try(lists)}
    name = f"quant-desk-{now_ist():%Y%m%d}.xlsx"
    return xlsx(sheets), name
