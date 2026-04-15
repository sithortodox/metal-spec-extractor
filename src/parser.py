# Модуль парсинга спецификации металлопроката — нормализация вложенной структуры

import re
import logging
from dataclasses import dataclass, field

from .extractor import ExtractedTable

logger = logging.getLogger(__name__)


@dataclass
class SpecItem:
    """Строка спецификации металлопроката."""
    position: str = ""
    name: str = ""
    designation: str = ""
    profile: str = ""
    steel_grade: str = ""
    quantity: str = ""
    length: str = ""
    mass_single: str = ""
    mass_total: str = ""
    note: str = ""
    level: int = 0
    parent_position: str = ""
    page_number: int = 0


# Шаблоны для определения уровня вложенности позиции
POSITION_PATTERNS = [
    re.compile(r"^(\d+)\.(\d+)(?:\.(\d+))?$"),
    re.compile(r"^(\d+)-(\d+)(?:-(\d+))?$"),
    re.compile(r"^(\d+)/(\d+)(?:/(\d+))?$"),
]

# Ключевые слова сборочных единиц
ASSEMBLY_KEYWORDS = [
    "сборка", "сборочная единица", "отправочная марка",
    "марка", "элемент", "блок", "ферма", "балка", "колонна",
    "связь", "прогоны", "ригель", "панель",
]

# Регулярные выражения для распознавания
STEEL_RE = re.compile(
    r"(?:С|с)\s*(\d{3})"
    r"|(?:\d{2}[Гг]\d+[Сс]?)"
    r"|(?:Ст|ст|ВСт|вст)\s*\d(?:\s*сп|кп)?",
)

QUANTITY_RE = re.compile(r"^\d+[,.]?\d*$")
MASS_RE = re.compile(r"^\d+[,.]?\d*$")


class SpecParser:
    """Парсер спецификации металлопроката с поддержкой вложенной структуры."""

    # Соответствие ключевых слов в заголовке полям спецификации
    COLUMN_MAP_HINTS = {
        "поз": ["поз", "позиция", "поз.", "№"],
        "name": ["наименование", "наим.", "наим"],
        "designation": ["обозначение", "обозн.", "обозн"],
        "profile": ["профиль", "сечени", "сеч.", "сечение", "размер", "тип"],
        "steel": ["сталь", "марка стали", "кл.ст.", "класс"],
        "quantity": ["кол", "кол.", "количество", "кол-во", "шт"],
        "length": ["длина", "длин.", "l"],
        "mass_single": ["масса ед", "масса 1 шт", "масса ед.", "вес ед", "ед., кг"],
        "mass_total": ["масса", "вес", "масса общ", "масса, кг", "вес, кг", "общ., кг"],
        "note": ["примечание", "прим.", "прим", "замечание"],
    }

    def __init__(self):
        self.column_indices: dict[str, int] = {}
        self.num_columns: int = 0

    def _map_columns(self, header: list[str]) -> dict[str, int]:
        """Сопоставляет заголовки колонок с полями спецификации."""
        mapping: dict[str, int] = {}
        used_cols: set[int] = set()
        for ci, h in enumerate(header):
            h_lower = h.strip().lower()
            if ci in used_cols:
                continue
            for key, hints in self.COLUMN_MAP_HINTS.items():
                if key in mapping:
                    continue
                for hint in hints:
                    if hint in h_lower:
                        mapping[key] = ci
                        used_cols.add(ci)
                        break
                if ci in used_cols:
                    break
        return mapping

    def _detect_position_level(self, pos: str) -> int:
        """Определяет уровень вложенности позиции (0=сборка, 1=деталь, 2=поддеталь)."""
        if not pos.strip():
            return -1
        pos = pos.strip()
        for pat in POSITION_PATTERNS:
            m = pat.match(pos)
            if m:
                groups = [g for g in m.groups() if g is not None]
                return len(groups) - 1
        if re.match(r"^\d+[а-яА-Я]?$", pos):
            return 0
        return -1

    def _is_assembly_row(self, row: list[str], col_map: dict[str, int]) -> bool:
        """Проверяет, является ли строка сборочной единицей (а не деталью)."""
        name_idx = col_map.get("name")
        profile_idx = col_map.get("profile")
        steel_idx = col_map.get("steel")
        quantity_idx = col_map.get("quantity")

        # Проверка по ключевым словам в наименовании
        if name_idx is not None and name_idx < len(row):
            name = row[name_idx].strip().lower()
            for kw in ASSEMBLY_KEYWORDS:
                if kw in name:
                    return True

        # Сборка обычно без профиля, марки стали и количества
        has_profile = (
            profile_idx is not None
            and profile_idx < len(row)
            and row[profile_idx].strip()
        )
        has_steel = (
            steel_idx is not None
            and steel_idx < len(row)
            and row[steel_idx].strip()
        )
        has_qty = (
            quantity_idx is not None
            and quantity_idx < len(row)
            and row[quantity_idx].strip()
        )

        if not has_profile and not has_steel and not has_qty:
            return True

        return False

    def _get_cell(self, row: list[str], col_map: dict[str, int], key: str) -> str:
        """Получает значение ячейки по ключу маппинга колонок."""
        idx = col_map.get(key)
        if idx is not None and idx < len(row):
            return row[idx].strip()
        return ""

    def _propagate_assembly_fields(self, items: list[SpecItem]) -> list[SpecItem]:
        """Распространяет позицию родительской сборки на дочерние элементы."""
        current_assembly_pos = ""

        for item in items:
            if item.level == 0:
                current_assembly_pos = item.position
            elif item.level > 0:
                if not item.parent_position:
                    item.parent_position = current_assembly_pos
            elif item.level == -1:
                item.parent_position = current_assembly_pos
                if current_assembly_pos:
                    item.level = 1

        return items

    def _merge_continuation_rows(
        self, raw_rows: list[list[str]], col_map: dict[str, int]
    ) -> list[list[str]]:
        """Объединяет строки-продолжения (переносы текста на следующую строку)."""
        if not raw_rows:
            return raw_rows

        pos_idx = col_map.get("поз", 0)
        merged = []
        prev = None

        for row in raw_rows:
            pos = row[pos_idx].strip() if pos_idx < len(row) else ""
            if pos and prev is not None:
                merged.append(prev)
                prev = row
            elif prev is not None:
                # Строка-продолжение: дописываем в предыдущую
                for ci in range(len(row)):
                    if ci < len(prev) and row[ci].strip():
                        if prev[ci].strip():
                            prev[ci] += " " + row[ci].strip()
                        else:
                            prev[ci] = row[ci].strip()
                prev_row_len = len(prev)
                row_len = len(row)
                if row_len > prev_row_len:
                    prev.extend(row[prev_row_len:])
            else:
                prev = list(row)

        if prev is not None:
            merged.append(prev)

        return merged

    def parse_tables(
        self,
        extracted_tables: list[ExtractedTable],
        merge_across_pages: bool = True,
    ) -> list[SpecItem]:
        """Парсит извлечённые таблицы в список позиций спецификации."""
        all_items: list[SpecItem] = []

        for table in extracted_tables:
            if not table.data_rows:
                continue

            col_map = self._map_columns(table.header)

            # Если колонка «Поз.» не найдена — пробуем определить первую колонку
            if "поз" not in col_map:
                first_col = 0
                for ci, h in enumerate(table.header):
                    if any(kw in h.strip().lower() for kw in ["поз", "позиция", "№"]):
                        first_col = ci
                        break
                col_map["поз"] = first_col

            if not col_map:
                logger.warning(
                    f"Страница {table.page_number}: не удалось сопоставить колонки, "
                    f"заголовок={table.header}"
                )
                col_map = self._build_default_map(len(table.header))

            merged_rows = self._merge_continuation_rows(table.data_rows, col_map)

            assembly_stack: list[str] = [""]

            for row in merged_rows:
                item = SpecItem(page_number=table.page_number)

                # Заполняем поля из строки по маппингу колонок
                item.position = self._get_cell(row, col_map, "поз")
                item.name = self._get_cell(row, col_map, "name")
                item.designation = self._get_cell(row, col_map, "designation")
                item.profile = self._get_cell(row, col_map, "profile")
                item.steel_grade = self._get_cell(row, col_map, "steel")
                item.quantity = self._get_cell(row, col_map, "quantity")
                item.length = self._get_cell(row, col_map, "length")
                item.mass_single = self._get_cell(row, col_map, "mass_single")
                item.mass_total = self._get_cell(row, col_map, "mass_total")
                item.note = self._get_cell(row, col_map, "note")

                # Определяем уровень вложенности
                level = self._detect_position_level(item.position)
                is_assembly = self._is_assembly_row(row, col_map)

                if level >= 0:
                    item.level = level
                elif is_assembly:
                    item.level = 0
                else:
                    item.level = -1

                # Обновляем стек сборок
                if item.level == 0:
                    assembly_stack = [item.position]
                    item.parent_position = ""
                elif item.level > 0:
                    while len(assembly_stack) > item.level:
                        assembly_stack.pop()
                    if not assembly_stack or assembly_stack[-1] != item.position:
                        assembly_stack.append(item.position)
                    item.parent_position = assembly_stack[0] if assembly_stack else ""
                else:
                    if assembly_stack:
                        item.parent_position = assembly_stack[0]
                        item.level = len(assembly_stack)

                # Пост-обработка значений
                self._post_process_steel(item)
                self._post_process_quantity(item)
                self._post_process_mass(item)

                all_items.append(item)

        all_items = self._propagate_assembly_fields(all_items)
        return all_items

    def _build_default_map(self, ncols: int) -> dict[str, int]:
        """Строит маппинг по умолчанию для заданного числа колонок."""
        defaults = [
            "поз", "name", "designation", "profile", "steel",
            "quantity", "length", "mass_single", "mass_total", "note",
        ]
        m = {}
        for i in range(min(ncols, len(defaults))):
            m[defaults[i]] = i
        for i in range(len(defaults), ncols):
            m[f"доп_{i}"] = i
        return m

    def _post_process_steel(self, item: SpecItem):
        """Очищает значение марки стали от лишних пробелов."""
        if item.steel_grade:
            item.steel_grade = item.steel_grade.replace(" ", "")
            return
        # Если марка не заполнена — пробуем извлечь из профиля
        if item.profile:
            m = STEEL_RE.search(item.profile)
            if m:
                item.steel_grade = m.group(0).replace(" ", "")

    def _post_process_quantity(self, item: SpecItem):
        """Нормализует значение количества."""
        val = item.quantity.replace(" ", "").replace("шт", "").replace("шт.", "")
        if QUANTITY_RE.match(val):
            item.quantity = val.replace(",", ".")
        elif val:
            item.quantity = val

    def _post_process_mass(self, item: SpecItem):
        """Нормализует значения массы."""
        for attr in ("mass_single", "mass_total"):
            val = getattr(item, attr)
            val = val.replace(" ", "").replace("кг", "").replace("кг.", "")
            if MASS_RE.match(val):
                setattr(item, attr, val.replace(",", "."))
            elif val:
                setattr(item, attr, val)
