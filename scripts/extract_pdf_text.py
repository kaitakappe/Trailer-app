from __future__ import annotations

import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    if len(argv) >= 2:
        pdf_path = Path(argv[1])
    else:
        pdf_path = Path(r"C:\Users\takas\Desktop\重量計算書.pdf")

    print("path:", pdf_path)
    print("exists:", pdf_path.exists())
    if not pdf_path.exists():
        print("PDF not found")
        return 2
    print("size:", pdf_path.stat().st_size)

    print("\n== PyPDF2 ==")
    try:
        from PyPDF2 import PdfReader
        reader = PdfReader(str(pdf_path))
        print("pages:", len(reader.pages))
        for i, page in enumerate(reader.pages):
            text = (page.extract_text() or "").replace("\r", "")
            print(f"\n--- page {i+1} ---")
            print("text_len:", len(text))
            print(text)
    except Exception as e:
        print("PyPDF2 error:", type(e).__name__, e)

    print("\n== PyMuPDF ==")
    try:
        import fitz
        doc = fitz.open(str(pdf_path))
        print("pages:", doc.page_count)
        for i in range(doc.page_count):
            page = doc.load_page(i)
            text = page.get_text("text").replace("\r", "")
            print(f"\n--- page {i+1} ---")
            print("text_len:", len(text))
            print(text)

        out_dir = Path(__file__).resolve().parents[1] / "output"
        out_dir.mkdir(parents=True, exist_ok=True)
        png_path = out_dir / (pdf_path.stem + "_page1.png")
        pix = doc.load_page(0).get_pixmap(matrix=fitz.Matrix(2, 2))
        pix.save(str(png_path))
        print("\nrendered:", png_path)
        doc.close()
    except Exception as e:
        print("PyMuPDF error:", type(e).__name__, e)

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
