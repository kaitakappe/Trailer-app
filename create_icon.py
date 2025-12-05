"""アプリケーションアイコン生成スクリプト"""
from PIL import Image, ImageDraw, ImageFont
import os

def create_app_icon():
    """トレーラー計算アプリのアイコンを生成"""
    # 複数サイズのアイコンを生成
    sizes = [256, 128, 64, 48, 32, 16]
    images = []
    
    for size in sizes:
        # 画像作成
        img = Image.new('RGBA', (size, size), (255, 255, 255, 0))
        draw = ImageDraw.Draw(img)
        
        # 背景（丸角四角形）
        margin = size // 16
        bg_color = (45, 85, 160, 255)  # 青色
        draw.rounded_rectangle(
            [margin, margin, size - margin, size - margin],
            radius=size // 8,
            fill=bg_color
        )
        
        # トレーラーの簡易図形を描画
        # スケール調整
        scale = size / 256.0
        
        # 荷台（矩形）
        bed_left = int(80 * scale)
        bed_top = int(80 * scale)
        bed_width = int(140 * scale)
        bed_height = int(70 * scale)
        bed_color = (220, 220, 220, 255)  # 明るいグレー
        draw.rounded_rectangle(
            [bed_left, bed_top, bed_left + bed_width, bed_top + bed_height],
            radius=int(5 * scale),
            fill=bed_color,
            outline=(180, 180, 180, 255),
            width=max(1, int(2 * scale))
        )
        
        # 連結部（小さい円）
        coupler_x = int(70 * scale)
        coupler_y = int(115 * scale)
        coupler_r = int(8 * scale)
        draw.ellipse(
            [coupler_x - coupler_r, coupler_y - coupler_r,
             coupler_x + coupler_r, coupler_y + coupler_r],
            fill=(255, 200, 0, 255),  # 黄色
            outline=(200, 150, 0, 255),
            width=max(1, int(2 * scale))
        )
        
        # 車輪（2つ）
        wheel_y = int(160 * scale)
        wheel_r = int(15 * scale)
        wheel_color = (60, 60, 60, 255)  # 濃いグレー
        
        # 前輪
        wheel1_x = int(120 * scale)
        draw.ellipse(
            [wheel1_x - wheel_r, wheel_y - wheel_r,
             wheel1_x + wheel_r, wheel_y + wheel_r],
            fill=wheel_color,
            outline=(40, 40, 40, 255),
            width=max(1, int(2 * scale))
        )
        
        # 後輪
        wheel2_x = int(180 * scale)
        draw.ellipse(
            [wheel2_x - wheel_r, wheel_y - wheel_r,
             wheel2_x + wheel_r, wheel_y + wheel_r],
            fill=wheel_color,
            outline=(40, 40, 40, 255),
            width=max(1, int(2 * scale))
        )
        
        # フレーム（線）
        frame_y = int(150 * scale)
        frame_width = max(1, int(3 * scale))
        draw.line(
            [(coupler_x, coupler_y), (bed_left, frame_y)],
            fill=(180, 180, 180, 255),
            width=frame_width
        )
        draw.line(
            [(bed_left, frame_y), (bed_left + bed_width, frame_y)],
            fill=(180, 180, 180, 255),
            width=frame_width
        )
        
        # 小さいサイズの場合は文字を省略
        if size >= 64:
            # 「T」の文字を追加（Trailer）
            try:
                font_size = int(size * 0.35)
                # Windows標準フォントを試す
                font_paths = [
                    'C:/Windows/Fonts/arial.ttf',
                    'C:/Windows/Fonts/calibri.ttf',
                ]
                font = None
                for font_path in font_paths:
                    if os.path.exists(font_path):
                        try:
                            font = ImageFont.truetype(font_path, font_size)
                            break
                        except:
                            pass
                
                if font:
                    text = "T"
                    # テキストのバウンディングボックスを取得
                    bbox = draw.textbbox((0, 0), text, font=font)
                    text_width = bbox[2] - bbox[0]
                    text_height = bbox[3] - bbox[1]
                    
                    text_x = (size - text_width) // 2
                    text_y = int(size * 0.55)
                    
                    # 影
                    draw.text(
                        (text_x + 2, text_y + 2),
                        text,
                        fill=(0, 0, 0, 100),
                        font=font
                    )
                    # 本文
                    draw.text(
                        (text_x, text_y),
                        text,
                        fill=(255, 255, 255, 255),
                        font=font
                    )
            except Exception as e:
                print(f"フォント描画エラー (size {size}): {e}")
        
        images.append(img)
    
    # ICOファイルとして保存（Windowsアイコン）
    ico_path = 'app_icon.ico'
    images[0].save(
        ico_path,
        format='ICO',
        sizes=[(s, s) for s in sizes]
    )
    
    # PNG版も保存（最大サイズ）
    png_path = 'app_icon.png'
    images[0].save(png_path, format='PNG')
    
    print(f"アイコン生成完了:")
    print(f"  - {ico_path} (Windows用 .ico)")
    print(f"  - {png_path} (PNG形式)")
    
    return ico_path, png_path

if __name__ == '__main__':
    create_app_icon()
