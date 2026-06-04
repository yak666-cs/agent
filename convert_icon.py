"""将 OIP-C.webp 转换为多尺寸 kai_agent.ico"""
import struct
import io
from PIL import Image
import os

SIZES = [16, 32, 48, 64, 128, 256]

def webp_to_ico(webp_path: str, ico_path: str):
    source = Image.open(webp_path).convert("RGBA")
    png_data_list = []
    for size in SIZES:
        img = source.resize((size, size), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        png_data_list.append(buf.getvalue())

    num = len(SIZES)
    hdr_size = 6 + 16 * num
    with open(ico_path, "wb") as f:
        f.write(struct.pack("<HHH", 0, 1, num))
        offset = hdr_size
        for i, sz in enumerate(SIZES):
            png = png_data_list[i]
            w = 0 if sz >= 256 else sz
            h = 0 if sz >= 256 else sz
            f.write(struct.pack("<BBBBHHII", w, h, 0, 0, 1, 32, len(png), offset))
            offset += len(png)
        for png in png_data_list:
            f.write(png)
    print(f"图标已生成: {ico_path}")

if __name__ == "__main__":
    base = os.path.dirname(os.path.abspath(__file__))
    webp_path = os.path.join(os.path.dirname(base), "OIP-C.webp")
    ico_path = os.path.join(base, "kai_agent.ico")
    webp_to_ico(webp_path, ico_path)
