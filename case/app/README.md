# Бюджетный конструктор выборок

Веб-приложение для интеллектуального отбора данных из АЦК-Планирование (РЧБ),
АЦК-Финансы (Соглашения, БУ/АУ) и АЦК-Госзаказ. Загружает CSV/XLSX-выгрузки,
приводит к единой модели фактов и предоставляет конструктор выборок с таблицей,
графиками и экспортом в Excel.

## Запуск

```bash
pip install -r requirements.txt
run.bat                              # Windows
# или
python -m uvicorn main:app --app-dir backend --port 8765
```

Затем откройте http://127.0.0.1:8765/

## Опциональный режим PostgreSQL

По умолчанию приложение читает CSV/XLSX из папки `Кейс_…`. При желании
можно подключить PostgreSQL — факты будут сохраняться в БД и читаться
оттуда при следующих запусках:

```bash
pip install sqlalchemy "psycopg[binary]"
set BK_DATABASE_URL=postgresql+psycopg://user:pass@127.0.0.1:5432/budget
run.bat
```

При первом запуске факты загружаются из CSV и кладутся в таблицу
`bk_facts` (имя меняется через `BK_DATABASE_TABLE`). При следующих —
читаются из PG. Кнопка «Перечитать» в шапке принудительно перечитывает
CSV и переписывает таблицу. Если переменная `BK_DATABASE_URL` не
задана — режим выключен и приложение работает строго на файлах.

## Новый UI (с версии 1.1)

- Светлая и тёмная темы (переключатель в шапке, сохраняется).
- Выбор раздела/типов чипами + сегментированный переключатель периода.
- KPI-плашки с источником, мини-полосы % исполнения в сводной таблице.
- Сохранение пользовательских пресетов (хранятся в localStorage).
- Снимки A↔B при сравнении двух дат, тосты с ошибками.
- Адаптив: одна колонка на ≤1100 px, упрощённые ряды на телефонах.

## Источники данных

По умолчанию читаются папки рядом с проектом:

- `Кейс_ Интеллектуальный отбор данных (БФТ, Минфин АО)/1. РЧБ/`
- `.../2. Соглашения/`
- `.../3. ГЗ/`
- `.../4. Выгрузка БУАУ/`

Путь настраивается в `backend/config.py` (`DATA_DIR`).

## Архитектура

```
CSV / XLSX
    │
    ▼
backend/etl.py        ─ нормализация в DataFrame фактов
backend/selection.py  ─ фильтры, агрегация, расчётные показатели
backend/excel_export.py ─ многолистовой XLSX (с диаграммой)
backend/main.py       ─ FastAPI, статика, REST API
frontend/             ─ Vue 3 + Chart.js (без сборки)
```

### Модель фактов

Каждый факт — строка с полями:
`source, date, period_month, budget_name, budget_level, kfsr, kcsr, kvr, kosgu,
kvfo, dopkr, dopkr_name, object_name, object_type, counterparty, doc_no, doc_type,
metric_code, metric_name, amount`.

### Каталог показателей

`limit_subject / bo_subject / cash_subject / ostatok_subject`
`limit_municipal / bo_municipal / cash_municipal / ostatok_municipal`
`agreement_mbt / agreement_subsidy_jur / agreement_subsidy_buau / agreement_task`
`contract_amount / payment_amount / buau_pay`

Расчётные: `% исполнения, неконтрактованный остаток, неоплаченные БО,
остаток по контрактам`.

### Разделы контрольного примера

Заданы декларативно в `config.SECTION_RULES`:
- **КИК** — позиции 6-8 КЦСР = `978`
- **СКК** — позиции 6-9 КЦСР = `6105`
- **2/3** — позиции 6-8 КЦСР = `970`
- **ОКВ** — `dopkr_code is not null` + КВР ∈ {464, 460, 461, …}

Чтобы добавить новый раздел — допишите запись в `SECTION_RULES`,
никаких правок кода не нужно.

## API

```
GET  /api/health           — статистика загруженных фактов
GET  /api/object_types     — типы объектов с количеством
GET  /api/objects?q=&section=&types=  — поиск объектов
GET  /api/metrics          — каталог метрик и пресеты
GET  /api/sections         — правила разделов
POST /api/selection        — построить выборку
POST /api/export           — XLSX (Параметры/Сводная/Динамика/Детализация/Справочник)
POST /api/reload           — перечитать данные с диска
```

Запрос `selection`:

```json
{
  "objects": ["kcsr_event|02.2.01.97003||..."],
  "metrics": ["limit_subject", "bo_subject", "cash_subject", "contract_amount"],
  "section": "okv",
  "period": { "type": "range", "date_from": "2025-01-01", "date_to": "2025-12-31" }
}
```
