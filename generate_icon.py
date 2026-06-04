"""生成 ChatGPT 风格图标 —— 黑底白星"""
import struct
import io
import math
from PIL import Image, ImageDraw

SIZES = [16, 32, 48, 64, 128, 256]


def create_chatgpt_icon(path: str):
    png_data_list = []
    for size in SIZES:
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        cx = cy = size // 2
        r = size * 0.46

        # 黑底圆
        draw.ellipse(
            [cx - r, cy - r, cx + r, cy + r],
            fill=(26, 26, 30, 255),
        )

        # 白色星芒
        star_r = r * 0.5
        points = []
        for i in range(8):
            angle = math.pi / 4 * i - math.pi / 2
            radius = star_r if i % 2 == 0 else star_r * 0.25
            px = cx + radius * math.cos(angle)
            py = cy + radius * math.sin(angle)
            points.append((px, py))
        draw.polygon(points, fill=(240, 242, 245, 255))

        # 星心白点
        dot_r = r * 0.08
        draw.ellipse(
            [cx - dot_r, cy - dot_r, cx + dot_r, cy + dot_r],
            fill=(255, 255, 255, 255),
        )

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        png_data_list.append(buf.getvalue())

    num = len(SIZES)
    hdr_size = 6 + 16 * num

    with open(path, "wb") as f:
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

    print(f"ChatGPT 风格图标已生成: {path} ({num} sizes)")


if __name__ == "__main__":
    import os
    create_chatgpt_icon(os.path.join(os.path.dirname(__file__), "kai_agent.ico"))
