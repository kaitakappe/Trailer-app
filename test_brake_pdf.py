#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""制動装置強度計算のPDF出力テスト"""

import sys
import os

# main.py から BrakeStrengthPanel を取得
sys.path.insert(0, os.path.dirname(__file__))

from lib.brake_strength import compute_brake_drum_strength, format_brake_strength_result

# テスト用のブレーキドラム仕様
r_inner_mm = 80
r_outer_mm = 120
pressure_mpa = 0.5
width_mm = 100
tensile_strength = 1000
yield_strength = 850
shear_strength = 600

# 計算実行
result = compute_brake_drum_strength(
    r_inner_mm, r_outer_mm, pressure_mpa, width_mm,
    tensile_strength, yield_strength, shear_strength
)

print("計算結果：")
print(format_brake_strength_result(result))

# PDF を生成して確認
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
import math

w, h = A4

# フォント設定
try:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    
    # Windows のシステムフォント
    msgothic_path = r"C:\Windows\Fonts\msgothic.ttc"
    if os.path.exists(msgothic_path):
        pdfmetrics.registerFont(TTFont('msgothic', msgothic_path))
        font = 'msgothic'
    else:
        font = 'Helvetica'
except:
    font = 'Helvetica'

# PDF出力
pdf_path = os.path.join(os.path.dirname(__file__), 'test_brake_output.pdf')
c = canvas.Canvas(pdf_path, pagesize=A4)

y = h - 40
c.setFont(font, 14)
c.drawCentredString(w/2, y, '制動装置構造強度計算書（テスト）')
y -= 30

# 【入力条件】
c.setFont(font, 11)
c.drawString(50, y, '【入力条件】'); y -= 20

c.drawString(70, y, f"(a) ブレーキドラム仕様"); y -= 15
c.drawString(90, y, f"内径 ri = {r_inner_mm:.1f} mm"); y -= 15
c.drawString(90, y, f"外径 ro = {r_outer_mm:.1f} mm"); y -= 15
c.drawString(90, y, f"ドラム幅 w = {width_mm:.1f} mm"); y -= 15

c.drawString(70, y, f"(b) 最大ブレーキ内圧"); y -= 15
c.drawString(90, y, f"P = {pressure_mpa:.3f} MPa"); y -= 30

# 【計算式と計算結果】
c.drawString(50, y, '【計算式と計算結果】'); y -= 20

# 径比計算
c.drawString(70, y, f"◆ 径比の計算："); y -= 15
c.drawString(90, y, f"n = ro / ri = {r_outer_mm} / {r_inner_mm} = {result['k_diameter_ratio']:.4f}"); y -= 20

# Hoop応力
c.drawString(70, y, f"◆ Hoop応力の計算（内面）："); y -= 15
c.drawString(90, y, f"σθ = P × (n² + 1) / (n² - 1)"); y -= 15
c.drawString(90, y, f"  = {pressure_mpa:.3f} × ({result['k_diameter_ratio']:.4f}² + 1) / ({result['k_diameter_ratio']:.4f}² - 1)"); y -= 15
c.drawString(90, y, f"  = {result['sigma_hoop_inner']:.2f} N/mm²"); y -= 20

# 等価応力
c.drawString(70, y, f"◆ von Mises 等価応力："); y -= 15
c.drawString(90, y, f"σeq = {result['equivalent_stress']:.2f} N/mm²"); y -= 30

# 【材料強度】
c.drawString(50, y, '【材料強度】'); y -= 20
c.drawString(70, y, f"材質：SC25（ブレーキドラム用鋳鋼）"); y -= 15
c.drawString(70, y, f"引張強さ (σb) = {tensile_strength:.1f} N/mm²"); y -= 15
c.drawString(70, y, f"降伏点 (σy) = {yield_strength:.1f} N/mm²"); y -= 15
c.drawString(70, y, f"せん断強さ (τ) = {shear_strength:.1f} N/mm²"); y -= 30

# 【安全率】
c.drawString(50, y, '【安全率】'); y -= 20

# 引張応力に対する安全率
c.drawString(70, y, f"引張応力に対する安全率："); y -= 15
c.drawString(90, y, f"f = σb / σeq = {tensile_strength:.1f} / {result['equivalent_stress']:.2f} = {result['safety_factor_tensile']:.2f}倍"); y -= 15
mark_t = '合格' if result['ok_tensile'] else '不合格'
c.drawString(90, y, f"基準：f >= 1.6倍 ... {mark_t}"); y -= 20

# 降伏点に対する安全率
c.drawString(70, y, f"降伏点に対する安全率："); y -= 15
c.drawString(90, y, f"f = σy / σeq = {yield_strength:.1f} / {result['equivalent_stress']:.2f} = {result['safety_factor_yield']:.2f}倍"); y -= 15
mark_y = '合格' if result['ok_yield'] else '不合格'
c.drawString(90, y, f"基準：f >= 1.6倍 ... {mark_y}"); y -= 20

# せん断応力に対する安全率
c.drawString(70, y, f"せん断応力に対する安全率："); y -= 15
c.drawString(90, y, f"f = τ / σeq = {shear_strength:.1f} / {result['equivalent_stress']:.2f} = {result['safety_factor_shear']:.2f}倍"); y -= 15
mark_s = '合格' if result['ok_shear'] else '不合格'
c.drawString(90, y, f"基準：f >= 1.6倍 ... {mark_s}"); y -= 30

# 【総合判定】
c.drawString(50, y, '【総合判定】'); y -= 20
judge = '合格 OK' if result['ok_overall'] else '不合格 NG'
c.drawString(70, y, judge)

c.save()
print(f"\nPDF 出力完了: {pdf_path}")
