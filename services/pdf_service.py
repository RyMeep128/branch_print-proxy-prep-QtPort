from __future__ import annotations

import pdf

from models import as_project_state


def generate_pdf(project_like, crop_dir, size, pdf_path, print_fn):
    return pdf.generate(as_project_state(project_like), crop_dir, size, pdf_path, print_fn)
