from pathlib import Path
import re
import shutil
from urllib.parse import unquote

# 你的 Markdown 文件路径
md_path = Path(r"D:\尚硅谷-2026年1月开课大模型智能体线上速成班V2(1).0\05_项目_掌柜智库\代码资料教案\教案\资料\01【掌柜智库】项目简介.md")

# 你的真实图片目录
image_dir = Path(r"D:\尚硅谷-2026年1月开课大模型智能体线上速成班V2(1).0\05_项目_掌柜智库\代码资料教案\教案\images")

# 备份文件
backup_path = md_path.with_name(md_path.name + ".bak")

if not md_path.exists():
    raise FileNotFoundError(f"Markdown 文件不存在：{md_path}")

if not image_dir.exists():
    raise FileNotFoundError(f"图片目录不存在：{image_dir}")

# 备份原始 md
shutil.copy2(md_path, backup_path)

text = md_path.read_text(encoding="utf-8")

total_replace = 0

# 1. 修复 HTML 写法：
# <img src="images/xxx.png" />
# 改成：
# <img src="../images/xxx.png" />
text, count1 = re.subn(
    r'(<img\b[^>]*?\bsrc\s*=\s*["\'])images[\\/]',
    r'\1../images/',
    text,
    flags=re.IGNORECASE
)
total_replace += count1

# 2. 修复 Markdown 写法：
# ![](images/xxx.png)
# 改成：
# ![](../images/xxx.png)
text, count2 = re.subn(
    r'(!\[[^\]]*\]\(\s*)images[\\/]',
    r'\1../images/',
    text
)
total_replace += count2

# 写回文件
md_path.write_text(text, encoding="utf-8")

print("=" * 80)
print("图片路径修复完成")
print("=" * 80)
print(f"Markdown 文件：{md_path}")
print(f"备份文件：{backup_path}")
print(f"HTML img 替换数量：{count1}")
print(f"Markdown 图片替换数量：{count2}")
print(f"总替换数量：{total_replace}")

# 检查图片是否真实存在
html_imgs = re.findall(
    r'<img\b[^>]*?\bsrc\s*=\s*["\']([^"\']+)["\']',
    text,
    flags=re.IGNORECASE
)

md_imgs = re.findall(
    r'!\[[^\]]*\]\(\s*([^) \t\r\n]+)',
    text
)

all_imgs = html_imgs + md_imgs

target_imgs = []
for img in all_imgs:
    img = img.strip().strip('"').strip("'")
    if img.startswith("../images/") or img.startswith("../images\\"):
        target_imgs.append(img)

missing = []

print("\n检测前 10 个图片引用：")
print("-" * 80)

for img in target_imgs[:10]:
    relative_name = img.replace("../images/", "", 1).replace("../images\\", "", 1)
    relative_name = unquote(relative_name)
    real_path = image_dir / relative_name

    if real_path.exists():
        print(f"[存在] {img}")
    else:
        print(f"[不存在] {img}")
        missing.append((img, real_path))

# 检查全部图片是否存在
for img in target_imgs[10:]:
    relative_name = img.replace("../images/", "", 1).replace("../images\\", "", 1)
    relative_name = unquote(relative_name)
    real_path = image_dir / relative_name

    if not real_path.exists():
        missing.append((img, real_path))

print("\n图片引用总数：", len(target_imgs))

if missing:
    print("\n以下图片文件不存在，请检查文件名是否一致：")
    print("-" * 80)
    for img, real_path in missing:
        print(f"{img}")
        print(f"实际查找位置：{real_path}")
else:
    print("\n所有 ../images/ 图片引用都能找到真实文件。")

print("=" * 80)
print("完成。现在重新用 Typora 打开 Markdown 文件即可。")
print("=" * 80)