from PIL import Image, ImageDraw, ImageFont

img = Image.new("RGB", (512, 512), (20, 20, 20))
d = ImageDraw.Draw(img)

d.rounded_rectangle([48, 48, 464, 464], radius=48, outline=(255, 255, 255), width=6)
d.ellipse([196, 160, 316, 280], outline=(255, 255, 255), width=6)
d.rounded_rectangle([156, 300, 356, 380], radius=40, outline=(255, 255, 255), width=6)

text = "Фото\nпозже"
try:
    font = ImageFont.truetype("Arial.ttf", 46)
except:
    font = ImageFont.load_default()

d.text((210, 420), text, fill=(255, 255, 255), font=font, align="center")

img.save("placeholder.png")
print("saved placeholder.png")