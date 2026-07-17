"""In thô các bảng của vài trang PDF để chốt mapping cột."""
import sys
import pdfplumber

path, start, end = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
with pdfplumber.open(path) as pdf:
    for i in range(start, min(end, len(pdf.pages))):
        print(f"===== PAGE {i} =====")
        for t in pdf.pages[i].extract_tables():
            for row in t:
                print([str(c)[:40] if c else "" for c in row])
