from __future__ import annotations

"""セミトレーラー用 重量計算書PDF（添付様式風）

添付画像の体裁に合わせて、以下の構成でPDFを生成する。
- 《重量計算書》
- （1）空車時重量分布（No/名称/Wi/Li/Wi×Li/Hi/Wi×Hi の表 + 合計Σ行）
- (a)(b) の前後軸重量計算
- （2）荷台オフセット（O.S.の算出式表示）
- （3）積車時重量分布（WF/WR の算出式表示）

※“そっくり”の最優先はレイアウトと項目順序。数値は入力に基づき算出する。
"""

import os
from dataclasses import dataclass
from typing import List, Sequence, Tuple

try:
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    _REPORTLAB_AVAILABLE = True
except ImportError:
    _REPORTLAB_AVAILABLE = False


def _register_japanese_font(font_name: str = "JPFont") -> str:
    """日本語フォントを登録し、フォント名を返す（無ければHelvetica）。"""
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


def _round_to_step(value: float, step: float) -> float:
    if step == 0:
        return value
    if value >= 0:
        return float(int((value + step / 2.0) / step) * step)
    return -float(int(((-value) + step / 2.0) / step) * step)


@dataclass(frozen=True)
class SemiTrailerComponent:
    no: str
    name: str
    wi_kg: float
    li_mm: float
    hi_mm: float

    @property
    def moment_wi_li(self) -> float:
        return self.wi_kg * self.li_mm

    @property
    def moment_wi_hi(self) -> float:
        return self.wi_kg * self.hi_mm


def parse_components_tsv(text: str) -> List[SemiTrailerComponent]:
    """TSV/CSV風の部品表をパース。

    形式:
      No\t名称\tWi\tLi\tHi
      (1)\tエアカプラカバー\t5\t-700\t1510

    空行と先頭#は無視。ヘッダー行はスキップされる。
    """

    rows: List[SemiTrailerComponent] = []
    if not text:
        return rows

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        sep = "\t" if "\t" in line else ","
        parts = [p.strip() for p in line.split(sep)]
        if len(parts) < 5:
            continue

        no, name, wi, li, hi = parts[0], parts[1], parts[2], parts[3], parts[4]
        if no.lower() in ("no", "番号"):
            continue

        try:
            rows.append(
                SemiTrailerComponent(
                    no=no,
                    name=name,
                    wi_kg=float(wi),
                    li_mm=float(li),
                    hi_mm=float(hi),
                )
            )
        except ValueError:
            continue

    return rows


class WeightCalculationSheet:
    """添付様式風の『重量計算書』をPDF生成（セミトレーラー想定）。"""

    def __init__(
        self,
        *,
        wheelbase_mm: float,
        payload_max_kg: float,
        os_a_mm: float,
        os_b_mm: float = 0.0,
        os_c_mm: float,
        os_d_mm: float,
        components: Sequence[SemiTrailerComponent],
        header_text: str = "",
    ):
        self.wheelbase_mm = float(wheelbase_mm)
        self.payload_max_kg = float(payload_max_kg)
        self.os_a_mm = float(os_a_mm)
        self.os_b_mm = float(os_b_mm)
        self.os_c_mm = float(os_c_mm)
        self.os_d_mm = float(os_d_mm)
        self.components = list(components)
        self.header_text = header_text

    def os_mm(self) -> float:
        return (self.os_a_mm / 2.0) + self.os_b_mm - self.os_c_mm - self.os_d_mm

    def totals(self) -> Tuple[float, float, float]:
        sum_w = sum(c.wi_kg for c in self.components)
        sum_wl = sum(c.moment_wi_li for c in self.components)
        sum_wh = sum(c.moment_wi_hi for c in self.components)
        return sum_w, sum_wl, sum_wh

    def empty_rear_axle_kg(self) -> float:
        _, sum_wl, _ = self.totals()
        if self.wheelbase_mm == 0:
            return 0.0
        return sum_wl / self.wheelbase_mm

    def empty_front_axle_kg(self) -> float:
        sum_w, _, _ = self.totals()
        return sum_w - self.empty_rear_axle_kg()

    def cg_l_mm(self) -> float:
        sum_w, sum_wl, _ = self.totals()
        return (sum_wl / sum_w) if sum_w else 0.0

    def cg_h_mm(self) -> float:
        sum_w, _, sum_wh = self.totals()
        return (sum_wh / sum_w) if sum_w else 0.0

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
        left = 45
        right = 45
        top = 32

        c.setFont(font, 9)
        c.drawCentredString(w / 2, h - top, self.header_text)

        title_y = h - top - 28
        c.setFont(font, 12)
        c.drawCentredString(w / 2, title_y, "《重量計算書》")

        y = title_y - 22
        c.setFont(font, 10)
        c.drawString(left, y, "（1）空車時重量分布")
        y -= 10

        y = self._draw_empty_table(c, left, y, w - left - right, font)
        y -= 10

        y = self._draw_empty_formulas(c, left, y, font)
        y -= 10

        c.setFont(font, 10)
        c.drawString(left, y, "（2）荷台オフセット（荷台幅＝一定）")
        y -= 14
        c.setFont(font, 9)
        os_val = self.os_mm()
        if abs(self.os_b_mm) < 1e-9:
            os_formula = (
                f"O.S. = ({self.os_a_mm:.0f} ÷ 2) - {self.os_c_mm:.0f} - {self.os_d_mm:.0f} = {os_val:.0f}mm  ({os_val:.0f}mm)"
            )
        else:
            os_formula = (
                f"O.S. = ({self.os_a_mm:.0f} ÷ 2) + {self.os_b_mm:.0f} - {self.os_c_mm:.0f} - {self.os_d_mm:.0f} = {os_val:.0f}mm  ({os_val:.0f}mm)"
            )
        c.drawString(left + 18, y, os_formula)
        y -= 20

        c.setFont(font, 10)
        c.drawString(left, y, "（3）積車時重量分布")
        y -= 14
        c.setFont(font, 9)
        self._draw_loaded_formulas(c, left, y, font)

    def _draw_empty_table(self, c, x: float, y_top: float, width: float, font: str) -> float:
        col_w = [34, 130, 48, 56, 78, 56, 78]
        row_h_header = 30
        # 部品数に応じて行の高さを動的に調整（最小9、最大16）
        num_rows = len(self.components)
        available_height = y_top - 200  # ページ下部に200ptの余白を確保
        if available_height < row_h_header + (num_rows + 1) * 9:
            # 最小の行高さ(9pt)でも収まらない場合は、余白を減らす
            available_height = y_top - 100
        calculated_row_h = (available_height - row_h_header) / (num_rows + 1) if num_rows > 0 else 16  # +1は合計行
        row_h = max(9, min(16, calculated_row_h))

        headers = [
            "No.",
            "名　称",
            "重　量\nWi\n(kg)",
            "ヒッチカプラー\nLi\n(mm)",
            "モーメント\nWi × Li\n(kg-mm)",
            "重心高\nHi\n(mm)",
            "モーメント\nWi × Hi\n(kg-mm)",
        ]

        rows = self.components
        sum_w, sum_wl, sum_wh = self.totals()
        avg_li = (sum_wl / sum_w) if sum_w else 0.0
        avg_hi = (sum_wh / sum_w) if sum_w else 0.0
        avg_li_r = _round_to_step(avg_li, 5.0)
        avg_hi_r = _round_to_step(avg_hi, 5.0)

        height = row_h_header + (len(rows) + 1) * row_h
        y_bottom = y_top - height

        c.setLineWidth(0.8)
        c.rect(x, y_bottom, sum(col_w), height)

        cx = x
        for wcol in col_w[:-1]:
            cx += wcol
            c.line(cx, y_top, cx, y_bottom)

        c.line(x, y_top - row_h_header, x + sum(col_w), y_top - row_h_header)
        ry = y_top - row_h_header
        for _ in range(len(rows)):
            ry -= row_h
            c.line(x, ry, x + sum(col_w), ry)

        c.setFont(font, 8)
        cx = x
        for i, text in enumerate(headers):
            lines = text.split("\n")
            line_y = y_top - 10
            for li, t in enumerate(lines):
                c.drawCentredString(cx + col_w[i] / 2, line_y - li * 9, t)
            cx += col_w[i]

        # フォントサイズも行の高さに応じて調整
        font_size = max(6, min(8, row_h - 4))
        c.setFont(font, font_size)
        # テキストのy位置をセルの中央に配置（下から数えるので row_h/2 - font_size/3）
        row_y = y_top - row_h_header - row_h / 2 - font_size / 3
        for comp in rows:
            cells = [
                comp.no,
                comp.name,
                f"{comp.wi_kg:.0f}",
                f"{comp.li_mm:.0f}",
                f"{comp.moment_wi_li:.0f}",
                f"{comp.hi_mm:.0f}",
                f"{comp.moment_wi_hi:.0f}",
            ]
            cx = x
            for i, cell in enumerate(cells):
                if i == 1:
                    c.drawString(cx + 3, row_y, str(cell))
                else:
                    c.drawCentredString(cx + col_w[i] / 2, row_y, str(cell))
                cx += col_w[i]
            row_y -= row_h

        cells = [
            "Σ",
            "車両重量",
            f"{sum_w:.0f}",
            f"({avg_li_r:.0f})",
            f"{sum_wl:.0f}",
            f"({avg_hi_r:.0f})",
            f"{sum_wh:.0f}",
        ]
        cx = x
        for i, cell in enumerate(cells):
            if i == 1:
                c.drawString(cx + 3, row_y, str(cell))
            else:
                c.drawCentredString(cx + col_w[i] / 2, row_y, str(cell))
            cx += col_w[i]

        return y_bottom

    def _draw_empty_formulas(self, c, x: float, y: float, font: str) -> float:
        sum_w, sum_wl, _ = self.totals()
        wb = self.wheelbase_mm
        wr = self.empty_rear_axle_kg()
        wf = self.empty_front_axle_kg()
        wr_r = _round_to_step(wr, 10.0)
        wf_r = _round_to_step(wf, 10.0)

        c.setFont(font, 9)
        c.drawString(x, y, "(a) 後軸")
        y -= 13
        c.drawString(
            x + 18,
            y,
            f"Wr = Σ (wi × Li) ÷ W.B. = {sum_wl:.0f} ÷ {wb:.0f} = {wr:.2f}kg  ({wr_r:.0f}kg)",
        )
        y -= 13
        c.drawString(x + 18, y, f"W.B.(ホイールベース) = {wb:.0f}mm")
        y -= 16
        c.drawString(x, y, "(b) 前軸")
        y -= 13
        c.drawString(
            x + 18,
            y,
            f"Wf = Σ Wi - Wr = {sum_w:.0f} - {wr:.2f} = {wf:.2f}kg  ({wf_r:.0f}kg)",
        )
        y -= 8
        return y

    def _draw_loaded_formulas(self, c, x: float, y: float, font: str) -> float:
        wb = self.wheelbase_mm
        osv = self.os_mm()
        P = self.payload_max_kg
        wf = self.empty_front_axle_kg()
        wr = self.empty_rear_axle_kg()

        pf = (P * osv / wb) if wb else 0.0
        WF = wf + pf
        WR = wr + (P - pf)
        wf_r = _round_to_step(wf, 10.0)
        wr_r = _round_to_step(wr, 10.0)
        pf_r = _round_to_step(pf, 10.0)
        WF_r = _round_to_step(WF, 10.0)
        WR_r = _round_to_step(WR, 10.0)

        c.drawString(x + 10, y, "(a) 前軸")
        y -= 13
        c.drawString(x + 28, y, f"WF = wf + (P × O.S.) ÷ W.B.　但し最大積載量P＝{P:.0f}kg")
        y -= 13
        c.drawString(x + 28, y, f"　　= {wf:.2f} + {P:.0f} × {osv:.0f} ÷ {wb:.0f}")
        y -= 13
        c.drawString(x + 28, y, f"　　= {wf:.2f} + {pf:.2f}")
        y -= 13
        c.drawString(x + 28, y, f"　　= {WF:.2f}kg  ({WF_r:.0f}kg)")
        y -= 16

        c.drawString(x + 10, y, "(b) 後軸")
        y -= 13
        c.drawString(x + 28, y, "WR = wr + (P − Pf)　但し Pf＝P × O.S. ÷ W.B.")
        y -= 13
        c.drawString(x + 28, y, f"　　= {wr:.2f} + ({P:.0f} − {pf:.2f})")
        y -= 13
        c.drawString(x + 28, y, f"　　= {WR:.2f}kg  ({WR_r:.0f}kg)")
        y -= 16

        c.drawString(x + 10, y, "(c) 車両総重量")
        y -= 13
        gvw = WF_r + WR_r
        c.drawString(x + 28, y, f"G.V.W. = WF + WR = {WF_r:.0f} + {WR_r:.0f} = {gvw:.0f}kg")
        y -= 18

        c.setFont(font, 10)
        c.drawString(x, y, "（4）重心位置")
        y -= 14
        c.setFont(font, 9)
        sum_w, sum_wl, sum_wh = self.totals()
        L = (sum_wl / sum_w) if sum_w else 0.0
        H = (sum_wh / sum_w) if sum_w else 0.0
        Lr = _round_to_step(L, 5.0)
        Hr = _round_to_step(H, 5.0)
        c.drawString(x + 10, y, "(a) 水平方向（ヒッチカプラーからの距離）")
        y -= 13
        c.drawString(x + 28, y, f"L = Σ (Wi × Li) ÷ Σ W = {sum_wl:.0f} ÷ {sum_w:.0f} = {L:.2f}mm  ({Lr:.0f}mm)")
        y -= 13
        c.drawString(x + 10, y, "(b) 重心方向（地面からの距離）")
        y -= 13
        c.drawString(x + 28, y, f"H = Σ (Wi × Hi) ÷ Σ W = {sum_wh:.0f} ÷ {sum_w:.0f} = {H:.2f}mm  ({Hr:.0f}mm)")
        y -= 6
        return y
