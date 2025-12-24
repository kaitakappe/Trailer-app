from __future__ import annotations

"""タイヤ負荷率及び接地圧計算書PDF（例の体裁風）

画像例の構成:
- 《タイヤ負荷率及び接地圧計算書》
- "後輪タイヤ及び本数11R22.5-14PR：12本" のような対象行
- <a> 負荷率
- <b> 接地圧

計算式:
  負荷率[%] = Wr / (n × 推奨荷重/本) × 100
  接地圧[kg/cm] = Wr / (n × 設置幅/本)

※ここで n は対象側のタイヤ本数（例: 後輪12本）
"""

import os
from dataclasses import dataclass

try:
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    _REPORTLAB_AVAILABLE = True
except ImportError:
    _REPORTLAB_AVAILABLE = False


def _register_japanese_font(font_name: str = "JPFont") -> str:
    if not _REPORTLAB_AVAILABLE:
        return "Helvetica"

    for font_path in [
        "C:/Windows/Fonts/msgothic.ttc",
        "C:/Windows/Fonts/meiryo.ttc",
        "C:/Windows/Fonts/yugothic.ttf",
        "ipaexg.ttf",
        "ipaexm.ttf",
        "fonts/ipaexg.ttf",
        "fonts/ipaexm.ttf",
    ]:
        if os.path.exists(font_path):
            try:
                pdfmetrics.registerFont(TTFont(font_name, font_path))
                return font_name
            except Exception:
                pass

    return "Helvetica"


def _fmt_int(value: float) -> str:
    return f"{value:.0f}"


def _fmt_1(value: float) -> str:
    return f"{value:.1f}"


def _draw_fraction(
    c,
    *,
    x: float,
    y: float,
    numerator: str,
    denominator: str,
    font: str,
    size: float,
    line_pad: float = 1.5,
) -> float:
    """簡易の分数描画。

    戻り値: 分数ブロックの高さ（次のy計算用）

    y は "分数の中心" に近いイメージで、
    numerator は y+size*0.6、denominator は y-size*0.9 に配置。
    """

    c.setFont(font, size)
    num_w = c.stringWidth(numerator, font, size)
    den_w = c.stringWidth(denominator, font, size)
    block_w = max(num_w, den_w)

    cx = x + block_w / 2.0

    num_y = y + size * 0.55
    den_y = y - size * 0.95

    c.drawCentredString(cx, num_y, numerator)
    c.drawCentredString(cx, den_y, denominator)

    line_y = y - line_pad
    c.setLineWidth(0.8)
    c.line(x, line_y, x + block_w, line_y)

    return size * 1.9


@dataclass(frozen=True)
class TireLoadContactSheetInput:
    target_label: str  # 例: 後輪
    tire_size_text: str  # 例: 11R22.5-14PR
    tire_count_n: int  # 例: 12
    axle_load_wr_kg: float  # Wr
    recommended_load_per_tire_kg: float  # 推奨荷重/本
    install_width_per_tire_cm: float  # 設置幅/本


class TireLoadContactSheet:
    def __init__(
        self,
        *,
        data: TireLoadContactSheetInput,
        header_text: str = "",
        load_rate_limit_percent: float = 100.0,
        contact_pressure_limit_kg_per_cm: float = 200.0,
    ):
        self.data = data
        self.header_text = header_text
        self.load_rate_limit_percent = float(load_rate_limit_percent)
        self.contact_pressure_limit_kg_per_cm = float(contact_pressure_limit_kg_per_cm)

    def load_rate_percent(self) -> float:
        d = self.data
        denom = float(d.tire_count_n) * float(d.recommended_load_per_tire_kg)
        if denom <= 0:
            return 0.0
        return float(d.axle_load_wr_kg) / denom * 100.0

    def contact_pressure_kg_per_cm(self) -> float:
        d = self.data
        denom = float(d.tire_count_n) * float(d.install_width_per_tire_cm)
        if denom <= 0:
            return 0.0
        return float(d.axle_load_wr_kg) / denom

    def generate_pdf(self, filepath: str) -> bool:
        if not _REPORTLAB_AVAILABLE:
            return False

        try:
            c = canvas.Canvas(filepath, pagesize=A4)
            w, h = A4
            font = _register_japanese_font()
            self._draw_page(c, w, h, font)
            c.showPage()
            c.save()
            return True
        except Exception:
            return False

    def _draw_page(self, c, w: float, h: float, font: str) -> None:
        left = 70
        top = 70

        y = h - top

        if self.header_text:
            c.setFont(font, 9)
            c.drawCentredString(w / 2, y, self.header_text)
            y -= 18

        c.setFont(font, 14)
        c.drawCentredString(w / 2, y, "《タイヤ負荷率及び接地圧計算書》")
        y -= 36

        d = self.data
        target = (d.target_label or "").strip() or "後輪"
        tire_txt = (d.tire_size_text or "").strip()
        c.setFont(font, 11)
        if tire_txt:
            c.drawString(left, y, f"{target}タイヤ及び本数{tire_txt}：{d.tire_count_n}本")
        else:
            c.drawString(left, y, f"{target}タイヤ及び本数：{d.tire_count_n}本")
        y -= 34

        # (a) 負荷率
        c.setFont(font, 11)
        c.drawString(left - 25, y, "〈a〉")
        c.drawString(left, y, "負荷率")
        y -= 28

        # Wr / (n×推奨荷重) ×100
        frac_h = _draw_fraction(
            c,
            x=left + 40,
            y=y,
            numerator="Wr",
            denominator="n × 推奨荷重",
            font=font,
            size=16,
        )
        c.setFont(font, 14)
        c.drawString(left + 200, y - 6, "× 100")
        y -= frac_h + 10

        # = 24830 / (12×2500) ×100
        wr_s = _fmt_int(d.axle_load_wr_kg)
        n_s = f"{int(d.tire_count_n)}"
        rec_s = _fmt_int(d.recommended_load_per_tire_kg)
        c.setFont(font, 12)
        c.drawString(left + 5, y, "=")
        frac_h = _draw_fraction(
            c,
            x=left + 40,
            y=y,
            numerator=wr_s,
            denominator=f"{n_s} × {rec_s}",
            font=font,
            size=16,
        )
        c.setFont(font, 14)
        c.drawString(left + 200, y - 6, "× 100")
        y -= frac_h + 16

        load_rate = self.load_rate_percent()
        c.setFont(font, 12)
        c.drawString(
            left + 40,
            y,
            f"= {_fmt_1(load_rate)}% ≤ {_fmt_int(self.load_rate_limit_percent)}%",
        )
        y -= 56

        # (b) 接地圧
        c.setFont(font, 11)
        c.drawString(left - 25, y, "〈b〉")
        c.drawString(left, y, "接地圧")
        y -= 28

        frac_h = _draw_fraction(
            c,
            x=left + 40,
            y=y,
            numerator="Wr",
            denominator="n × 設置幅",
            font=font,
            size=16,
        )
        y -= frac_h + 10

        width_s = _fmt_1(d.install_width_per_tire_cm)
        c.setFont(font, 12)
        c.drawString(left + 5, y, "=")
        frac_h = _draw_fraction(
            c,
            x=left + 40,
            y=y,
            numerator=wr_s,
            denominator=f"{n_s} × {width_s}",
            font=font,
            size=16,
        )
        y -= frac_h + 16

        pressure = self.contact_pressure_kg_per_cm()
        c.setFont(font, 12)
        c.drawString(
            left + 40,
            y,
            f"= {_fmt_1(pressure)}kg/cm ≤ {_fmt_int(self.contact_pressure_limit_kg_per_cm)}kg/cm",
        )
