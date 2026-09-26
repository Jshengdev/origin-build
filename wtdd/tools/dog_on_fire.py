"""Make the 'this is fine' picture: a real dog photo (dog.ceo) with flames drawn over it and the caption. Returns the path.
Nothing is copied from the original comic; the flames and the caption are drawn here (seeded, so the same photo gives
the same flames). Saved to ~/Pictures/wtdd/this-is-fine.jpg, JPEG q88, longest side 900 px. Needs the network twice."""
ARGS = {"caption": {"type": "string", "default": "this is fine"}}

OUT = "~/Pictures/wtdd/this-is-fine.jpg"


def run(caption="this is fine"):
    import io
    import os
    import random
    import requests
    from PIL import Image, ImageDraw, ImageFont
    r = requests.get("https://dog.ceo/api/breeds/image/random", timeout=15)
    r.raise_for_status()
    url = r.json()["message"]
    img = Image.open(io.BytesIO(requests.get(url, timeout=20).content)).convert("RGB")
    img.thumbnail((900, 900))
    w, h = img.size
    d = ImageDraw.Draw(img, "RGBA")
    rnd = random.Random(7)
    for _ in range(46):  # flames: layered tongues along the bottom and sides, drawn, not pasted
        x = rnd.randint(0, w)
        base = h - rnd.randint(0, int(h * 0.12))
        fh = rnd.randint(int(h * 0.18), int(h * 0.55))
        fw = rnd.randint(int(w * 0.05), int(w * 0.14))
        col = rnd.choice([(255, 90, 20, 190), (255, 150, 30, 170), (255, 210, 60, 150), (230, 40, 10, 200)])
        d.polygon([(x - fw, base), (x - fw // 3, base - fh * 0.55), (x, base - fh), (x + fw // 3, base - fh * 0.6), (x + fw, base)], fill=col)
    for _ in range(12):  # sparks
        x, y = rnd.randint(0, w), rnd.randint(int(h * 0.3), h)
        d.ellipse([x - 6, y - 6, x + 6, y + 6], fill=(255, 220, 90, 220))
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Impact.ttf", int(h * 0.11))
    except OSError:  # not on a Mac: PIL's built-in font; the picture is still made, only the caption face differs
        font = ImageFont.load_default()
    text = caption.upper()
    x, y = (w - d.textlength(text, font=font)) / 2, int(h * 0.04)
    for dx, dy in ((-3, -3), (3, -3), (-3, 3), (3, 3), (0, 4), (0, -4), (4, 0), (-4, 0)):
        d.text((x + dx, y + dy), text, font=font, fill=(0, 0, 0, 255))
    d.text((x, y), text, font=font, fill=(255, 255, 255, 255))
    out = os.path.expanduser(OUT)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    img.save(out, "JPEG", quality=88)
    return {"file": out, "source": url, "size": [w, h]}
