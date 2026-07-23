from pathlib import Path
from io import BytesIO
import json
import math
import re

from pypdf import PdfReader, PdfWriter
from pypdf.annotations import Link
from pypdf.generic import ArrayObject, FloatObject
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas


INPUT_DIR = Path("pdfs")
OUTPUT_FILE = Path("merged_with_toc.pdf")
CHECKPOINT_FILE = Path("merge_pdf_checkpoint.json")
PAGE_SIZE = A4
TITLE = "Table des annexes"


def load_checkpoint() -> dict:
    if not CHECKPOINT_FILE.exists():
        return {}
    try:
        with CHECKPOINT_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def save_checkpoint(
    main_path: Path,
    ordered_appendix_paths: list[Path],
    titles: list[str],
) -> None:
    data = {
        "main": main_path.name,
        "appendix_order": [p.name for p in ordered_appendix_paths],
        "titles": {p.name: t for p, t in zip(ordered_appendix_paths, titles)},
    }
    with CHECKPOINT_FILE.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def clean_title(path: Path) -> str:
    """
    Convertit des noms de fichier comme :
      01_contract-final.pdf

    en :
      Contract Final
    """
    name = path.stem
    name = re.sub(r"^\d+[_\-. ]*", "", name)
    name = name.replace("_", " ").replace("-", " ")
    return name.title()


def make_toc_pdf(entries):
    """
    Génère les pages de la table des annexes (sans liens cliquables).

    Retourne :
      buffer : tampon BytesIO du PDF
      link_rects : zones cliquables à ajouter ensuite avec pypdf
    """
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=PAGE_SIZE)

    width, height = PAGE_SIZE
    left = 22 * mm
    right = 22 * mm
    top = height - 25 * mm
    bottom = 22 * mm

    title_font_size = 18
    row_font_size = 11
    line_height = 8 * mm

    max_rows_per_page = int((top - bottom - 18 * mm) / line_height)
    total_toc_pages = max(1, math.ceil(len(entries) / max_rows_per_page))

    link_rects = []

    for toc_page_index in range(total_toc_pages):
        c.setFont("Helvetica-Bold", title_font_size)
        c.drawString(left, top, TITLE)

        y = top - 18 * mm

        start = toc_page_index * max_rows_per_page
        end = start + max_rows_per_page

        for entry in entries[start:end]:
            title = entry["title"]
            page_number = entry["page_number"]

            c.setFont("Helvetica", row_font_size)

            max_title_width = width - left - right - 25 * mm
            display_title = title

            while (
                c.stringWidth(display_title, "Helvetica", row_font_size)
                > max_title_width
                and len(display_title) > 4
            ):
                display_title = display_title[:-4] + "..."

            c.drawString(left, y, display_title)
            c.drawRightString(width - right, y, str(page_number))

            title_width = c.stringWidth(display_title, "Helvetica", row_font_size)
            page_width = c.stringWidth(str(page_number), "Helvetica", row_font_size)

            dot_start = left + title_width + 3 * mm
            dot_end = width - right - page_width - 3 * mm

            if dot_end > dot_start:
                c.setDash(1, 2)
                c.line(dot_start, y + 1.5, dot_end, y + 1.5)
                c.setDash()

            link_rects.append(
                {
                    "toc_page_index": toc_page_index,
                    "target_entry_index": entry["source_index"],
                    "rect": [
                        float(left),
                        float(y - 2 * mm),
                        float(width - right),
                        float(y + 5 * mm),
                    ],
                }
            )

            y -= line_height

        c.showPage()

    c.save()
    buffer.seek(0)

    return buffer, link_rects


def make_title_page(title: str):
    """
    Génère une page unique avec le titre de l'annexe centré et un lien
    « Retour à la table des annexes » en bas de page.

    Retourne :
      reader : PdfReader contenant la page
      back_rect : zone cliquable (en coordonnées de page) pour le lien retour
    """
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=PAGE_SIZE)

    width, height = PAGE_SIZE
    font_name = "Helvetica-Bold"
    font_size = 28
    margin = 30 * mm
    max_width = width - 2 * margin

    words = title.split()
    lines = []
    current = ""

    for word in words:
        candidate = (current + " " + word).strip()
        if c.stringWidth(candidate, font_name, font_size) <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word

    if current:
        lines.append(current)

    line_height = font_size * 1.3
    total_height = len(lines) * line_height
    y_start = height / 2 + total_height / 2 - line_height / 2

    c.setFont(font_name, font_size)
    for i, line in enumerate(lines):
        y = y_start - i * line_height
        c.drawCentredString(width / 2, y, line)

    back_text = "Retour à la table des annexes"
    back_font_name = "Helvetica"
    back_font_size = 11
    back_y = 22 * mm
    back_text_width = c.stringWidth(back_text, back_font_name, back_font_size)
    back_x = (width - back_text_width) / 2

    c.setFont(back_font_name, back_font_size)
    c.setFillColorRGB(0.1, 0.3, 0.7)
    c.drawString(back_x, back_y, back_text)
    c.line(back_x, back_y - 1, back_x + back_text_width, back_y - 1)
    c.setFillColorRGB(0, 0, 0)

    back_rect = [
        float(back_x - 2 * mm),
        float(back_y - 2 * mm),
        float(back_x + back_text_width + 2 * mm),
        float(back_y + back_font_size),
    ]

    c.showPage()
    c.save()
    buffer.seek(0)

    return PdfReader(buffer), back_rect


def read_pdf(path: Path) -> PdfReader:
    reader = PdfReader(str(path))

    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception as exc:
            raise RuntimeError(f"Impossible de déchiffrer le PDF : {path}") from exc

    return reader


def prompt_main_choice(paths: list[Path], default_name: str | None = None) -> int:
    default_index = None
    if default_name is not None:
        for i, path in enumerate(paths):
            if path.name == default_name:
                default_index = i
                break

    print("Fichiers PDF trouvés :")
    for i, path in enumerate(paths, start=1):
        marker = "  ← précédent" if default_index is not None and i - 1 == default_index else ""
        print(f"  {i}. {path.name}{marker}")
    print()

    suffix = f" [défaut : {default_index + 1}]" if default_index is not None else ""

    while True:
        answer = input(
            f"Quel fichier doit être le document principal ? [1-{len(paths)}]{suffix} : "
        ).strip()

        if answer == "" and default_index is not None:
            return default_index

        if answer.isdigit():
            n = int(answer)
            if 1 <= n <= len(paths):
                return n - 1

        print("Réponse invalide, veuillez réessayer.")


def prompt_order(
    paths: list[Path],
    default_order: list[int] | None = None,
) -> list[int]:
    if not paths:
        return []

    print()
    print("Annexes disponibles :")
    for i, path in enumerate(paths, start=1):
        print(f"  {i}. {path.name}")
    print()

    if default_order is not None:
        default_str = " ".join(str(i + 1) for i in default_order)
        prompt_msg = (
            "Saisissez l'ordre des annexes, "
            f"ou appuyez sur Entrée pour l'ordre précédent ({default_str}) : "
        )
    else:
        example = " ".join(str(i) for i in range(1, len(paths) + 1))
        prompt_msg = (
            f"Saisissez l'ordre des annexes (ex. « {example} »), "
            "ou appuyez sur Entrée pour l'ordre alphabétique : "
        )

    while True:
        answer = input(prompt_msg).strip()

        if answer == "":
            if default_order is not None:
                return default_order
            return list(range(len(paths)))

        tokens = re.split(r"[\s,]+", answer)
        try:
            indices = [int(t) - 1 for t in tokens if t]
        except ValueError:
            print("Réponse invalide : utilisez uniquement des chiffres.")
            continue

        if sorted(indices) == list(range(len(paths))):
            return indices

        print(
            f"Réponse invalide : indiquez chaque numéro de 1 à {len(paths)} "
            "exactement une fois."
        )


def prompt_titles(
    ordered_paths: list[Path],
    saved_titles: dict[str, str] | None = None,
) -> list[str]:
    if not ordered_paths:
        return []

    saved_titles = saved_titles or {}

    print()
    print("Titres des annexes (appuyez sur Entrée pour utiliser le titre par défaut) :")

    titles = []
    total = len(ordered_paths)

    for i, path in enumerate(ordered_paths, start=1):
        default = saved_titles.get(path.name) or clean_title(path)
        answer = input(
            f"  [{i}/{total}] {path.name} — défaut : « {default} » : "
        ).strip()
        titles.append(answer if answer else default)

    return titles


def create_merged_pdf():
    pdf_paths = sorted(INPUT_DIR.glob("*.pdf"))

    if not pdf_paths:
        raise FileNotFoundError(
            f"Aucun fichier PDF trouvé dans : {INPUT_DIR.resolve()}"
        )

    if len(pdf_paths) < 2:
        raise RuntimeError(
            "Au moins deux fichiers PDF sont nécessaires : "
            "un document principal et au moins une annexe."
        )

    checkpoint = load_checkpoint()
    saved_main = checkpoint.get("main")
    saved_order = checkpoint.get("appendix_order", [])
    saved_titles = checkpoint.get("titles", {})

    main_index = prompt_main_choice(pdf_paths, default_name=saved_main)
    main_path = pdf_paths[main_index]
    appendix_paths = [p for i, p in enumerate(pdf_paths) if i != main_index]

    # Le défaut d'ordre n'est proposé que si la liste enregistrée correspond
    # exactement à l'ensemble actuel d'annexes.
    appendix_names = {p.name for p in appendix_paths}
    default_order = None
    if saved_order and set(saved_order) == appendix_names:
        name_to_index = {p.name: i for i, p in enumerate(appendix_paths)}
        default_order = [name_to_index[n] for n in saved_order]

    order = prompt_order(appendix_paths, default_order=default_order)
    ordered_appendix_paths = [appendix_paths[i] for i in order]

    titles = prompt_titles(ordered_appendix_paths, saved_titles=saved_titles)

    save_checkpoint(main_path, ordered_appendix_paths, titles)

    main_reader = read_pdf(main_path)
    main_page_count = len(main_reader.pages)

    appendix_docs = []
    for path, title in zip(ordered_appendix_paths, titles):
        reader = read_pdf(path)
        appendix_docs.append(
            {
                "path": path,
                "reader": reader,
                "title": title,
                "page_count": len(reader.pages),
            }
        )

    # Première passe : estimer le nombre de pages de la table des annexes.
    dummy_entries = [
        {"title": d["title"], "page_number": 1, "source_index": i}
        for i, d in enumerate(appendix_docs)
    ]
    temp_toc_buffer, _ = make_toc_pdf(dummy_entries)
    toc_page_count = len(PdfReader(temp_toc_buffer).pages)

    # Seconde passe : numéros de page réels.
    # Disposition : document principal, puis table des annexes, puis annexes.
    entries = []
    current_page_number = main_page_count + toc_page_count + 1

    for i, doc in enumerate(appendix_docs):
        entries.append(
            {
                "title": doc["title"],
                "page_number": current_page_number,
                "source_index": i,
            }
        )
        # +1 pour la page de titre insérée avant chaque annexe.
        current_page_number += 1 + doc["page_count"]

    toc_buffer, link_rects = make_toc_pdf(entries)
    toc_reader = PdfReader(toc_buffer)

    writer = PdfWriter()

    # 1. Document principal.
    main_start_index = len(writer.pages)
    for page in main_reader.pages:
        writer.add_page(page)

    # 2. Table des annexes.
    toc_start_index = len(writer.pages)
    for page in toc_reader.pages:
        writer.add_page(page)

    # 3. Annexes (page de titre + contenu).
    appendix_start_indexes = []
    back_links = []
    for doc in appendix_docs:
        title_page_index = len(writer.pages)
        appendix_start_indexes.append(title_page_index)

        title_reader, back_rect = make_title_page(doc["title"])
        for page in title_reader.pages:
            writer.add_page(page)

        back_links.append({"page_index": title_page_index, "rect": back_rect})

        for page in doc["reader"].pages:
            writer.add_page(page)

    # Signets.
    writer.add_outline_item(clean_title(main_path), main_start_index)
    writer.add_outline_item(TITLE, toc_start_index)
    for entry, start_page_index in zip(entries, appendix_start_indexes):
        writer.add_outline_item(entry["title"], start_page_index)

    # Liens cliquables sur les pages de la table des annexes.
    for link in link_rects:
        toc_local_index = link["toc_page_index"]
        target_entry_index = link["target_entry_index"]
        target_page_index = appendix_start_indexes[target_entry_index]

        annotation = Link(
            rect=link["rect"],
            border=ArrayObject([FloatObject(0), FloatObject(0), FloatObject(0)]),
            target_page_index=target_page_index,
        )
        writer.add_annotation(
            page_number=toc_start_index + toc_local_index,
            annotation=annotation,
        )

    # Liens « Retour à la table des annexes » sur chaque page de titre.
    for back in back_links:
        annotation = Link(
            rect=back["rect"],
            border=ArrayObject([FloatObject(0), FloatObject(0), FloatObject(0)]),
            target_page_index=toc_start_index,
        )
        writer.add_annotation(
            page_number=back["page_index"],
            annotation=annotation,
        )

    with OUTPUT_FILE.open("wb") as f:
        writer.write(f)

    print()
    print(f"Créé : {OUTPUT_FILE.resolve()}")
    print()
    print(f"Document principal : {main_path.name} ({main_page_count} pages)")
    print()
    print("Annexes fusionnées :")
    for entry, doc in zip(entries, appendix_docs):
        print(
            f"- Page {entry['page_number']} : "
            f"{entry['title']} "
            f"({doc['path'].name}, {doc['page_count']} pages)"
        )


if __name__ == "__main__":
    create_merged_pdf()
