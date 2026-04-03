from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pdf

from models import ProjectState, as_project_state


@dataclass
class PDFGenerationResult:
    state: ProjectState
    pdf_path: str
    pages: object


def generate_pdf(
    project_like,
    crop_dir,
    size,
    pdf_path,
    print_fn: Callable[[str], None],
) -> PDFGenerationResult:
    state = as_project_state(project_like)
    pages = pdf.generate(state, crop_dir, size, pdf_path, print_fn)
    return PDFGenerationResult(state=state, pdf_path=pdf_path, pages=pages)
