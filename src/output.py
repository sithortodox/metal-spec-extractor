# Модуль сохранения результатов в форматах Excel, CSV и JSON

import json
import logging
from dataclasses import asdict
from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
from openpyxl.utils import get_column_letter

from .parser import SpecItem

logger = logging.getLogger(__name__)

# Поля данных спецификации (в порядке вывода)
ITEM_FIELDS = [
    "position", "parent_position", "level", "name", "designation",
    "profile", "steel_grade", "quantity", "length", "mass_single",
    "mass_total", "note", "page_number",
]

# Заголовки колонок на русском для отображения
DISPLAY_HEADERS = [
    "Поз.", "Поз. родителя", "Уровень", "Наименование", "Обозначение",
    "Профиль/Сечение", "Марка стали", "Кол-во", "Длина, мм",
    "Масса ед., кг", "Масса общ., кг", "Примечание", "Страница",
]


def items_to_dataframe(items: list[SpecItem]) -> pd.DataFrame:
    """Преобразует список позиций в DataFrame."""
    rows = []
    for item in items:
        d = asdict(item)
        rows.append({field: d[field] for field in ITEM_FIELDS})
    df = pd.DataFrame(rows, columns=ITEM_FIELDS)
    df.columns = DISPLAY_HEADERS
    return df


def save_csv(items: list[SpecItem], output_path: str | Path) -> Path:
    """Сохраняет спецификацию в CSV-файл (разделитель — точка с запятой)."""
    output_path = Path(output_path)
    df = items_to_dataframe(items)
    df.to_csv(output_path, index=False, encoding="utf-8-sig", sep=";")
    logger.info(f"CSV сохранён: {output_path} ({len(items)} строк)")
    return output_path


def save_json(items: list[SpecItem], output_path: str | Path) -> Path:
    """Сохраняет спецификацию в JSON-файл."""
    output_path = Path(output_path)
    rows = []
    for item in items:
        d = asdict(item)
        rows.append({field: d[field] for field in ITEM_FIELDS})
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    logger.info(f"JSON сохранён: {output_path} ({len(items)} строк)")
    return output_path


def save_excel(items: list[SpecItem], output_path: str | Path) -> Path:
    """Сохраняет спецификацию в Excel-файл с форматированием и сводным листом."""
    output_path = Path(output_path)
    wb = Workbook()
    ws = wb.active
    ws.title = "Спецификация"

    # Стили
    thin_border = Border(
        left=Side(style="thin"),
        right=Side(style="thin"),
        top=Side(style="thin"),
        bottom=Side(style="thin"),
    )

    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    header_font = Font(name="Arial", bold=True, size=10, color="FFFFFF")

    assembly_fill = PatternFill(start_color="D6E4F0", end_color="D6E4F0", fill_type="solid")
    assembly_font = Font(name="Arial", bold=True, size=10)

    detail_font = Font(name="Arial", size=10)

    center_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
    left_align = Alignment(horizontal="left", vertical="center", wrap_text=True)

    # Заголовок таблицы
    for ci, header in enumerate(DISPLAY_HEADERS, 1):
        cell = ws.cell(row=1, column=ci, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = center_align
        cell.border = thin_border

    # Строки данных
    for ri, item in enumerate(items, 2):
        d = asdict(item)
        values = [d[f] for f in ITEM_FIELDS]
        for ci, val in enumerate(values, 1):
            cell = ws.cell(row=ri, column=ci, value=val)
            cell.border = thin_border
            # Выравнивание по центру для числовых и коротких колонок
            if ci <= 3 or ci in (7, 8, 9, 10, 13):
                cell.alignment = center_align
            else:
                cell.alignment = left_align

            # Подсветка сборочных строк
            if item.level == 0:
                cell.fill = assembly_fill
                cell.font = assembly_font
            else:
                cell.font = detail_font

    # Ширина колонок
    col_widths = {
        1: 10, 2: 14, 3: 8, 4: 30, 5: 14, 6: 16, 7: 12,
        8: 9, 9: 12, 10: 14, 11: 14, 12: 18, 13: 9,
    }
    for ci, width in col_widths.items():
        ws.column_dimensions[get_column_letter(ci)].width = width

    # Автофильтр и закрепление верхней строки
    ws.auto_filter.ref = ws.dimensions
    if len(items) > 1:
        ws.freeze_panes = "A2"

    # Сводный лист
    _add_summary_sheet(wb, items)

    wb.save(output_path)
    logger.info(f"Excel сохранён: {output_path} ({len(items)} строк)")
    return output_path


def _add_summary_sheet(wb: Workbook, items: list[SpecItem]):
    """Добавляет сводный лист с информацией по маркам стали и профилям."""
    ws = wb.create_sheet("Сводка")

    assemblies = [it for it in items if it.level == 0]
    details = [it for it in items if it.level > 0]

    steel_summary: dict[str, float] = {}
    profile_summary: dict[str, float] = {}

    for it in details:
        mass = 0.0
        try:
            mass = float(it.mass_total.replace(",", ".") if it.mass_total else "0")
        except ValueError:
            pass
        if it.steel_grade:
            steel_summary[it.steel_grade] = steel_summary.get(it.steel_grade, 0) + mass
        if it.profile:
            profile_summary[it.profile] = profile_summary.get(it.profile, 0) + mass

    thin_border = Border(
        left=Side(style="thin"),
        right=Side(style="thin"),
        top=Side(style="thin"),
        bottom=Side(style="thin"),
    )
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    header_font = Font(name="Arial", bold=True, size=10, color="FFFFFF")
    bold_font = Font(name="Arial", bold=True, size=10)

    # Общая информация
    ws.cell(row=1, column=1, value="Общая информация").font = bold_font
    ws.cell(row=2, column=1, value="Сборок:")
    ws.cell(row=2, column=2, value=len(assemblies))
    ws.cell(row=3, column=1, value="Деталей:")
    ws.cell(row=3, column=2, value=len(details))

    total_mass = 0.0
    for it in assemblies:
        try:
            total_mass += float(it.mass_total.replace(",", ".") if it.mass_total else "0")
        except ValueError:
            pass
    ws.cell(row=4, column=1, value="Общая масса (по сборкам), кг:")
    ws.cell(row=4, column=2, value=round(total_mass, 2))

    # Сводка по маркам стали
    row = 6
    ws.cell(row=row, column=1, value="Сводка по маркам стали").font = bold_font
    row += 1
    for ci, h in enumerate(["Марка стали", "Масса, кг"], 1):
        cell = ws.cell(row=row, column=ci, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.border = thin_border
    row += 1
    for steel, mass in sorted(steel_summary.items()):
        ws.cell(row=row, column=1, value=steel).border = thin_border
        c = ws.cell(row=row, column=2, value=round(mass, 2))
        c.border = thin_border
        row += 1

    # Сводка по профилям
    row += 1
    ws.cell(row=row, column=1, value="Сводка по профилям").font = bold_font
    row += 1
    for ci, h in enumerate(["Профиль", "Масса, кг"], 1):
        cell = ws.cell(row=row, column=ci, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.border = thin_border
    row += 1
    for prof, mass in sorted(profile_summary.items()):
        ws.cell(row=row, column=1, value=prof).border = thin_border
        c = ws.cell(row=row, column=2, value=round(mass, 2))
        c.border = thin_border
        row += 1

    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 15


def save(
    items: list[SpecItem],
    output_path: str | Path,
    fmt: str = "excel",
) -> Path:
    """Сохраняет спецификацию в указанном формате (excel, csv, json)."""
    output_path = Path(output_path)
    fmt = fmt.lower().strip(".")

    if fmt in ("xlsx", "excel"):
        if output_path.suffix not in (".xlsx", ""):
            output_path = output_path.with_suffix(".xlsx")
        return save_excel(items, output_path)
    elif fmt == "csv":
        if output_path.suffix not in (".csv", ""):
            output_path = output_path.with_suffix(".csv")
        return save_csv(items, output_path)
    elif fmt == "json":
        if output_path.suffix not in (".json", ""):
            output_path = output_path.with_suffix(".json")
        return save_json(items, output_path)
    else:
        raise ValueError(f"Неподдерживаемый формат: {fmt}. Допустимые: excel, csv, json")
