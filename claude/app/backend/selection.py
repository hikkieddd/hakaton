"""Сервис формирования аналитической выборки на основе нормализованного DataFrame фактов."""
from __future__ import annotations

from typing import Any
import re

import pandas as pd

from config import METRICS, SECTION_RULES


RISK_META = {
    "green": {"title": "Норма", "rank": 1},
    "yellow": {"title": "Требует внимания", "rank": 2},
    "red": {"title": "Высокий риск", "rank": 3},
}


def _tokenize_query(query: str) -> list[str]:
    tokens = [t for t in re.split(r"[\s,;:№#\"'()]+", (query or "").strip().lower()) if len(t) >= 2]
    synonyms = {
        "детский": ["дошкольн"],
        "сад": ["дошкольн", "учрежден"],
        "детсад": ["дошкольн"],
    }
    expanded: list[str] = []
    for token in tokens:
        expanded.append(token)
        expanded.extend(synonyms.get(token, []))
    return expanded


def _kcsr_clean(s: str) -> str:
    """Удаляет точки из КЦСР для применения правил по позициям."""
    return (s or "").replace(".", "").replace(" ", "").upper()


def apply_section_filter(df: pd.DataFrame, section_id: str) -> pd.DataFrame:
    rule = SECTION_RULES.get(section_id)
    if not rule or df.empty:
        return df
    out = df.copy()
    if "kcsr_substring" in rule:
        start, length, expected = rule["kcsr_substring"]
        codes = out["kcsr"].fillna("").map(_kcsr_clean)
        out = out[codes.str[start:start + length] == expected]
    if rule.get("dopkr_not_null"):
        out = out[out["dopkr"].fillna("").str.strip().ne("") & out["dopkr"].fillna("").str.strip().ne("0")]
    if "kvr_in" in rule:
        kvr_clean = out["kvr"].fillna("").map(lambda s: s.replace(".", "").strip())
        out = out[kvr_clean.isin(rule["kvr_in"])]
    return out


def search_objects(df: pd.DataFrame, query: str = "", types: list[str] | None = None,
                   section: str | None = None, limit: int = 200) -> list[dict]:
    """Возвращает уникальные объекты с количеством связанных фактов."""
    if df.empty:
        return []
    work = df
    if section:
        work = apply_section_filter(work, section)
    if types:
        work = work[work["object_type"].isin(types)]
    if query:
        q = query.strip().lower()
        tokens = _tokenize_query(q)
        searchable_cols = [
            "object_name", "kcsr", "kvr", "dopkr", "dopkr_name", "counterparty",
            "doc_no", "doc_type", "metric_name", "budget_name",
        ]
        text = pd.Series("", index=work.index, dtype="object")
        for col in searchable_cols:
            if col in work.columns:
                text = text.str.cat(work[col].fillna("").astype(str).str.lower(), sep=" ")
        if tokens:
            mask = pd.Series(True, index=work.index)
            for token in tokens:
                mask &= text.str.contains(token, na=False, regex=False)
            if not mask.any():
                mask = pd.Series(False, index=work.index)
                for token in tokens:
                    mask |= text.str.contains(token, na=False, regex=False)
            if not mask.any() and q:
                mask = text.str.contains(q, na=False, regex=False)
            work = work[mask]

    grouped = (
        work.groupby(["object_name", "object_type", "kcsr", "kvr", "dopkr"], dropna=False)
        .agg(facts=("amount", "count"), total=("amount", "sum"))
        .reset_index()
        .sort_values("total", ascending=False)
        .head(limit)
    )
    out = []
    for _, r in grouped.iterrows():
        out.append({
            "id": f"{r['object_type']}|{r['kcsr']}|{r['dopkr']}|{r['object_name']}",
            "name": r["object_name"] or "(без названия)",
            "type": r["object_type"],
            "kcsr": r["kcsr"] or "",
            "kvr": r["kvr"] or "",
            "dopkr": r["dopkr"] or "",
            "facts": int(r["facts"]),
            "total": float(r["total"]),
        })
    return out


def _risk_for_row(row: dict[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    level = "green"

    limit = float(row.get("limit_subject") or 0)
    cash = float(row.get("cash_subject") or 0)
    bo = float(row.get("bo_subject") or 0)
    contracts = float(row.get("contract_amount") or 0)
    exec_pct = row.get("exec_pct")
    exec_num = float(exec_pct) if exec_pct is not None else None

    if limit > 0 and cash <= 0:
        level = "red"
        reasons.append("есть лимит, но нет кассовых выплат")
    if exec_num is not None:
        if exec_num < 40 and limit > 0:
            level = "red"
            reasons.append(f"низкое кассовое исполнение: {exec_num:.1f}%")
        elif exec_num < 70 and level != "red":
            level = "yellow"
            reasons.append(f"исполнение ниже 70%: {exec_num:.1f}%")
        elif exec_num > 105:
            level = "red"
            reasons.append(f"исполнение выше лимита: {exec_num:.1f}%")
        elif exec_num > 95 and level == "green":
            level = "yellow"
            reasons.append(f"исполнение близко к лимиту: {exec_num:.1f}%")
    if limit > 0 and bo > limit * 1.01:
        level = "red"
        reasons.append("БО больше лимита")
    if limit > 0 and contracts > 0:
        gap = limit - contracts
        if gap > limit * 0.5 and level != "red":
            level = "yellow"
            reasons.append("контракты закрывают меньше половины лимита")

    if not reasons:
        reasons.append("критичных отклонений не найдено")

    return {
        "risk_level": level,
        "risk_label": RISK_META[level]["title"],
        "risk_reasons": reasons,
    }


def _build_analytics(summary: list[dict[str, Any]], totals: dict[str, float]) -> list[str]:
    if not summary:
        return []

    limit = float(totals.get("limit_subject") or 0)
    cash = float(totals.get("cash_subject") or 0)
    contracts = float(totals.get("contract_amount") or 0)
    exec_pct = (cash / limit * 100) if limit else 0

    no_cash = sum(1 for row in summary if float(row.get("limit_subject") or 0) > 0 and float(row.get("cash_subject") or 0) <= 0)
    red = sum(1 for row in summary if row.get("risk_level") == "red")
    yellow = sum(1 for row in summary if row.get("risk_level") == "yellow")
    contract_gap = limit - contracts if limit or contracts else 0

    def rub(value: float) -> str:
        text = f"{value:,.1f}".replace(",", " ").replace(".", ",")
        return f"{text} ₽"

    out: list[str] = []
    if limit:
        out.append(f"По выбранным объектам общий лимит составляет {rub(limit)}.")
    if cash or limit:
        out.append(f"Кассовое исполнение — {rub(cash)}, или {exec_pct:.1f}%.".replace(".", ",", 1))
    if no_cash:
        out.append(f"Есть {no_cash} объект(ов) с лимитом, но без кассовых выплат.")
    if contracts:
        direction = "меньше" if contract_gap >= 0 else "больше"
        out.append(f"Сумма контрактов {direction} лимита на {rub(abs(contract_gap))}.")
    if red:
        out.append(f"По {red} объект(ам) наблюдается высокий риск неисполнения.")
    elif yellow:
        out.append(f"{yellow} объект(ов) требуют внимания по индикаторам риска.")
    else:
        out.append("Критичных отклонений по выбранным объектам не выявлено.")
    return out


def _filter_by_objects(df: pd.DataFrame, objects: list[str]) -> pd.DataFrame:
    if not objects:
        return df
    keys = []
    for obj_id in objects:
        parts = obj_id.split("|", 3)
        while len(parts) < 4:
            parts.append("")
        keys.append(tuple(parts))
    obj_keys = pd.DataFrame(keys, columns=["object_type", "kcsr", "dopkr", "object_name"])
    df_keyed = df.assign(
        kcsr_key=df["kcsr"].fillna(""),
        dopkr_key=df["dopkr"].fillna(""),
        oname_key=df["object_name"].fillna(""),
        otype_key=df["object_type"].fillna(""),
    )
    merged = df_keyed.merge(
        obj_keys.rename(columns={
            "object_type": "otype_key",
            "kcsr": "kcsr_key",
            "dopkr": "dopkr_key",
            "object_name": "oname_key",
        }),
        on=["otype_key", "kcsr_key", "dopkr_key", "oname_key"],
        how="inner",
    )
    return merged.drop(columns=["otype_key", "kcsr_key", "dopkr_key", "oname_key"])


def _filter_by_period(df: pd.DataFrame, period: dict[str, Any] | None) -> pd.DataFrame:
    if df.empty or not period:
        return df
    ptype = period.get("type", "all")
    if ptype == "all":
        return df
    if ptype == "as_of":
        d = pd.to_datetime(period.get("date"), errors="coerce")
        if pd.isna(d):
            return df
        return df[df["date"] <= d]
    if ptype == "range":
        d1 = pd.to_datetime(period.get("date_from"), errors="coerce")
        d2 = pd.to_datetime(period.get("date_to"), errors="coerce")
        out = df
        if not pd.isna(d1):
            out = out[out["date"] >= d1]
        if not pd.isna(d2):
            out = out[out["date"] <= d2]
        return out
    if ptype == "compare":
        d1 = pd.to_datetime(period.get("date_a"), errors="coerce")
        d2 = pd.to_datetime(period.get("date_b"), errors="coerce")
        if pd.isna(d1) and pd.isna(d2):
            return df
        # Включаем все факты по более позднюю дату — динамика по месяцам
        # позволит фронтенду собрать снимки A и B.
        upper = max([d for d in (d1, d2) if not pd.isna(d)])
        return df[df["date"] <= upper]
    return df


def build_selection(df: pd.DataFrame, payload: dict[str, Any]) -> dict[str, Any]:
    """Строит сводную таблицу + динамику по запросу пользователя."""
    if df.empty:
        return {"summary": [], "dynamic": [], "details": [], "totals": {}, "analytics": [], "risk_counts": {}, "params": payload}

    work = df
    section = payload.get("section")
    if section:
        work = apply_section_filter(work, section)

    objects = payload.get("objects") or []
    if objects:
        work = _filter_by_objects(work, objects)

    metrics = payload.get("metrics") or []
    if metrics:
        work = work[work["metric_code"].isin(metrics)]

    work = _filter_by_period(work, payload.get("period"))

    work = work.copy()
    work["object_key"] = work["object_name"].fillna("(без названия)")

    if work.empty:
        return {"summary": [], "dynamic": [], "details": [], "totals": {}, "analytics": [], "risk_counts": {}, "params": payload}

    pivot = work.pivot_table(
        index="object_key",
        columns="metric_code",
        values="amount",
        aggfunc="sum",
        fill_value=0.0,
    )
    pivot = pivot.reset_index()

    metric_columns = [c for c in pivot.columns if c != "object_key"]
    for code in metric_columns:
        pivot[code] = pivot[code].astype(float)

    if "limit_subject" in pivot.columns and "cash_subject" in pivot.columns:
        pivot["exec_pct"] = (pivot["cash_subject"] / pivot["limit_subject"].replace(0, pd.NA)) * 100
        pivot["exec_pct"] = pivot["exec_pct"].fillna(0).round(2)
    if "limit_subject" in pivot.columns and "contract_amount" in pivot.columns:
        pivot["uncontracted"] = pivot["limit_subject"] - pivot["contract_amount"]
    if "bo_subject" in pivot.columns and "cash_subject" in pivot.columns:
        pivot["unpaid_bo"] = pivot["bo_subject"] - pivot["cash_subject"]
    if "contract_amount" in pivot.columns and "payment_amount" in pivot.columns:
        pivot["contract_remainder"] = pivot["contract_amount"] - pivot["payment_amount"]

    summary = pivot.rename(columns={"object_key": "object"}).to_dict(orient="records")
    for row in summary:
        row.update(_risk_for_row(row))

    dynamic_df = (
        work.assign(month=work["date"].dt.strftime("%Y-%m").fillna("без даты"))
        .groupby(["month", "metric_code"], dropna=False)["amount"]
        .sum()
        .reset_index()
    )
    dyn_pivot = dynamic_df.pivot_table(
        index="month", columns="metric_code", values="amount", fill_value=0.0
    ).reset_index().sort_values("month")
    dynamic = dyn_pivot.to_dict(orient="records")

    metric_lookup = {m["code"]: m["name"] for m in METRICS}

    details_df = work.sort_values(["date", "amount"], ascending=[False, False]).head(2000).copy()
    details_df["date_str"] = pd.to_datetime(details_df["date"], errors="coerce").dt.strftime("%Y-%m-%d").fillna("")
    detail_cols = [
        "object_name", "source", "metric_code", "metric_name", "amount",
        "date_str", "doc_type", "doc_no", "counterparty", "kcsr", "kvr",
        "dopkr", "dopkr_name", "budget_name",
    ]
    for col in detail_cols:
        if col not in details_df.columns:
            details_df[col] = ""
    details = (
        details_df[detail_cols]
        .rename(columns={"date_str": "date"})
        .to_dict(orient="records")
    )

    totals: dict[str, float] = {
        code: float(pd.to_numeric(pivot[code], errors="coerce").fillna(0).sum())
        for code in metric_columns
    }

    metric_meta = []
    for code in metric_columns:
        metric_meta.append({"code": code, "name": metric_lookup.get(code, code)})

    risk_counts = {level: 0 for level in RISK_META}
    for row in summary:
        level = row.get("risk_level", "green")
        risk_counts[level] = risk_counts.get(level, 0) + 1

    return {
        "summary": summary,
        "dynamic": dynamic,
        "details": details,
        "totals": totals,
        "metric_meta": metric_meta,
        "analytics": _build_analytics(summary, totals),
        "risk_counts": risk_counts,
        "params": payload,
    }
