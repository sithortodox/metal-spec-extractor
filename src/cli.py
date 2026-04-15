# Командный интерфейс (CLI) для извлечения спецификаций металлопроката из PDF

import logging
import sys
from pathlib import Path

import click

from .extractor import PDFTableExtractor
from .parser import SpecParser
from .output import save


@click.command()
@click.argument("pdf_path", type=click.Path(exists=True))
@click.option(
    "-o", "--output",
    default=None,
    help="Путь к файлу результата (по умолчанию — как у исходного, с другим расширением)",
)
@click.option(
    "-f", "--format",
    type=click.Choice(["excel", "csv", "json"], case_sensitive=False),
    default="excel",
    help="Формат вывода (по умолчанию: excel)",
)
@click.option(
    "--strategy",
    type=click.Choice(["lines", "text", "lines_strict"], case_sensitive=False),
    default="lines",
    help="Стратегия обнаружения таблиц в PDF",
)
@click.option(
    "-v", "--verbose",
    is_flag=True,
    help="Включить подробный вывод логов",
)
def main(pdf_path: str, output: str | None, format: str, strategy: str, verbose: bool):
    """Извлечение спецификации металлопроката из PDF в структурированный формат.

    PDF_PATH — путь к PDF-файлу со спецификацией металлоконструкций
    """
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")

    pdf = Path(pdf_path)
    if output is None:
        suffix = ".xlsx" if format == "excel" else f".{format}"
        output = str(pdf.with_suffix(suffix))

    click.echo(f"Обработка файла: {pdf.name}")

    table_settings = {
        "vertical_strategy": strategy,
        "horizontal_strategy": strategy,
    }

    extractor = PDFTableExtractor(pdf)
    tables = extractor.extract_tables(table_settings)

    if not tables:
        click.echo("Таблицы в PDF не найдены.", err=True)
        sys.exit(1)

    total_rows = sum(len(t.data_rows) for t in tables)
    click.echo(f"Найдено таблиц: {len(tables)}, строк данных: {total_rows}")

    parser = SpecParser()
    items = parser.parse_tables(tables)

    if not items:
        click.echo("Не удалось распознать позиции спецификации.", err=True)
        sys.exit(1)

    click.echo(f"Распознано позиций: {len(items)}")

    result_path = save(items, output, fmt=format)
    click.echo(f"Результат сохранён: {result_path}")


if __name__ == "__main__":
    main()
