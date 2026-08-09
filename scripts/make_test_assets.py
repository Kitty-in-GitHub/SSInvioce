from pathlib import Path

from PIL import Image, ImageDraw
import pymupdf

root = Path("data/test_tmp")
root.mkdir(parents=True, exist_ok=True)

doc = pymupdf.open()
page = doc.new_page(width=595, height=400)
page.insert_text((50, 80), "Invoice TEST", fontsize=24)
doc.save(root / "invoice.pdf")
doc.close()

img = Image.new("RGB", (400, 900), (245, 245, 245))
ImageDraw.Draw(img).text((20, 20), "ORDER", fill=(0, 0, 0))
img.save(root / "order.png")

img2 = Image.new("RGB", (500, 900), (230, 240, 255))
ImageDraw.Draw(img2).text((20, 20), "PAYMENT wechat", fill=(0, 0, 0))
img2.save(root / "payment_wechat.png")

print("assets ok")
