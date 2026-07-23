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
    appendix_titles: dict[str, str],
    section_names: dict[str, str],
    remove_cover: bool,
    section_dividers: bool,
) -> None:
    data = {
        "main": main_path.name,
        "titles": appendix_titles,
        "section_names": section_names,
        "remove_cover": remove_cover,
        "section_dividers": section_dividers,
    }
    with CHECKPOINT_FILE.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# Trait d'union ASCII plus les tirets Unicode courants (tiret demi-cadratin,
# cadratin, insécable, etc.), fréquents dans les noms de fichiers macOS.
_DASHES = r"\-‐‑‒–—―"


def clean_title(path: Path) -> str:
    """
    Convertit des noms de fichier ou de dossier comme :
      01_contract-final.pdf
      02_Comptes–annuels 2025   (tiret Unicode, dossier)

    en :
      Contract Final
      Comptes Annuels 2025

    On ne retire que l'extension « .pdf » : le point est significatif dans un
    nom de dossier (« v1.2 ») et ne doit pas tronquer le nom.
    """
    name = path.name
    if name.lower().endswith(".pdf"):
        name = name[: -len(".pdf")]
    # Préfixe numérique de tri : « 01_ », « 1- », « 1. »…
    name = re.sub(rf"^\d+[_{_DASHES}. ]*", "", name)
    # Underscores et tirets (ASCII + Unicode) → espaces.
    name = re.sub(rf"[_{_DASHES}]", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name.title()


def rel_key(path: Path) -> str:
    """Clé stable d'une annexe dans le checkpoint : chemin relatif à pdfs/."""
    try:
        return path.relative_to(INPUT_DIR).as_posix()
    except ValueError:
        return path.name


def make_toc_pdf(rows):
    """
    Génère les pages de la table des annexes (sans liens cliquables).

    Chaque « row » est un dict :
      title       : texte affiché
      page_number : numéro de page (int) ou None (pas de numéro ni de pointillés)
      indent      : niveau d'indentation (0 = section/annexe, 1 = sous-section)
      bold        : True pour les en-têtes de section
      rule        : True pour souligner l'en-tête de section
      target_id   : identifiant de destination pour le lien, ou None

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
    indent_step = 8 * mm

    max_rows_per_page = int((top - bottom - 18 * mm) / line_height)
    total_toc_pages = max(1, math.ceil(len(rows) / max_rows_per_page))

    link_rects = []

    for toc_page_index in range(total_toc_pages):
        c.setFont("Helvetica-Bold", title_font_size)
        c.drawString(left, top, TITLE)

        y = top - 18 * mm

        start = toc_page_index * max_rows_per_page
        end = start + max_rows_per_page

        for row in rows[start:end]:
            title = row["title"]
            page_number = row.get("page_number")
            indent = row.get("indent", 0)
            bold = row.get("bold", False)

            row_left = left + indent * indent_step
            font_name = "Helvetica-Bold" if bold else "Helvetica"
            c.setFont(font_name, row_font_size)

            max_title_width = width - row_left - right - 25 * mm
            display_title = title

            while (
                c.stringWidth(display_title, font_name, row_font_size)
                > max_title_width
                and len(display_title) > 4
            ):
                display_title = display_title[:-4] + "..."

            c.drawString(row_left, y, display_title)

            title_width = c.stringWidth(display_title, font_name, row_font_size)

            if page_number is not None:
                c.setFont(font_name, row_font_size)
                c.drawRightString(width - right, y, str(page_number))
                page_width = c.stringWidth(str(page_number), font_name, row_font_size)

                dot_start = row_left + title_width + 3 * mm
                dot_end = width - right - page_width - 3 * mm

                if dot_end > dot_start:
                    c.setDash(1, 2)
                    c.line(dot_start, y + 1.5, dot_end, y + 1.5)
                    c.setDash()

            if row.get("rule"):
                c.setLineWidth(0.4)
                c.line(row_left, y - 2.2 * mm, width - right, y - 2.2 * mm)
                c.setLineWidth(1)

            if row.get("target_id") is not None:
                link_rects.append(
                    {
                        "toc_page_index": toc_page_index,
                        "target_id": row["target_id"],
                        "rect": [
                            float(row_left),
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


def _draw_back_link(c):
    """Dessine le lien « Retour à la table des annexes » et retourne son rect."""
    width, _ = PAGE_SIZE
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

    return [
        float(back_x - 2 * mm),
        float(back_y - 2 * mm),
        float(back_x + back_text_width + 2 * mm),
        float(back_y + back_font_size),
    ]


def _draw_centered_title(c, title, font_size):
    """Dessine un titre centré (multi-lignes) et retourne le bas du bloc."""
    width, height = PAGE_SIZE
    font_name = "Helvetica-Bold"
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

    return y_start - (len(lines) - 1) * line_height


def make_title_page(title: str):
    """
    Génère une page unique avec le titre de l'annexe centré et un lien
    « Retour à la table des annexes » en bas de page.
    """
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=PAGE_SIZE)

    _draw_centered_title(c, title, font_size=28)
    back_rect = _draw_back_link(c)

    c.showPage()
    c.save()
    buffer.seek(0)

    return PdfReader(buffer), back_rect


def make_divider_page(name: str):
    """
    Génère une page de séparation de section : un intitulé « SECTION » suivi du
    nom de la section, centré, plus un lien « Retour à la table des annexes ».
    """
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=PAGE_SIZE)

    width, height = PAGE_SIZE

    eyebrow = "SECTION"
    eyebrow_font_size = 14
    c.setFont("Helvetica", eyebrow_font_size)
    c.setFillColorRGB(0.35, 0.35, 0.35)
    c.drawCentredString(width / 2, height / 2 + 26 * mm, eyebrow)
    c.setFillColorRGB(0, 0, 0)

    _draw_centered_title(c, name, font_size=32)
    back_rect = _draw_back_link(c)

    c.showPage()
    c.save()
    buffer.seek(0)

    return PdfReader(buffer), back_rect


def read_pdf(path: Path) -> PdfReader:
    try:
        reader = PdfReader(str(path))
    except Exception as exc:
        raise RuntimeError(
            f"PDF illisible (fichier corrompu ?) : {path}"
        ) from exc

    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception as exc:
            raise RuntimeError(f"Impossible de déchiffrer le PDF : {path}") from exc

    return reader


def is_pdf(path: Path) -> bool:
    # Insensible à la casse (.pdf / .PDF) et sans tenir compte des fichiers
    # cachés (.DS_Store, etc.).
    return (
        path.is_file()
        and not path.name.startswith(".")
        and path.suffix.lower() == ".pdf"
    )


def list_pdfs(folder: Path, recursive: bool) -> list[Path]:
    it = folder.rglob("*") if recursive else folder.iterdir()
    pdfs = [p for p in it if is_pdf(p)]
    # Tri par chemin relatif pour un ordre stable (préfixes numériques).
    return sorted(pdfs, key=lambda p: p.relative_to(folder).as_posix().lower())


def discover_inputs(root: Path):
    """
    Retourne (root_pdfs, sections) où :
      root_pdfs : PDF à la racine de pdfs/ (candidats document principal +
                  annexes non classées), triés par nom.
      sections  : liste de dicts {folder, pdfs} pour chaque sous-dossier
                  contenant au moins un PDF (à n'importe quelle profondeur),
                  triés par nom.

    La détection est insensible à la casse de l'extension, ignore les fichiers
    et dossiers cachés, et récupère les PDF placés dans des sous-dossiers
    imbriqués d'une section (à plat).
    """
    root_pdfs = list_pdfs(root, recursive=False)

    sections = []
    for folder in sorted(
        (c for c in root.iterdir() if c.is_dir() and not c.name.startswith(".")),
        key=lambda p: p.name.lower(),
    ):
        pdfs = list_pdfs(folder, recursive=True)
        if pdfs:
            sections.append({"folder": folder, "pdfs": pdfs})

    return root_pdfs, sections


def prompt_main_choice(paths: list[Path], default_name: str | None = None) -> int:
    default_index = None
    if default_name is not None:
        for i, path in enumerate(paths):
            if path.name == default_name:
                default_index = i
                break

    print("Fichiers PDF à la racine de pdfs/ :")
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


def prompt_section_names(
    sections: list[dict],
    saved_names: dict[str, str] | None = None,
) -> list[str]:
    saved_names = saved_names or {}
    if not sections:
        return []

    print()
    print("Noms des sections (appuyez sur Entrée pour le nom par défaut) :")

    names = []
    total = len(sections)
    for i, section in enumerate(sections, start=1):
        folder = section["folder"]
        default = saved_names.get(folder.name) or clean_title(folder)
        answer = input(
            f"  [{i}/{total}] {folder.name}/ — défaut : « {default} » : "
        ).strip()
        names.append(answer if answer else default)

    return names


def prompt_titles(
    specs: list[dict],
    saved_titles: dict[str, str] | None = None,
) -> None:
    """
    Demande un titre pour chaque annexe et l'écrit dans spec["title"].
    Les annexes sont regroupées visuellement par section.
    """
    saved_titles = saved_titles or {}
    if not specs:
        return

    print()
    print("Titres des annexes (appuyez sur Entrée pour le titre par défaut) :")

    total = len(specs)
    current_section = object()  # sentinelle : force l'affichage du premier groupe

    for i, spec in enumerate(specs, start=1):
        if spec["section_name"] != current_section:
            current_section = spec["section_name"]
            label = current_section if current_section else "Annexes générales"
            print(f"  — {label} —")

        default = saved_titles.get(spec["key"]) or clean_title(spec["path"])
        answer = input(
            f"  [{i}/{total}] {spec['path'].name} — défaut : « {default} » : "
        ).strip()
        spec["title"] = answer if answer else default


def prompt_yes_no(question: str, default: bool = False) -> bool:
    default_label = "O/n" if default else "o/N"

    print()
    while True:
        answer = input(f"{question} [{default_label}] : ").strip().lower()

        if answer == "":
            return default
        if answer in ("o", "oui", "y", "yes"):
            return True
        if answer in ("n", "non", "no"):
            return False

        print("Réponse invalide, répondez par « o » ou « n ».")


def build_doc(spec: dict, remove_cover: bool) -> dict:
    reader = read_pdf(spec["path"])
    total_pages = len(reader.pages)
    # On ne supprime la page de garde que s'il reste au moins une page de
    # contenu ensuite.
    start_page = 1 if remove_cover and total_pages > 1 else 0
    return {
        "path": spec["path"],
        "key": spec["key"],
        "title": spec["title"],
        "reader": reader,
        "start_page": start_page,
        "page_count": total_pages - start_page,
    }


def create_merged_pdf():
    if not INPUT_DIR.exists():
        raise FileNotFoundError(f"Dossier introuvable : {INPUT_DIR.resolve()}")

    root_pdfs, sections = discover_inputs(INPUT_DIR)

    if not root_pdfs:
        raise FileNotFoundError(
            "Aucun PDF à la racine de "
            f"{INPUT_DIR.resolve()} : placez-y le document principal."
        )

    checkpoint = load_checkpoint()
    saved_main = checkpoint.get("main")
    saved_titles = checkpoint.get("titles", {})
    saved_section_names = checkpoint.get("section_names", {})
    saved_remove_cover = bool(checkpoint.get("remove_cover", False))
    saved_section_dividers = bool(checkpoint.get("section_dividers", False))

    main_index = prompt_main_choice(root_pdfs, default_name=saved_main)
    main_path = root_pdfs[main_index]

    unsectioned_paths = [p for i, p in enumerate(root_pdfs) if i != main_index]

    total_appendices = len(unsectioned_paths) + sum(len(s["pdfs"]) for s in sections)
    if total_appendices == 0:
        raise RuntimeError(
            "Aucune annexe trouvée : ajoutez des PDF à la racine de pdfs/ "
            "ou dans des sous-dossiers (sections)."
        )

    # Noms de section (uniquement s'il y a des sous-dossiers).
    section_names = prompt_section_names(sections, saved_names=saved_section_names)

    # Construction des « specs » d'annexes dans l'ordre du corps :
    # d'abord les annexes non classées, puis les sections.
    specs = []
    for path in unsectioned_paths:
        specs.append({"path": path, "key": rel_key(path), "section_name": None})
    for section, name in zip(sections, section_names):
        for path in section["pdfs"]:
            specs.append({"path": path, "key": rel_key(path), "section_name": name})

    prompt_titles(specs, saved_titles=saved_titles)

    remove_cover = prompt_yes_no(
        "Supprimer la page de garde (première page) de chaque annexe ?",
        default=saved_remove_cover,
    )

    section_dividers = False
    if sections:
        section_dividers = prompt_yes_no(
            "Insérer une page de séparation avant chaque section ?",
            default=saved_section_dividers,
        )

    save_checkpoint(
        main_path,
        {spec["key"]: spec["title"] for spec in specs},
        {section["folder"].name: name for section, name in zip(sections, section_names)},
        remove_cover,
        section_dividers,
    )

    # Lecture des documents.
    main_reader = read_pdf(main_path)
    main_page_count = len(main_reader.pages)

    key_to_doc = {spec["key"]: build_doc(spec, remove_cover) for spec in specs}

    unsectioned_docs = [key_to_doc[rel_key(p)] for p in unsectioned_paths]
    section_blocks = []
    for section, name in zip(sections, section_names):
        docs = [key_to_doc[rel_key(p)] for p in section["pdfs"]]
        section_blocks.append({"name": name, "folder": section["folder"], "docs": docs})

    # Première passe : estimer le nombre de pages de la table des annexes.
    # Le nombre de lignes ne dépend pas des numéros de page réels.
    dummy_rows = []
    for doc in unsectioned_docs:
        dummy_rows.append({"title": doc["title"], "page_number": 0, "indent": 0})
    for block in section_blocks:
        dummy_rows.append(
            {
                "title": block["name"],
                "page_number": (0 if section_dividers else None),
                "indent": 0,
                "bold": True,
                "rule": True,
            }
        )
        for doc in block["docs"]:
            dummy_rows.append({"title": doc["title"], "page_number": 0, "indent": 1})

    temp_toc_buffer, _ = make_toc_pdf(dummy_rows)
    toc_page_count = len(PdfReader(temp_toc_buffer).pages)

    # Seconde passe : calcul des index de page réels et des lignes de la table.
    # Disposition : document principal, table des annexes, puis le corps.
    body_page = main_page_count + toc_page_count  # index 0-based de la 1re page du corps
    next_target = 0
    toc_rows = []
    target_page_index = {}  # target_id -> index de page 0-based

    def place_doc(doc, indent):
        nonlocal body_page, next_target
        target_id = next_target
        next_target += 1
        doc["target_id"] = target_id
        doc["page_index"] = body_page  # page de titre de l'annexe
        target_page_index[target_id] = body_page
        toc_rows.append(
            {
                "title": doc["title"],
                "page_number": body_page + 1,
                "indent": indent,
                "target_id": target_id,
            }
        )
        body_page += 1 + doc["page_count"]  # page de titre + contenu

    for doc in unsectioned_docs:
        place_doc(doc, 0)

    for block in section_blocks:
        header_row = {"title": block["name"], "indent": 0, "bold": True, "rule": True}
        toc_rows.append(header_row)

        if section_dividers:
            target_id = next_target
            next_target += 1
            block["divider_target_id"] = target_id
            block["divider_page_index"] = body_page
            block["bookmark_page_index"] = body_page
            target_page_index[target_id] = body_page
            header_row["page_number"] = body_page + 1
            header_row["target_id"] = target_id
            body_page += 1  # page de séparation
        else:
            block["divider_target_id"] = None
            block["divider_page_index"] = None
            header_row["page_number"] = None
            header_row["target_id"] = None

        for doc in block["docs"]:
            place_doc(doc, 1)

        if not section_dividers:
            # En-tête cliquable vers la première annexe de la section.
            first_doc = block["docs"][0]
            header_row["target_id"] = first_doc["target_id"]
            block["bookmark_page_index"] = first_doc["page_index"]

    expected_total_pages = body_page  # index de page atteint = nombre total de pages

    toc_buffer, link_rects = make_toc_pdf(toc_rows)
    toc_reader = PdfReader(toc_buffer)

    writer = PdfWriter()

    # 1. Document principal.
    #    On utilise writer.append() (et non add_page() page par page) : le
    #    remappage complet du graphe d'objets est bien plus robuste face aux
    #    PDF mal formés (p. ex. exportés/complétés sous macOS), qui sinon
    #    peuvent perdre des pages à l'écriture.
    main_start_index = len(writer.pages)
    writer.append(main_reader, import_outline=False)

    # 2. Table des annexes.
    toc_start_index = len(writer.pages)
    for page in toc_reader.pages:
        writer.add_page(page)

    # 3. Corps : annexes non classées, puis sections.
    back_links = []

    def add_doc_pages(doc):
        title_page_index = len(writer.pages)
        assert title_page_index == doc["page_index"], "désynchronisation des pages"

        title_reader, back_rect = make_title_page(doc["title"])
        for page in title_reader.pages:
            writer.add_page(page)
        back_links.append({"page_index": title_page_index, "rect": back_rect})

        # Suppression de la page de garde via une plage de pages explicite
        # (plutôt qu'un slice de reader.pages, moins fiable selon les versions).
        total_pages = len(doc["reader"].pages)
        if doc["start_page"] < total_pages:
            writer.append(
                doc["reader"],
                pages=(doc["start_page"], total_pages),
                import_outline=False,
            )

    for doc in unsectioned_docs:
        add_doc_pages(doc)

    for block in section_blocks:
        if block["divider_page_index"] is not None:
            divider_index = len(writer.pages)
            assert divider_index == block["divider_page_index"], (
                "désynchronisation des pages"
            )
            divider_reader, back_rect = make_divider_page(block["name"])
            for page in divider_reader.pages:
                writer.add_page(page)
            back_links.append({"page_index": divider_index, "rect": back_rect})

        for doc in block["docs"]:
            add_doc_pages(doc)

    # Signets (hiérarchiques pour les sections).
    writer.add_outline_item(clean_title(main_path), main_start_index)
    writer.add_outline_item(TITLE, toc_start_index)
    for doc in unsectioned_docs:
        writer.add_outline_item(doc["title"], doc["page_index"])
    for block in section_blocks:
        parent = writer.add_outline_item(block["name"], block["bookmark_page_index"])
        for doc in block["docs"]:
            writer.add_outline_item(doc["title"], doc["page_index"], parent=parent)

    # Liens cliquables sur les pages de la table des annexes.
    for link in link_rects:
        target_index = target_page_index[link["target_id"]]
        annotation = Link(
            rect=link["rect"],
            border=ArrayObject([FloatObject(0), FloatObject(0), FloatObject(0)]),
            target_page_index=target_index,
        )
        writer.add_annotation(
            page_number=toc_start_index + link["toc_page_index"],
            annotation=annotation,
        )

    # Liens « Retour à la table des annexes » sur chaque page de titre/séparation.
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

    # Garde-fou : aucune page ne doit être perdue silencieusement.
    if len(writer.pages) != expected_total_pages:
        raise RuntimeError(
            "Incohérence du nombre de pages "
            f"(attendu {expected_total_pages}, obtenu {len(writer.pages)}). "
            "Un PDF source est probablement corrompu."
        )

    with OUTPUT_FILE.open("wb") as f:
        writer.write(f)

    verify = PdfReader(str(OUTPUT_FILE))
    if len(verify.pages) != expected_total_pages:
        raise RuntimeError(
            "Le PDF fusionné ne contient pas le nombre de pages attendu "
            f"(attendu {expected_total_pages}, obtenu {len(verify.pages)})."
        )

    print()
    print(f"Créé : {OUTPUT_FILE.resolve()}")
    print()
    print(f"Document principal : {main_path.name} ({main_page_count} pages)")

    if unsectioned_docs:
        print()
        print("Annexes générales :")
        for doc in unsectioned_docs:
            print(
                f"- Page {doc['page_index'] + 1} : {doc['title']} "
                f"({doc['path'].name}, {doc['page_count']} pages)"
            )

    for block in section_blocks:
        print()
        print(f"Section : {block['name']}")
        for doc in block["docs"]:
            print(
                f"- Page {doc['page_index'] + 1} : {doc['title']} "
                f"({doc['path'].name}, {doc['page_count']} pages)"
            )


if __name__ == "__main__":
    create_merged_pdf()
