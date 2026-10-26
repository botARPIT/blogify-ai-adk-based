"""Document conversion for completed blog content."""

import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from starlette.concurrency import run_in_threadpool


@dataclass(frozen=True)
class BlogExport:
    path: Path
    filename: str
    media_type: str
    temp_dir: str


class BlogExportService:
    async def create(self, markdown: str, title: str, format: Literal["pdf", "docx"]) -> BlogExport:
        suffix = ".pdf" if format == "pdf" else ".docx"
        filename = re.sub(r"[^\w.-]+", "-", title, flags=re.UNICODE).strip("-._")[:100] or "blog"
        temp_dir = tempfile.mkdtemp(prefix="blogify-export-")
        output = Path(temp_dir) / f"{filename}{suffix}"
        try:
            import pypandoc  # type: ignore[import-not-found]

            pypandoc.get_pandoc_path()
            if format == "pdf" and shutil.which("xelatex") is None:
                raise RuntimeError(
                    "PDF export is unavailable because XeLaTeX is not installed in the API runtime."
                )

            def convert() -> None:
                pypandoc.convert_text(
                    markdown,
                    to=format,
                    format="md",
                    outputfile=str(output),
                    extra_args=["--pdf-engine=xelatex"] if format == "pdf" else [],
                )

            await run_in_threadpool(convert)
        except ImportError as exc:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise RuntimeError(
                "Document export is unavailable because pypandoc is not installed on the API server."
            ) from exc
        except Exception:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise
        return BlogExport(
            path=output,
            filename=f"{filename}{suffix}",
            media_type="application/pdf"
            if format == "pdf"
            else "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            temp_dir=temp_dir,
        )
