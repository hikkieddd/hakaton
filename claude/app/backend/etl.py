"""ETL: загрузка и нормализация CSV/XLSX из АЦК-Планирование, АЦК-Финансы и АЦК-Госзаказ."""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Iterable

import pandas as pd

from config import (
    AGREEMENTS_DIR, BUAU_DIR, DOCUMENTCLASS_MAP, GZ_DIR, MONTH_MAP, RCHB_DIR,
)


def _to_amount(val) -> float:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().replace("\xa0", "").replace(" ", "")
    if not s or s in ("-", "—"):
        return 0.0
    s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _parse_date(val) -> pd.Timestamp | None:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    if isinstance(val, (pd.Timestamp, datetime)):
        try:
            return pd.Timestamp(val).normalize()
        except Exception:
            return None
    s = str(val).strip()
    if not s or s in ("-", "—", "NaT", "nan", "None"):
        return None
    for fmt in (
        "%d.%m.%Y", "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M",
        "%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f",
        "%d/%m/%Y", "%Y/%m/%d",
    ):
        try:
            return pd.Timestamp(datetime.strptime(s, fmt)).normalize()
        except (ValueError, TypeError):
            continue
    try:
        ts = pd.to_datetime(s, errors="coerce", dayfirst=True)
        if pd.isna(ts):
            return None
        return ts.normalize()
    except Exception:
        return None


def _budget_level(budget_name: str) -> str:
    if not budget_name:
        return "unknown"
    s = budget_name.lower()
    if "областной" in s or "субъект" in s:
        return "subject"
    if "консолид" in s:
        return "consolidated"
    return "municipal"


def _filename_period(name: str) -> tuple[int, int] | None:
    """Извлекает (год, месяц) из имени РЧБ-файла, например 'январь2025.csv' → (2025, 1)."""
    m = re.match(r"([а-яё]+)(\d{4})", name.lower())
    if not m:
        return None
    month = MONTH_MAP.get(m.group(1))
    if not month:
        return None
    return int(m.group(2)), month


def _agreements_period(name: str) -> pd.Timestamp | None:
    """Из имени файла соглашений 'на01022025.csv' извлекает дату."""
    m = re.search(r"на(\d{2})(\d{2})(\d{4})", name)
    if m:
        d, mo, y = m.groups()
        try:
            return pd.Timestamp(int(y), int(mo), int(d))
        except ValueError:
            return None
    m = re.search(r"(\d{2})(\d{2})(\d{4})-(\d{2})(\d{2})(\d{4})", name)
    if m:
        d2, mo2, y2 = m.group(4), m.group(5), m.group(6)
        try:
            return pd.Timestamp(int(y2), int(mo2), int(d2))
        except ValueError:
            return None
    return None


def _read_rchb_csv(path: Path) -> pd.DataFrame:
    """Читает РЧБ-файл, пропуская служебный заголовок, ищет строку 'Бюджет;Дата проводки'."""
    raw = path.read_text(encoding="utf-8", errors="replace").splitlines()
    header_idx = None
    for i, line in enumerate(raw[:30]):
        if line.startswith("Бюджет;Дата проводки"):
            header_idx = i
            break
    if header_idx is None:
        return pd.DataFrame()
    data = "\n".join(raw[header_idx:])
    from io import StringIO
    df = pd.read_csv(StringIO(data), sep=";", dtype=str, keep_default_na=False, engine="python")
    df.columns = [c.strip() for c in df.columns]
    return df


def _find_col(df: pd.DataFrame, *needles: str) -> str | None:
    for col in df.columns:
        low = col.lower()
        for n in needles:
            if n.lower() in low:
                return col
    return None


def load_rchb() -> pd.DataFrame:
    """Загружает все месячные файлы АЦК-Планирование (РЧБ) и нормализует в факты."""
    files = sorted(RCHB_DIR.glob("*.csv"))
    if not files:
        return pd.DataFrame()

    by_year: dict[int, list[tuple[int, Path]]] = {}
    for p in files:
        per = _filename_period(p.stem)
        if not per:
            continue
        by_year.setdefault(per[0], []).append((per[1], p))

    rows: list[dict] = []
    for year, items in by_year.items():
        items.sort()
        latest_month, latest_file = items[-1]
        df = _read_rchb_csv(latest_file)
        if df.empty:
            continue

        c_budget = _find_col(df, "Бюджет")
        c_date = _find_col(df, "Дата проводки")
        c_kfsr = _find_col(df, "КФСР") or ""
        c_kfsr_n = _find_col(df, "Наименование КФСР") or ""
        c_kcsr = _find_col(df, "КЦСР") or ""
        c_kcsr_n = _find_col(df, "Наименование КЦСР") or ""
        c_kvr = _find_col(df, "КВР") or ""
        c_kvr_n = _find_col(df, "Наименование КВР") or ""
        c_kvsr = _find_col(df, "КВСР") or ""
        c_kvsr_n = _find_col(df, "Наименование КВСР") or ""
        c_kosgu = _find_col(df, "КОСГУ") or ""
        c_kvfo = _find_col(df, "КВФО") or ""
        c_dopkr = _find_col(df, "Код цели") or _find_col(df, "ДопКР") or ""
        c_dopkr_n = _find_col(df, "Наименование Код цели") or _find_col(df, "Наименование ДопКР") or ""
        c_source = _find_col(df, "Источник средств") or ""

        c_limit = _find_col(df, "Лимиты ПБС")
        c_bo = _find_col(df, "Подтв. лимитов по БО")
        c_ostatok = _find_col(df, "Остаток лимитов")
        c_cash = _find_col(df, "Всего выбытий")

        for _, r in df.iterrows():
            budget_name = (r.get(c_budget) or "").strip() if c_budget else ""
            if not budget_name or budget_name.lower().startswith("итого"):
                continue
            level = _budget_level(budget_name)
            date = _parse_date(r.get(c_date)) if c_date else None
            kcsr = (r.get(c_kcsr) or "").strip() if c_kcsr else ""
            kcsr_n = (r.get(c_kcsr_n) or "").strip() if c_kcsr_n else ""
            dopkr = (r.get(c_dopkr) or "").strip() if c_dopkr else ""
            dopkr_n = (r.get(c_dopkr_n) or "").strip() if c_dopkr_n else ""
            kvr = (r.get(c_kvr) or "").strip() if c_kvr else ""
            kvr_n = (r.get(c_kvr_n) or "").strip() if c_kvr_n else ""

            if dopkr_n and dopkr_n.lower() not in ("не указан", "0"):
                object_name = dopkr_n
                object_type = "capital_object"
            elif kcsr_n:
                object_name = kcsr_n
                object_type = "kcsr_event"
            else:
                object_name = f"КЦСР {kcsr}" if kcsr else budget_name
                object_type = "kcsr_event"

            base = {
                "source": "planning",
                "date": date,
                "snapshot_year": year,
                "budget_name": budget_name,
                "budget_level": level,
                "kfsr": (r.get(c_kfsr) or "").strip() if c_kfsr else "",
                "kfsr_name": (r.get(c_kfsr_n) or "").strip() if c_kfsr_n else "",
                "kcsr": kcsr,
                "kcsr_name": kcsr_n,
                "kvr": kvr,
                "kvr_name": kvr_n,
                "kvsr": (r.get(c_kvsr) or "").strip() if c_kvsr else "",
                "kvsr_name": (r.get(c_kvsr_n) or "").strip() if c_kvsr_n else "",
                "kosgu": (r.get(c_kosgu) or "").strip() if c_kosgu else "",
                "kvfo": (r.get(c_kvfo) or "").strip() if c_kvfo else "",
                "dopkr": dopkr,
                "dopkr_name": dopkr_n,
                "source_funds": (r.get(c_source) or "").strip() if c_source else "",
                "object_name": object_name,
                "object_type": object_type,
                "counterparty": (r.get(c_kvsr_n) or "").strip() if c_kvsr_n else "",
                "doc_no": "",
                "doc_type": "",
            }

            metric_pairs = []
            if c_limit:
                metric_pairs.append((
                    "limit_subject" if level == "subject" else "limit_municipal",
                    "Лимит бюджета субъекта РФ" if level == "subject" else "Лимит местных бюджетов",
                    _to_amount(r.get(c_limit)),
                ))
            if c_bo:
                metric_pairs.append((
                    "bo_subject" if level == "subject" else "bo_municipal",
                    "Принятые БО (субъект)" if level == "subject" else "Принятые БО (местные)",
                    _to_amount(r.get(c_bo)),
                ))
            if c_ostatok:
                metric_pairs.append((
                    "ostatok_subject" if level == "subject" else "ostatok_municipal",
                    "Остаток лимита (субъект)" if level == "subject" else "Остаток лимита (местные)",
                    _to_amount(r.get(c_ostatok)),
                ))
            if c_cash:
                metric_pairs.append((
                    "cash_subject" if level == "subject" else "cash_municipal",
                    "Касса (субъект)" if level == "subject" else "Касса (местные)",
                    _to_amount(r.get(c_cash)),
                ))

            for code, name, amt in metric_pairs:
                if amt == 0:
                    continue
                row = dict(base)
                row.update({"metric_code": code, "metric_name": name, "amount": amt})
                rows.append(row)
    return pd.DataFrame(rows)


def load_agreements() -> pd.DataFrame:
    files = sorted(AGREEMENTS_DIR.glob("*.csv"))
    rows: list[dict] = []
    for path in files:
        try:
            df = pd.read_csv(path, dtype=str, keep_default_na=False)
        except Exception:
            try:
                df = pd.read_csv(path, dtype=str, keep_default_na=False, sep=";")
            except Exception:
                continue
        if df.empty:
            continue
        df.columns = [c.strip().lower() for c in df.columns]
        for _, r in df.iterrows():
            try:
                doc_class = int(str(r.get("documentclass_id", "0")).strip() or 0)
            except ValueError:
                doc_class = 0
            metric_code, metric_name = DOCUMENTCLASS_MAP.get(doc_class, ("agreement_other", "Соглашения (прочее)"))
            close_date = _parse_date(r.get("close_date") or r.get("main_close_date"))
            amount = _to_amount(r.get("amount_1year"))
            if amount == 0:
                continue
            kcsr = (r.get("kcsr_code") or "").strip()
            kvr = (r.get("kvr_code") or "").strip()
            dopkr = (r.get("dd_purposefulgrant_code") or r.get("dd_grantinvestment_code") or "").strip()
            recipient = (r.get("dd_recipient_caption") or r.get("dd_recepient_caption") or "").strip()
            level = "subject" if "областн" in (r.get("caption", "") or "").lower() else "municipal"
            rows.append({
                "source": "agreements",
                "date": close_date,
                "snapshot_year": close_date.year if close_date is not None else None,
                "budget_name": (r.get("caption") or "").strip(),
                "budget_level": level,
                "kfsr": (r.get("kfsr_code") or "").strip(),
                "kfsr_name": "",
                "kcsr": kcsr,
                "kcsr_name": "",
                "kvr": kvr,
                "kvr_name": "",
                "kvsr": "",
                "kvsr_name": "",
                "kosgu": (r.get("kesr_code") or "").strip(),
                "kvfo": "",
                "dopkr": dopkr,
                "dopkr_name": "",
                "source_funds": "",
                "object_name": recipient or f"Соглашение по КЦСР {kcsr}",
                "object_type": "agreement",
                "counterparty": recipient,
                "doc_no": (r.get("reg_number") or "").strip(),
                "doc_type": metric_name,
                "metric_code": metric_code,
                "metric_name": metric_name,
                "amount": amount,
            })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df.drop_duplicates(subset=["doc_no", "date", "metric_code", "amount", "kcsr"], keep="first")
    return df


def load_procurement() -> pd.DataFrame:
    contracts_path = GZ_DIR / "Контракты и договора.csv"
    lines_path = GZ_DIR / "Бюджетные строки.csv"
    pays_path = GZ_DIR / "Платежки.csv"

    rows: list[dict] = []
    if not contracts_path.exists():
        return pd.DataFrame(rows)

    contracts = pd.read_csv(contracts_path, dtype=str, keep_default_na=False)
    contracts.columns = [c.strip().lower() for c in contracts.columns]

    lines = pd.DataFrame()
    if lines_path.exists():
        lines = pd.read_csv(lines_path, dtype=str, keep_default_na=False)
        lines.columns = [c.strip().lower() for c in lines.columns]
        lines = lines.drop_duplicates(subset=["con_document_id"], keep="first")

    pays = pd.DataFrame()
    if pays_path.exists():
        pays = pd.read_csv(pays_path, dtype=str, keep_default_na=False)
        pays.columns = [c.strip().lower() for c in pays.columns]

    line_index = {}
    if not lines.empty:
        for _, lr in lines.iterrows():
            line_index[str(lr.get("con_document_id", "")).strip()] = lr

    for _, r in contracts.iterrows():
        cid = str(r.get("con_document_id", "")).strip()
        date = _parse_date(r.get("con_date"))
        amt = _to_amount(r.get("con_amount"))
        number = (r.get("con_number") or "").strip()
        zakaz = (r.get("zakazchik_key") or "").strip()
        line = line_index.get(cid)
        kcsr = (line.get("kcsr_code") if line is not None else "") or ""
        kvr = (line.get("kvr_code") if line is not None else "") or ""
        kfsr = (line.get("kfsr_code") if line is not None else "") or ""
        purposefulgrant = (line.get("purposefulgrant") if line is not None else "") or ""
        kde = (line.get("kde_code") if line is not None else "") or ""
        if amt:
            rows.append({
                "source": "procurement",
                "date": date,
                "snapshot_year": date.year if date is not None else None,
                "budget_name": "",
                "budget_level": "subject",
                "kfsr": kfsr.strip(),
                "kfsr_name": "",
                "kcsr": kcsr.strip(),
                "kcsr_name": "",
                "kvr": kvr.strip(),
                "kvr_name": "",
                "kvsr": "",
                "kvsr_name": "",
                "kosgu": "",
                "kvfo": "",
                "dopkr": kde.strip(),
                "dopkr_name": purposefulgrant.strip(),
                "source_funds": "",
                "object_name": purposefulgrant.strip() or f"Контракт {number}",
                "object_type": "contract_object",
                "counterparty": zakaz,
                "doc_no": number,
                "doc_type": "Контракт",
                "metric_code": "contract_amount",
                "metric_name": "Сумма контрактов / договоров",
                "amount": amt,
            })

    if not pays.empty:
        for _, p in pays.iterrows():
            cid = str(p.get("con_document_id", "")).strip()
            date = _parse_date(p.get("platezhka_paydate"))
            amt = _to_amount(p.get("platezhka_amount"))
            num = (p.get("platezhka_num") or "").strip()
            line = line_index.get(cid)
            kcsr = (line.get("kcsr_code") if line is not None else "") or ""
            kvr = (line.get("kvr_code") if line is not None else "") or ""
            kfsr = (line.get("kfsr_code") if line is not None else "") or ""
            purposefulgrant = (line.get("purposefulgrant") if line is not None else "") or ""
            kde = (line.get("kde_code") if line is not None else "") or ""
            if amt == 0:
                continue
            rows.append({
                "source": "procurement",
                "date": date,
                "snapshot_year": date.year if date is not None else None,
                "budget_name": "",
                "budget_level": "subject",
                "kfsr": kfsr.strip(),
                "kfsr_name": "",
                "kcsr": kcsr.strip(),
                "kcsr_name": "",
                "kvr": kvr.strip(),
                "kvr_name": "",
                "kvsr": "",
                "kvsr_name": "",
                "kosgu": "",
                "kvfo": "",
                "dopkr": kde.strip(),
                "dopkr_name": purposefulgrant.strip(),
                "source_funds": "",
                "object_name": purposefulgrant.strip() or f"Платеж по контракту {cid}",
                "object_type": "contract_object",
                "counterparty": "",
                "doc_no": num,
                "doc_type": "Платежка",
                "metric_code": "payment_amount",
                "metric_name": "Платежи по контрактам",
                "amount": amt,
            })

    return pd.DataFrame(rows)


def load_buau() -> pd.DataFrame:
    files = sorted(BUAU_DIR.glob("*.csv"))
    rows: list[dict] = []
    for path in files:
        try:
            df = pd.read_csv(path, dtype=str, keep_default_na=False, sep=";")
        except Exception:
            continue
        if df.empty:
            continue
        df.columns = [c.strip() for c in df.columns]
        for _, r in df.iterrows():
            budget_name = (r.get("Бюджет") or "").strip()
            if not budget_name or budget_name.lower().startswith("итого"):
                continue
            date = _parse_date(r.get("Дата проводки"))
            amount = _to_amount(r.get("Выплаты с учетом возврата") or r.get("Выплаты - Исполнение"))
            if amount == 0:
                continue
            rows.append({
                "source": "buau",
                "date": date,
                "snapshot_year": date.year if date is not None else None,
                "budget_name": budget_name,
                "budget_level": _budget_level(budget_name),
                "kfsr": (r.get("КФСР") or "").strip(),
                "kfsr_name": "",
                "kcsr": (r.get("КЦСР") or "").strip(),
                "kcsr_name": "",
                "kvr": (r.get("КВР") or "").strip(),
                "kvr_name": "",
                "kvsr": "",
                "kvsr_name": "",
                "kosgu": (r.get("КОСГУ") or "").strip(),
                "kvfo": (r.get("КВФО") or "").strip(),
                "dopkr": (r.get("Код субсидии") or "").strip(),
                "dopkr_name": (r.get("Отраслевой код") or "").strip(),
                "source_funds": "",
                "object_name": (r.get("Организация") or "").strip(),
                "object_type": "buau_org",
                "counterparty": (r.get("Орган, предоставляющий субсидии") or "").strip(),
                "doc_no": "",
                "doc_type": "Выплата БУ/АУ",
                "metric_code": "buau_pay",
                "metric_name": "Выплаты БУ/АУ (с учетом возврата)",
                "amount": amount,
            })
    return pd.DataFrame(rows)


def load_all() -> pd.DataFrame:
    parts = []
    for fn in (load_rchb, load_agreements, load_procurement, load_buau):
        try:
            df = fn()
            if not df.empty:
                parts.append(df)
                print(f"[etl] {fn.__name__}: {len(df)} facts loaded")
        except Exception as exc:
            print(f"[etl] {fn.__name__} failed: {exc}")
    if not parts:
        return pd.DataFrame()
    df = pd.concat(parts, ignore_index=True, sort=False)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["period_month"] = df["date"].dt.strftime("%Y-%m").fillna("")
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
    return df
