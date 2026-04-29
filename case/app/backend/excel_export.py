"""Экспорт результата выборки в многолистовой Excel-файл."""
from __future__ import annotations

from datetime import datetime
from io import BytesIO
from typing import Any

import pandas as pd

from config import DERIVED, METRICS, SECTION_RULES


RISK_TITLES = {
    "green": "Норма",
    "yellow": "Требует внимания",
    "red": "Высокий риск",
}

PRIMARY_METRIC_PRIORITY = [
    "limit_subject",
    "cash_subject",
    "bo_subject",
    "contract_amount",
    "payment_amount",
]


def _period_text(period: dict[str, Any]) -> str:
    ptype = period.get("type", "all")
    if ptype == "as_of":
        return f"На дату {period.get('date', '')}"
    if ptype == "range":
        return f"С {period.get('date_from', '')} по {period.get('date_to', '')}"
    if ptype == "compare":
        return f"Сравнение {period.get('date_a', '')} и {period.get('date_b', '')}"
    return "Без ограничения"


def _money_cols(df: pd.DataFrame) -> list[int]:
    out = []
    for idx, col in enumerate(df.columns):
        name = str(col).lower()
        if idx > 0 and not any(x in name for x in ("%", "доля", "статус", "риск", "дата", "номер", "код")):
            out.append(idx)
    return out


def _autofit(ws, df: pd.DataFrame, workbook, wrap_cols: set[int] | None = None, money_cols: set[int] | None = None,
             pct_cols: set[int] | None = None) -> None:
    wrap_cols = wrap_cols or set()
    money_cols = money_cols or set()
    pct_cols = pct_cols or set()
    wrap_fmt = workbook.add_format({"text_wrap": True, "valign": "top"})
    money_fmt = workbook.add_format({"num_format": '#,##0.00 "₽"', "align": "right"})
    pct_fmt = workbook.add_format({"num_format": "0.0%", "align": "right"})
    for idx, col in enumerate(df.columns):
        sample = [str(col)] + ["" if pd.isna(v) else str(v) for v in df[col].head(300).tolist()]
        width = min(max(max((len(x) for x in sample), default=8) + 2, 10), 52)
        fmt = None
        if idx in wrap_cols:
            fmt = wrap_fmt
            width = min(max(width, 24), 60)
        if idx in money_cols:
            fmt = money_fmt
            width = max(width, 18)
        if idx in pct_cols:
            fmt = pct_fmt
            width = max(width, 12)
        ws.set_column(idx, idx, width, fmt)


def _write_headers(ws, df: pd.DataFrame, header_fmt) -> None:
    for col_idx, col in enumerate(df.columns):
        ws.write(0, col_idx, col, header_fmt)


def _primary_metric(metrics: list[str], totals: dict[str, float]) -> str | None:
    for code in PRIMARY_METRIC_PRIORITY:
        if code in metrics:
            return code
    if totals:
        return max(totals, key=lambda code: abs(float(totals.get(code) or 0)))
    return metrics[0] if metrics else None


def build_excel(result: dict[str, Any]) -> bytes:
    params = result.get("params", {}) or {}
    summary = result.get("summary") or []
    dynamic = result.get("dynamic") or []
    details = result.get("details") or []
    metric_meta = result.get("metric_meta") or []
    totals = result.get("totals") or {}
    analytics = result.get("analytics") or []

    metric_lookup = {m["code"]: m["name"] for m in METRICS}
    metric_source = {m["code"]: m["source"] for m in METRICS}
    metric_group = {m["code"]: m["group"] for m in METRICS}
    section_titles = {k: v["title"] for k, v in SECTION_RULES.items()}

    metrics = params.get("metrics") or [m["code"] for m in metric_meta]
    metric_names = [metric_lookup.get(c, c) for c in metrics]
    primary_metric = _primary_metric(metrics, totals)
    primary_metric_name = metric_lookup.get(primary_metric, primary_metric or "Итого")
    period = params.get("period") or {}
    objects = params.get("objects") or []

    params_df = pd.DataFrame([
        ("Дата формирования", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        ("Выбранный период", _period_text(period)),
        ("Раздел", section_titles.get(params.get("section"), "Все")),
        ("Объекты", "; ".join(o.split("|")[-1] for o in objects[:30]) or "Все объекты"),
        ("Показатели", ", ".join(metric_names)),
        ("Кол-во объектов в результате", len(summary)),
        ("Кол-во точек динамики", len(dynamic)),
        ("Кол-во строк детализации", len(details)),
    ], columns=["Параметр", "Значение"])

    summary_rows = []
    for s in summary:
        row = {
            "Объект": s.get("object", ""),
            "Статус риска": RISK_TITLES.get(s.get("risk_level"), s.get("risk_label", "")),
            "Причины риска": "; ".join(s.get("risk_reasons") or []),
        }
        for code in metrics:
            row[metric_lookup.get(code, code)] = s.get(code, 0)
        if "exec_pct" in s:
            row["% исполнения"] = (float(s.get("exec_pct") or 0) / 100)
        if "uncontracted" in s:
            row["Неконтрактованный остаток"] = s["uncontracted"]
        if "unpaid_bo" in s:
            row["Неоплаченные обязательства"] = s["unpaid_bo"]
        if "contract_remainder" in s:
            row["Остаток по контрактам"] = s["contract_remainder"]
        summary_rows.append(row)
    summary_df = pd.DataFrame(summary_rows)
    if summary_df.empty:
        summary_df = pd.DataFrame(columns=["Объект", "Статус риска", "Причины риска"] + metric_names)

    kpi_df = pd.DataFrame([
        {
            "Код": code,
            "Показатель": metric_lookup.get(code, code),
            "Источник": metric_source.get(code, ""),
            "Группа": metric_group.get(code, ""),
            "Итого": value,
        }
        for code, value in totals.items()
    ])
    if not kpi_df.empty and "limit_subject" in totals and "cash_subject" in totals and totals.get("limit_subject"):
        kpi_df = pd.concat([kpi_df, pd.DataFrame([{
            "Код": "exec_pct",
            "Показатель": "% кассового исполнения",
            "Источник": "расч.",
            "Группа": "Риски",
            "Итого": float(totals.get("cash_subject") or 0) / float(totals.get("limit_subject") or 1),
        }])], ignore_index=True)
    if kpi_df.empty:
        kpi_df = pd.DataFrame(columns=["Код", "Показатель", "Источник", "Группа", "Итого"])

    dyn_rows = []
    for d in dynamic:
        row = {"Месяц": d.get("month", "")}
        for code in metrics:
            row[metric_lookup.get(code, code)] = d.get(code, 0)
        dyn_rows.append(row)
    dyn_df = pd.DataFrame(dyn_rows)
    if dyn_df.empty:
        dyn_df = pd.DataFrame(columns=["Месяц"] + metric_names)

    comparison_rows = []
    for s in sorted(summary, key=lambda x: float(x.get(primary_metric) or 0), reverse=True)[:30]:
        row = {"Объект": s.get("object", ""), "Статус риска": RISK_TITLES.get(s.get("risk_level"), "")}
        for code in metrics:
            row[metric_lookup.get(code, code)] = s.get(code, 0)
        comparison_rows.append(row)
    comparison_df = pd.DataFrame(comparison_rows)
    if comparison_df.empty:
        comparison_df = pd.DataFrame(columns=["Объект", "Статус риска"] + metric_names)

    detail_rename = {
        "object_name": "Объект",
        "source": "Источник",
        "metric_code": "Код показателя",
        "metric_name": "Показатель",
        "amount": "Сумма",
        "date": "Дата",
        "doc_type": "Тип документа",
        "doc_no": "Номер документа",
        "counterparty": "Контрагент",
        "kcsr": "КЦСР",
        "kvr": "КВР",
        "dopkr": "Код цели/ДопКР",
        "dopkr_name": "Наименование кода цели",
        "budget_name": "Бюджет",
    }
    details_df = pd.DataFrame(details).rename(columns=detail_rename)
    if not details_df.empty:
        details_df = details_df[[v for v in detail_rename.values() if v in details_df.columns]]
    else:
        details_df = pd.DataFrame(columns=list(detail_rename.values()))

    hints_df = pd.DataFrame({"Аналитическая подсказка": analytics or ["По выбранным параметрам данные не найдены."]})

    catalog_df = pd.DataFrame([
        {"Код": m["code"], "Наименование": m["name"], "Источник": m["source"], "Группа": m["group"], "Формула": ""}
        for m in METRICS
    ] + [
        {"Код": m["code"], "Наименование": m["name"], "Источник": "расч.", "Группа": "Расчетные показатели", "Формула": m["formula"]}
        for m in DERIVED
    ])

    chart_rows = []
    for s in sorted(summary, key=lambda x: float(x.get(primary_metric) or 0), reverse=True)[:12]:
        limit = float(s.get("limit_subject") or 0)
        cash = float(s.get("cash_subject") or 0)
        chart_rows.append({
            "Объект": s.get("object", ""),
            primary_metric_name: float(s.get(primary_metric) or 0),
            "Касса": cash,
            "Контракты": float(s.get("contract_amount") or 0),
            "% исполнения": cash / limit if limit else None,
        })
    charts_df = pd.DataFrame(chart_rows)
    if charts_df.empty:
        charts_df = pd.DataFrame(columns=["Объект", primary_metric_name, "Касса", "Контракты", "% исполнения"])

    dyn_chart_rows = []
    for d in dynamic:
        limit = float(d.get("limit_subject") or 0)
        cash = float(d.get("cash_subject") or 0)
        dyn_chart_rows.append({
            "Месяц": d.get("month", ""),
            primary_metric_name: float(d.get(primary_metric) or 0),
            "Касса": cash,
            "% исполнения": cash / limit if limit else None,
        })
    dyn_chart_df = pd.DataFrame(dyn_chart_rows)
    if dyn_chart_df.empty:
        dyn_chart_df = pd.DataFrame(columns=["Месяц", primary_metric_name, "Касса", "% исполнения"])

    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
        sheets = [
            ("Параметры выборки", params_df),
            ("Сводная", summary_df),
            ("KPI", kpi_df),
            ("Динамика", dyn_df),
            ("Сравнение", comparison_df),
            ("Детализация документов", details_df),
            ("Аналитические подсказки", hints_df),
            ("Справочник показателей", catalog_df),
            ("Графики", charts_df),
        ]
        for sheet_name, df in sheets:
            df.to_excel(writer, sheet_name=sheet_name, index=False)

        workbook = writer.book
        header_fmt = workbook.add_format({
            "bold": True, "bg_color": "#1F4E79", "font_color": "white",
            "align": "center", "valign": "vcenter", "border": 1,
        })
        title_fmt = workbook.add_format({"bold": True, "font_size": 12})
        money_fmt = workbook.add_format({"num_format": '#,##0.00 "₽"', "align": "right"})
        pct_fmt = workbook.add_format({"num_format": "0.0%", "align": "right"})
        risk_green = workbook.add_format({"bg_color": "#D9EAD3", "font_color": "#274E13"})
        risk_yellow = workbook.add_format({"bg_color": "#FFF2CC", "font_color": "#7F6000"})
        risk_red = workbook.add_format({"bg_color": "#F4CCCC", "font_color": "#990000"})

        for sheet_name, df in sheets:
            ws = writer.sheets[sheet_name]
            ws.set_zoom(105)
            ws.freeze_panes(1, 0)
            _write_headers(ws, df, header_fmt)
            ws.autofilter(0, 0, max(len(df), 1), max(len(df.columns) - 1, 0))

        writer.sheets["Параметры выборки"].set_column("A:A", 28, title_fmt)
        writer.sheets["Параметры выборки"].set_column("B:B", 80, workbook.add_format({"text_wrap": True, "valign": "top"}))

        _autofit(writer.sheets["Сводная"], summary_df, workbook,
                 wrap_cols={0, 2}, money_cols=set(_money_cols(summary_df)),
                 pct_cols={i for i, c in enumerate(summary_df.columns) if "%" in str(c)})
        _autofit(writer.sheets["KPI"], kpi_df, workbook,
                 wrap_cols={1}, money_cols={4} if not kpi_df.empty else set(),
                 pct_cols=set())
        _autofit(writer.sheets["Динамика"], dyn_df, workbook, money_cols=set(range(1, len(dyn_df.columns))))
        _autofit(writer.sheets["Сравнение"], comparison_df, workbook, wrap_cols={0}, money_cols=set(_money_cols(comparison_df)))
        _autofit(writer.sheets["Детализация документов"], details_df, workbook, wrap_cols={0, 3, 8, 12}, money_cols={4})
        _autofit(writer.sheets["Аналитические подсказки"], hints_df, workbook, wrap_cols={0})
        _autofit(writer.sheets["Справочник показателей"], catalog_df, workbook, wrap_cols={1, 4})
        _autofit(writer.sheets["Графики"], charts_df, workbook, wrap_cols={0}, money_cols={1, 2, 3}, pct_cols={4})

        graph_ws = writer.sheets["Графики"]
        dyn_start = max(len(charts_df) + 4, 18)
        graph_ws.write(dyn_start - 1, 0, "Динамика для графика", title_fmt)
        dyn_chart_df.to_excel(writer, sheet_name="Графики", startrow=dyn_start, startcol=0, index=False)
        for col_idx, col in enumerate(dyn_chart_df.columns):
            graph_ws.write(dyn_start, col_idx, col, header_fmt)
        graph_ws.set_column(0, 0, 42, workbook.add_format({"text_wrap": True, "valign": "top"}))
        if len(dyn_chart_df.columns) > 1:
            graph_ws.set_column(1, len(dyn_chart_df.columns) - 1, 18, money_fmt)
        if "% исполнения" in dyn_chart_df.columns:
            graph_ws.set_column(dyn_chart_df.columns.get_loc("% исполнения"), dyn_chart_df.columns.get_loc("% исполнения"), 13, pct_fmt)

        for sheet_name, df in (("Сводная", summary_df), ("Сравнение", comparison_df)):
            if "Статус риска" not in df.columns:
                continue
            ws = writer.sheets[sheet_name]
            col = df.columns.get_loc("Статус риска")
            ws.conditional_format(1, col, len(df), col, {"type": "text", "criteria": "containing", "value": "Норма", "format": risk_green})
            ws.conditional_format(1, col, len(df), col, {"type": "text", "criteria": "containing", "value": "Требует", "format": risk_yellow})
            ws.conditional_format(1, col, len(df), col, {"type": "text", "criteria": "containing", "value": "Высокий", "format": risk_red})

        if "% исполнения" in summary_df.columns:
            pct_col = summary_df.columns.get_loc("% исполнения")
            writer.sheets["Сводная"].set_column(pct_col, pct_col, 14, pct_fmt)

        if not kpi_df.empty and "Итого" in kpi_df.columns:
            total_col = kpi_df.columns.get_loc("Итого")
            writer.sheets["KPI"].set_column(total_col, total_col, 20, money_fmt)
            if "Код" in kpi_df.columns:
                for row_idx, code in enumerate(kpi_df["Код"].astype(str).tolist(), start=1):
                    if code.endswith("_pct") or code.endswith("_share") or code == "exec_pct":
                        writer.sheets["KPI"].write_number(row_idx, total_col, float(kpi_df.iloc[row_idx - 1]["Итого"] or 0), pct_fmt)

        if len(dyn_chart_df) >= 2 and len(dyn_chart_df.columns) > 1:
            chart = workbook.add_chart({"type": "column"})
            n_rows = len(dyn_chart_df)
            chart.add_series({
                "name": ["Графики", dyn_start, 1],
                "categories": ["Графики", dyn_start + 1, 0, dyn_start + n_rows, 0],
                "values": ["Графики", dyn_start + 1, 1, dyn_start + n_rows, 1],
                "fill": {"color": "#4D63D1"},
                "border": {"color": "#4D63D1"},
            })
            if "Касса" in dyn_chart_df.columns:
                cash_col = dyn_chart_df.columns.get_loc("Касса")
                chart.add_series({
                    "name": ["Графики", dyn_start, cash_col],
                    "categories": ["Графики", dyn_start + 1, 0, dyn_start + n_rows, 0],
                    "values": ["Графики", dyn_start + 1, cash_col, dyn_start + n_rows, cash_col],
                    "fill": {"color": "#2F8F4E"},
                    "border": {"color": "#2F8F4E"},
                })
            if "% исполнения" in dyn_chart_df.columns:
                pct_col = dyn_chart_df.columns.get_loc("% исполнения")
                chart.add_series({
                    "name": ["Графики", dyn_start, pct_col],
                    "categories": ["Графики", dyn_start + 1, 0, dyn_start + n_rows, 0],
                    "values": ["Графики", dyn_start + 1, pct_col, dyn_start + n_rows, pct_col],
                    "y2_axis": True,
                    "line": {"color": "#C64338", "width": 2.25},
                    "marker": {"type": "circle", "size": 5, "border": {"color": "#C64338"}, "fill": {"color": "#C64338"}},
                })
            chart.set_title({"name": "Динамика: деньги и % исполнения"})
            chart.set_x_axis({"name": "Месяц"})
            chart.set_y_axis({"name": "Сумма, руб.", "num_format": '#,##0'})
            chart.set_y2_axis({"name": "% исполнения", "num_format": "0%"})
            chart.set_legend({"position": "bottom"})
            chart.set_size({"width": 900, "height": 430})
            graph_ws.insert_chart(dyn_start, len(dyn_chart_df.columns) + 2, chart)

        if len(charts_df) >= 1 and len(charts_df.columns) > 1:
            chart = workbook.add_chart({"type": "bar"})
            n_rows = min(len(charts_df), 12)
            chart.add_series({
                "name": ["Графики", 0, 1],
                "categories": ["Графики", 1, 0, n_rows, 0],
                "values": ["Графики", 1, 1, n_rows, 1],
                "fill": {"color": "#4D63D1"},
                "border": {"color": "#4D63D1"},
            })
            if "Касса" in charts_df.columns:
                cash_col = charts_df.columns.get_loc("Касса")
                chart.add_series({
                    "name": ["Графики", 0, cash_col],
                    "categories": ["Графики", 1, 0, n_rows, 0],
                    "values": ["Графики", 1, cash_col, n_rows, cash_col],
                    "fill": {"color": "#2F8F4E"},
                    "border": {"color": "#2F8F4E"},
                })
            chart.set_title({"name": f"Топ объектов: {primary_metric_name} и касса"})
            chart.set_x_axis({"name": "Сумма, руб.", "num_format": '#,##0'})
            chart.set_legend({"position": "bottom"})
            chart.set_size({"width": 900, "height": 430})
            graph_ws.insert_chart(1, len(charts_df.columns) + 2, chart)

    return buf.getvalue()
