# Модуль извлечения таблиц из PDF-документов со спецификациями металлопроката

import re
import logging
from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber

logger = logging.getLogger(__name__)


@dataclass
class TableCell:
    """Ячейка таблицы с координатами на странице PDF."""
    text: str
    x0: float
    top: float
    x1: float
    bottom: float
    row: int
    col: int
    col_span: int = 1
    row_span: int = 1


@dataclass
class ExtractedTable:
    """Извлечённая таблица со страницы PDF."""
    page_number: int
    raw_rows: list[list[str]]
    cells: list[list[TableCell]] = field(default_factory=list)
    header: list[str] = field(default_factory=list)
    data_rows: list[list[str]] = field(default_factory=list)


class PDFTableExtractor:
    """Извлекает таблицы из PDF-файла с помощью pdfplumber."""

    # Настройки по умолчанию для обнаружения таблиц
    SETTINGS = {
        "vertical_strategy": "lines",
        "horizontal_strategy": "lines",
        "snap_tolerance": 5,
        "join_tolerance": 5,
        "edge_min_length": 10,
        "min_words_vertical": 1,
        "min_words_horizontal": 1,
    }

    # Ключевые слова заголовка спецификации металлопроката
    HEADER_KEYWORDS = [
        "поз", "позиция", "наименование", "марка", "профиль",
        "сечение", "сталь", "марка стали", "кол", "количество",
        "масса", "вес", "длина", "площадь", "примечание", "обозначение",
        "тип", "размер", "толщ", "ширина", "№",
    ]

    def __init__(self, pdf_path: str | Path):
        self.pdf_path = Path(pdf_path)
        if not self.pdf_path.exists():
            raise FileNotFoundError(f"PDF-файл не найден: {self.pdf_path}")

    def _is_header_row(self, row: list[str]) -> bool:
        """Проверяет, является ли строка заголовком таблицы."""
        combined = " ".join(cell.strip().lower() for cell in row if cell.strip())
        if not combined:
            return False
        matches = sum(1 for kw in self.HEADER_KEYWORDS if kw in combined)
        return matches >= 2

    def _clean_cell(self, text: str) -> str:
        """Очищает текст ячейки от лишних пробелов и переносов."""
        text = text.replace("\n", " ").replace("\r", " ")
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _detect_merged_cells(self, table, page) -> list[list[TableCell]]:
        """Определяет объединённые ячейки в таблице."""
        cells_grid = []
        try:
            rows = table.rows
        except Exception:
            return cells_grid

        if not rows:
            return cells_grid

        for ri, row in enumerate(rows):
            row_cells = []
            cells = getattr(row, "cells", None)
            if cells is None:
                continue
            for ci, cell in enumerate(cells):
                if cell is None:
                    row_cells.append(TableCell(
                        text="", x0=0, top=0, x1=0, bottom=0, row=ri, col=ci
                    ))
                    continue
                # pdfplumber может возвращать кортеж вместо объекта ячейки
                if isinstance(cell, tuple):
                    text = self._clean_cell(str(cell)) if cell else ""
                    tc = TableCell(text=text, x0=0, top=0, x1=0, bottom=0, row=ri, col=ci)
                else:
                    text = self._clean_cell(getattr(cell, "text", ""))
                    tc = TableCell(
                        text=text,
                        x0=getattr(cell, "x0", 0),
                        top=getattr(cell, "top", 0),
                        x1=getattr(cell, "x1", 0),
                        bottom=getattr(cell, "bottom", 0),
                        row=ri, col=ci,
                    )
                row_cells.append(tc)
            cells_grid.append(row_cells)
        return cells_grid

    def extract_tables(self, table_settings: dict | None = None) -> list[ExtractedTable]:
        """Извлекает все таблицы из PDF-файла."""
        settings = {**self.SETTINGS}
        if table_settings:
            settings.update(table_settings)

        extracted = []

        with pdfplumber.open(self.pdf_path) as pdf:
            for page_idx, page in enumerate(pdf.pages):
                tables = page.find_tables(settings)
                logger.info(f"Страница {page_idx + 1}: найдено таблиц — {len(tables)}")

                for ti, table in enumerate(tables):
                    raw_rows = []
                    for row in table.extract():
                        cleaned = [self._clean_cell(c) if c else "" for c in row]
                        raw_rows.append(cleaned)

                    ext = ExtractedTable(page_number=page_idx + 1, raw_rows=raw_rows)

                    # Ищем строку заголовка
                    header_idx = None
                    for i, row in enumerate(raw_rows):
                        if self._is_header_row(row):
                            header_idx = i
                            ext.header = row
                            break

                    if header_idx is not None:
                        ext.data_rows = raw_rows[header_idx + 1:]
                    elif raw_rows:
                        ext.header = self._infer_header(raw_rows[0])
                        ext.data_rows = raw_rows[1:]

                    # Удаляем полностью пустые строки
                    ext.data_rows = [
                        r for r in ext.data_rows
                        if any(cell.strip() for cell in r)
                    ]

                    ext.cells = self._detect_merged_cells(table, page)
                    extracted.append(ext)

                    logger.info(
                        f"  Таблица {ti + 1}: строк данных — {len(ext.data_rows)}, "
                        f"заголовок={ext.header[:3]}..."
                    )

        return extracted

    def _infer_header(self, first_row: list[str]) -> list[str]:
        """Определяет заголовки колонок по умолчанию, если не удалось распознать."""
        defaults = [
            "Поз.", "Наименование", "Обозначение", "Профиль/Сечение",
            "Марка стали", "Кол-во", "Длина, мм", "Масса ед., кг",
            "Масса общ., кг", "Примечание",
        ]
        if len(first_row) <= len(defaults):
            return defaults[:len(first_row)]
        return defaults + [f"Кол.{i}" for i in range(len(defaults), len(first_row))]
