"""Конфигурация: пути, каталог метрик, правила разделов."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = Path(os.environ.get(
    "BK_DATA_DIR",
    str(ROOT / "Кейс_ Интеллектуальный отбор данных (БФТ, Минфин АО)"),
))

RCHB_DIR = DATA_DIR / "1. РЧБ"
AGREEMENTS_DIR = DATA_DIR / "2. Соглашения"
GZ_DIR = DATA_DIR / "3. ГЗ"
BUAU_DIR = DATA_DIR / "4. Выгрузка БУАУ"

MONTH_MAP = {
    "январь": 1, "февраль": 2, "март": 3, "апрель": 4,
    "май": 5, "июнь": 6, "июль": 7, "август": 8,
    "сентябрь": 9, "октябрь": 10, "ноябрь": 11, "декабрь": 12,
}

DOCUMENTCLASS_MAP = {
    273: ("agreement_mbt", "Соглашения МБТ"),
    313: ("agreement_subsidy_jur", "Субсидии ЮЛ/ИП/ФЛ"),
    278: ("agreement_subsidy_buau", "Субсидии БУ/АУ (иные цели)"),
    272: ("agreement_task", "Соглашения по гос/мун. заданиям"),
}

METRICS = [
    {"code": "limit_subject", "name": "Лимит бюджета субъекта РФ", "source": "planning", "group": "Финансовый минимум"},
    {"code": "bo_subject", "name": "Принятые БО бюджета субъекта РФ", "source": "planning", "group": "Финансовый минимум"},
    {"code": "cash_subject", "name": "Кассовые выплаты бюджета субъекта РФ", "source": "planning", "group": "Финансовый минимум"},
    {"code": "ostatok_subject", "name": "Остаток лимита субъекта РФ", "source": "planning", "group": "Исполнение"},

    {"code": "limit_municipal", "name": "Лимит местных бюджетов", "source": "planning", "group": "Финансовый минимум"},
    {"code": "bo_municipal", "name": "Принятые БО местных бюджетов", "source": "planning", "group": "Финансовый минимум"},
    {"code": "cash_municipal", "name": "Кассовые выплаты местных бюджетов", "source": "planning", "group": "Финансовый минимум"},
    {"code": "ostatok_municipal", "name": "Остаток лимита местных бюджетов", "source": "planning", "group": "Исполнение"},

    {"code": "agreement_mbt", "name": "Соглашения МБТ", "source": "agreements", "group": "Контрактование"},
    {"code": "agreement_subsidy_jur", "name": "Субсидии ЮЛ/ИП/ФЛ", "source": "agreements", "group": "Контрактование"},
    {"code": "agreement_subsidy_buau", "name": "Субсидии БУ/АУ (иные цели)", "source": "agreements", "group": "Контрактование"},
    {"code": "agreement_task", "name": "Соглашения по заданиям", "source": "agreements", "group": "Контрактование"},

    {"code": "contract_amount", "name": "Сумма контрактов / договоров", "source": "procurement", "group": "Контрактование"},
    {"code": "payment_amount", "name": "Платежи по контрактам", "source": "procurement", "group": "Финансовый минимум"},

    {"code": "buau_pay", "name": "Выплаты БУ/АУ (с учетом возврата)", "source": "buau", "group": "Финансовый минимум"},
]

METRIC_PRESETS = {
    "min_finance": {
        "title": "Финансовый минимум",
        "metrics": ["limit_subject", "bo_subject", "cash_subject"],
    },
    "contracting": {
        "title": "Контрактование",
        "metrics": ["bo_subject", "contract_amount", "agreement_mbt", "agreement_subsidy_buau", "agreement_subsidy_jur"],
    },
    "execution": {
        "title": "Исполнение",
        "metrics": ["limit_subject", "cash_subject", "ostatok_subject", "payment_amount"],
    },
    "full": {
        "title": "Полный срез",
        "metrics": [m["code"] for m in METRICS],
    },
}

SECTION_RULES = {
    "kik": {
        "title": "Раздел 1. КИК",
        "kcsr_substring": (5, 3, "978"),
    },
    "skk": {
        "title": "Раздел 2. СКК",
        "kcsr_substring": (5, 4, "6105"),
    },
    "two_thirds": {
        "title": "Раздел 3. 2/3",
        "kcsr_substring": (5, 3, "970"),
    },
    "okv": {
        "title": "Раздел 4. Объекты капитальных вложений",
        "dopkr_not_null": True,
        "kvr_in": ["464", "460", "461", "462", "463", "465", "466", "400", "406", "407", "408"],
    },
}

DERIVED = [
    {"code": "exec_pct", "name": "% кассового исполнения", "formula": "cash_subject / limit_subject * 100"},
    {"code": "ostatok_calc", "name": "Остаток лимита (расч.)", "formula": "limit_subject - cash_subject"},
    {"code": "uncontracted", "name": "Неконтрактованный остаток", "formula": "limit_subject - contract_amount"},
    {"code": "unpaid_bo", "name": "Неоплаченные обязательства", "formula": "bo_subject - cash_subject"},
    {"code": "contract_remainder", "name": "Остаток по контрактам", "formula": "contract_amount - payment_amount"},
    {"code": "contract_share", "name": "Доля контрактования, %", "formula": "contract_amount / limit_subject * 100"},
]
